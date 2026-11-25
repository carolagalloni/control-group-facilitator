"""Modalità senza API: journey inseriti a mano, deploy come checklist manuale, risultati letti dagli export."""
import os
import tempfile

os.environ.setdefault("CGF_DATA_DIR", tempfile.mkdtemp())

from fastapi.testclient import TestClient  # noqa: E402

from app import engine  # noqa: E402
from app.main import api, core  # noqa: E402
from app.sfmc_mock import MockSFMC  # noqa: E402

client = TestClient(api)


def _results_export(lift: float) -> bytes:
    """Export della DE risultati come lo produrrebbe SFMC: generato col motore su dati simulati."""
    m = MockSFMC()
    j = next(x for x in __import__("app.sfmc_mock", fromlist=["JOURNEYS"]).JOURNEYS if x["id"] == "j-cart")
    cg = {"holdout_pct": 0.2, "salt": "abc123", "activity_key": None, "scope_id": "journey_incrementality"}
    assign, mult = m._assign(cg, {**j, "true_lift": {"journey": lift}})
    sales = m._gen_sales(j, mult)
    snaps = engine.compute_snapshots(assign, sales, 30, m.start, m.today, touchpoint=False)
    return snaps.to_csv(index=False).encode("utf-16")  # le Data Extract spesso escono in UTF-16


def test_file_mode_end_to_end():
    folder = tempfile.mkdtemp()
    old = dict(core.settings)
    client.put("/api/settings", json={"sfmc_mode": "file", "sfmc_export_dir": folder})
    try:
        h = client.get("/api/health").json()
        assert h["sfmc_mode"] == "file" and h["sfmc_export_dir"] == folder
        j = client.post("/api/journeys/manual", json={
            "name": "Carrello abbandonato IT", "entry_de": "Cart_Entry", "monthly_volume": 40000,
            "conversion_rate": 0.08, "avg_order_value": 120, "messages": ["Email promemoria", "SMS codice sconto"],
        }).json()
        assert [a["type"] for a in j["activities"]] == ["ENTRY", "EMAIL", "SMS", "EXIT"]
        found = client.get("/api/journeys", params={"q": "carrello"}).json()
        assert found["total"] == 1 and found["items"][0]["id"] == j["id"]

        ini = client.post("/api/initiatives", json={
            "name": "Carrello IT", "journey_ids": [j["id"]], "scope_id": "journey_incrementality",
            "holdout_pct": 0.2, "primary_kpi": "conversion_rate", "category": "Carrello e conversione"}).json()
        cg = ini["control_groups"][0]
        assert all(s["status"] == "manuale" for s in cg["deploy_log"])
        assert "Cart_Entry" in cg["artifacts"]["assignment_sql"]
        assert cg["artifacts"]["export_file"] in " ".join(cg["artifacts"]["automation"]["steps"])

        r = client.get(f"/api/control-groups/{cg['id']}/results")
        assert r.status_code == 400 and cg["artifacts"]["export_file"] in r.json()["detail"]

        up = client.post(f"/api/control-groups/{cg['id']}/export",
                         files={"file": ("export.csv", _results_export(0.12), "text/csv")})
        assert up.status_code == 200, up.text
        res = up.json()
        conv = next(k for k in res["kpis"] if k["id"] == "conversion_rate")
        assert res["srm"]["ok"] and conv["ci_low"] < 0.12 < conv["ci_high"]
        assert client.post(f"/api/control-groups/{cg['id']}/refresh").status_code == 200
        client.delete(f"/api/initiatives/{ini['id']}")
    finally:
        client.put("/api/settings", json={"sfmc_mode": old["sfmc_mode"], "sfmc_export_dir": old["sfmc_export_dir"]})
    assert client.post("/api/journeys/manual", json={
        "name": "x", "entry_de": "y", "monthly_volume": 1, "conversion_rate": 0.1, "avg_order_value": 1}).status_code == 400
