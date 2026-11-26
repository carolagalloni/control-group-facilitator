import os
import tempfile

os.environ["CGF_DATA_DIR"] = tempfile.mkdtemp()

from fastapi.testclient import TestClient  # noqa: E402

from app.main import api, core  # noqa: E402

core.settings["llm_base_url"] = "http://127.0.0.1:9/v1"  # LLM irraggiungibile => fallback a regole
core.reconfigure()
client = TestClient(api)


def test_health_and_catalog():
    h = client.get("/api/health").json()
    assert h["sfmc_mode"] == "mock" and h["llm"]["reachable"] is False
    assert {s["id"] for s in client.get("/api/scopes").json()} >= {"journey_incrementality", "touchpoint_value"}
    j = client.get("/api/journeys/j-welcome").json()
    assert j["activities"][0]["type"] == "ENTRY"


def test_interpret_fallback_picks_touchpoint():
    r = client.post("/api/advisor/interpret",
                    json={"question": "L'SMS di reminder serve davvero?", "journey_id": "j-welcome"}).json()
    assert r["source"] == "regole" and r["scope_id"] == "touchpoint_value" and r["activity_key"] == "SMS1"


def test_full_flow_detects_hidden_lift():
    pos = client.post("/api/advisor/positions",
                      json={"journey_id": "j-welcome", "scope_id": "journey_incrementality"}).json()
    rec = next(c for c in pos["candidates"] if c["recommended"])
    assert rec["activity_key"] is None
    body = {"name": "Test", "journey_id": "j-welcome", "scope_id": "journey_incrementality",
            "holdout_pct": 0.2, "primary_kpi": "conversion_rate", "kpis": ["revenue_per_contact"],
            "attribution_days": 30}
    cg = client.post("/api/control-groups", json=body).json()
    assert all(s["status"] != "errore" for s in cg["deploy_log"])
    assert "HASHBYTES" in cg["artifacts"]["assignment_sql"]
    res = client.get(f"/api/control-groups/{cg['id']}/results").json()
    conv = next(k for k in res["kpis"] if k["id"] == "conversion_rate")
    assert res["srm"]["ok"]
    assert conv["ci_low"] < 0.10 < conv["ci_high"]  # il lift reale nascosto è 10%
    assert client.post("/api/control-groups", json=body).status_code == 409
    assert client.post(f"/api/control-groups/{cg['id']}/narrative").json()["source"] == "regole"
    assert client.delete(f"/api/control-groups/{cg['id']}").json()["ok"]


def test_sfmc_link_checked_and_used_in_artifacts():
    base = {"journey_ids": ["j-winback"], "data_source": {"type": "sfmc_de", "config": {"sales_de_key": "Sales"}}}
    ok = client.post("/api/sfmc/check-link", json={**base, "sfmc_link": {"de_folder": "Control group"}}).json()
    assert ok["ok"] and ok["verifiable"] and ok["resolved"]["j-winback"]["entry_de"] == "Winback_Entry"
    bad_link = {"journeys": {"j-winback": {"entry_de": "Non_Esiste", "contact_field": "CustomerID"}}}
    bad = client.post("/api/sfmc/check-link", json={**base, "sfmc_link": bad_link}).json()
    assert not bad["ok"] and any("Non_Esiste" in c["message"] for c in bad["checks"] if c["status"] == "error")
    bad_cols = {**base, "data_source": {"type": "sfmc_de", "config": {"sales_de_key": "Sales", "col_amount": "Totale"}}}
    r = client.post("/api/sfmc/check-link", json=bad_cols).json()
    assert any(c["item"] == "DE vendite" and c["status"] == "error" and "Totale" in c["message"] for c in r["checks"])

    body = {"name": "Link", "journey_ids": ["j-winback"], "scope_id": "journey_incrementality", "holdout_pct": 0.15,
            "attribution_days": 30, **{k: v for k, v in base.items() if k != "journey_ids"}}
    assert client.post("/api/initiatives", json={**body, "sfmc_link": bad_link}).status_code == 400
    link = {"de_folder": "Control group", "query_folder": "CG queries", "automation_folder": "CG",
            "journeys": {"j-winback": {"contact_field": "SubscriberKey", "entry_event_key": "DEAudience-winback"}}}
    ini = client.post("/api/initiatives", json={**body, "sfmc_link": link}).json()
    cg = ini["control_groups"][0]
    assert cg["sfmc_link"]["query_folder"] == "CG queries"
    assert any("in «Control group»" in s["step"] for s in cg["deploy_log"])
    assert "DEAudience-winback" in str(cg["artifacts"]["journey_change"]["decision_split"])
    assert "s.[Amount]" in cg["artifacts"]["results_sql"]
    assert client.delete(f"/api/initiatives/{ini['id']}").json()["ok"]


def test_external_sql_source():
    db = os.path.join(os.environ["CGF_DATA_DIR"], "samples", "sales.db")
    body = {"name": "Winback SQL", "journey_id": "j-winback", "scope_id": "journey_incrementality",
            "holdout_pct": 0.3, "primary_kpi": "conversion_rate", "attribution_days": 30,
            "data_source": {"type": "sql", "config": {"dsn": db,
                                                     "query": "SELECT OrderID, SubscriberKey, OrderDate, Amount FROM sales"}}}
    cg = client.post("/api/control-groups", json=body).json()
    res = client.get(f"/api/control-groups/{cg['id']}/results").json()
    assert "database SQL" in res["source"] and res["days_running"] > 0
    bad = client.post("/api/datasources/test", json={"type": "sql", "config": {"dsn": db, "query": "DELETE FROM sales"}})
    assert bad.json()["ok"] is False


def test_journey_search_is_paginated_and_filtered():
    r = client.get("/api/journeys", params={"page_size": 10}).json()
    assert r["total"] > 2000 and len(r["items"]) == 10 and r["facets"]["folder"]
    r = client.get("/api/journeys", params={"q": "carrello abbandonato", "status": "Running"}).json()
    assert r["items"] and all("carrello abbandonato" in j["name"].lower() and j["status"] == "Running"
                              for j in r["items"])
    r = client.get("/api/journeys", params={"q": "welcome"}).json()
    assert r["items"][0]["id"] == "j-welcome"
    r = client.get("/api/journeys", params={"folder": "Loyalty", "channel": "sms", "page": 2, "page_size": 5}).json()
    assert r["page"] == 2 and all(j["folder"] == "Loyalty" and "sms" in j["channels"] for j in r["items"])


def test_initiative_on_many_journeys_split_by_journey():
    found = client.get("/api/journeys", params={"q": "post-acquisto", "folder": "Retention", "status": "Running",
                                               "sort": "volume"}).json()["items"]
    free = [j["id"] for j in found if not j["active_control_groups"] and 5000 < j["monthly_volume"] < 60000][:2]
    body = {"name": "Post-acquisto multi", "journey_ids": free, "scope_id": "journey_incrementality",
            "holdout_pct": 0.2, "primary_kpi": "conversion_rate", "category": "Retention", "attribution_days": 30}
    ini = client.post("/api/initiatives", json=body).json()
    assert len(ini["journeys"]) == 2 and ini["category"] == "Retention"
    res = client.get(f"/api/initiatives/{ini['id']}/results").json()
    assert len(res["members"]) == 2 and all(m["results"]["days_running"] > 0 for m in res["members"])
    tot = res["total"]["groups"]["control"]["contacts"]
    assert tot == sum(m["results"]["groups"]["control"]["contacts"] for m in res["members"])
    assert res["total"]["srm"]["ok"]
    assert client.post("/api/initiatives", json=body).status_code == 409  # stessi journey già in test
    tp = {**body, "scope_id": "touchpoint_value", "activity_key": "EMAIL1"}
    assert client.post("/api/initiatives", json=tp).status_code == 400  # touchpoint solo su un journey
    ov = client.get("/api/overview").json()
    cat = next(c for c in ov["categories"] if c["category"] == "Retention")
    assert cat["journeys"] >= 2 and cat["incremental_revenue"]["ci_low"] <= cat["incremental_revenue"]["estimate"]
    assert {r["cg_id"] for r in ov["rows"]} >= {j["cg_id"] for j in ini["journeys"]}
    assert client.delete(f"/api/initiatives/{ini['id']}").json()["ok"]
    assert client.get(f"/api/initiatives/{ini['id']}").status_code == 404


def test_post_first_email_position_covers_everyone():
    pos = client.post("/api/advisor/positions",
                      json={"journey_id": "j-welcome", "scope_id": "journey_incrementality"}).json()
    alt = next(c for c in pos["candidates"] if c["activity_key"])
    assert alt["activity_key"] == "WAIT1" and alt["monthly_volume"] == 150000
    body = {"name": "Dopo prima email", "journey_id": "j-welcome", "scope_id": "journey_incrementality",
            "activity_key": "WAIT1", "holdout_pct": 0.2, "primary_kpi": "conversion_rate", "attribution_days": 30}
    cg = client.post("/api/control-groups", json=body).json()
    assert all(s["status"] != "errore" for s in cg["deploy_log"])
    assert "uscita" in " ".join(cg["artifacts"]["journey_change"]["steps"])
    res = client.get(f"/api/control-groups/{cg['id']}/results").json()
    assert res["days_running"] > 0 and res["srm"]["ok"]
    client.delete(f"/api/control-groups/{cg['id']}")
