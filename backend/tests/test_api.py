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
