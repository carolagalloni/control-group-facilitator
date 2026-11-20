"""API FastAPI del Control Group Facilitator. Contratto: docs/API.md"""
from __future__ import annotations

import logging
import secrets
import threading
from pathlib import Path
from typing import Literal, Optional

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import advisor, datasources, scopes, service, stats
from .llm import LLMClient

log = logging.getLogger("cgf")
VERSION = "0.1.0"
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
SAMPLES_DIR = service.DATA_DIR / "samples"


class App:
    """Stato del processo: impostazioni, client SFMC (mock o live), client LLM."""

    def __init__(self):
        self.lock = threading.RLock()
        self.state = service.load_state()
        self.sfmc = None
        self.sfmc_error: str | None = None
        self.llm: LLMClient = None  # type: ignore[assignment]
        self.reconfigure()

    @property
    def settings(self) -> dict:
        return self.state["settings"]

    def reconfigure(self):
        s = self.settings
        self.llm = LLMClient(s["llm_base_url"], s["llm_model"], s["llm_enabled"])
        try:
            self.sfmc = service.make_sfmc(s)
            self.sfmc_error = None
        except Exception as e:  # noqa: BLE001
            self.sfmc_error = str(e)
            self.sfmc = service.MockSFMC()
            log.warning("SFMC live non configurabile, uso il mock: %s", e)
        if self.sfmc.mode == "mock":
            self._replay_mock()

    def _replay_mock(self):
        """Il mock è in memoria: al riavvio ricostruisce i dati dei control group salvati (deterministico)."""
        by_journey: dict[str, list[dict]] = {}
        for cg in self.state["control_groups"]:
            by_journey.setdefault(cg["journey_id"], []).append(cg)
            for key in ("assignment_de", "results_de"):
                a = cg["artifacts"][key]
                self.sfmc.create_de(a["key"], a["fields"])
        for jid, cgs in by_journey.items():
            j = service.internal_journey(jid)
            if j is not None:
                self.sfmc.simulate_journey(j, cgs)
        SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
        self._write_samples()

    def _write_samples(self):
        """Esporta le vendite come CSV/SQLite di esempio per provare le sorgenti esterne."""
        self.sfmc.export_sales_csv(SAMPLES_DIR / "sales_export.csv")
        import sqlite3
        db = SAMPLES_DIR / "sales.db"
        with sqlite3.connect(db) as con:
            self.sfmc.de["Sales"].to_sql("sales", con, if_exists="replace", index=False)

    def save(self):
        service.save_state(self.state)

    def journey(self, jid: str) -> dict:
        try:
            j = self.sfmc.get_journey(jid)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"Errore SFMC: {e}") from e
        if not j:
            raise HTTPException(404, "Journey non trovato")
        return j

    def cg(self, cid: str) -> dict:
        cg = next((c for c in self.state["control_groups"] if c["id"] == cid), None)
        if not cg:
            raise HTTPException(404, "Control group non trovato")
        return cg


core = App()


def _seed_demo():
    """Al primo avvio in mock crea un control group di esempio, così la dashboard non è vuota."""
    if core.sfmc.mode != "mock" or core.state.get("seeded"):
        return
    core.state["seeded"] = True
    if not core.state["control_groups"]:
        j = core.sfmc.get_journey("j-cart")
        req = {"name": "Carrello abbandonato – holdout 15%", "scope_id": "journey_incrementality",
               "activity_key": None, "holdout_pct": 0.15, "primary_kpi": "conversion_rate",
               "kpis": ["revenue_per_contact", "orders_per_contact", "avg_order_value"], "attribution_days": 30,
               "data_source": {"type": "sfmc_de", "config": {"sales_de_key": "Sales"}}, "guardrails": {}}
        cg = service.build_control_group(req, j)
        service.deploy(cg, core.sfmc)
        core.state["control_groups"].append(cg)
        core._write_samples()
    core.save()


_seed_demo()
api = FastAPI(title="Control Group Facilitator", version=VERSION)


# ----------------------------------------------------------------------------- modelli

class SettingsIn(BaseModel):
    llm_enabled: Optional[bool] = None
    llm_base_url: Optional[str] = None
    llm_model: Optional[str] = None
    sfmc_mode: Optional[Literal["mock", "live"]] = None
    sfmc_subdomain: Optional[str] = None
    sfmc_mid: Optional[str] = None
    sfmc_client_id: Optional[str] = None
    sfmc_client_secret: Optional[str] = None


class InterpretIn(BaseModel):
    question: str = Field(min_length=3)
    journey_id: str


class PositionsIn(BaseModel):
    journey_id: str
    scope_id: str
    activity_key: Optional[str] = None


KPI = Literal["revenue_per_contact", "conversion_rate", "orders_per_contact", "avg_order_value"]


class SizingIn(BaseModel):
    monthly_volume: int = Field(gt=0)
    baseline_conversion: float = Field(gt=0, lt=1)
    avg_order_value: float = Field(gt=0)
    aov_cv: float = Field(default=1.0, gt=0)
    expected_lift: float = Field(gt=0, lt=5)
    duration_days: int = Field(gt=0, le=730)
    alpha: float = Field(default=0.05, gt=0, lt=0.5)
    power: float = Field(default=0.8, gt=0.5, lt=1)
    kpi: Literal["revenue_per_contact", "conversion_rate"] = "revenue_per_contact"


class ExplainIn(BaseModel):
    journey_id: str
    scope_id: str
    sizing: dict
    request: dict


class DataSourceIn(BaseModel):
    type: Literal["sfmc_de", "csv", "sql"]
    config: dict = {}


class ControlGroupIn(BaseModel):
    name: str = Field(min_length=1)
    journey_id: str
    scope_id: str
    activity_key: Optional[str] = None
    holdout_pct: float = Field(gt=0, le=0.5)
    primary_kpi: KPI = "revenue_per_contact"
    kpis: list[KPI] = []
    attribution_days: int = Field(default=30, gt=0, le=365)
    data_source: DataSourceIn = DataSourceIn(type="sfmc_de", config={"sales_de_key": "Sales"})
    guardrails: dict = {}


# ----------------------------------------------------------------------------- sistema

def _public_settings() -> dict:
    s = dict(core.settings)
    s["sfmc_client_secret_set"] = bool(s.pop("sfmc_client_secret", ""))
    return s


@api.get("/api/health")
def health():
    s = core.settings
    return {"version": VERSION, "sfmc_mode": core.sfmc.mode, "sfmc_error": core.sfmc_error,
            "llm": {"base_url": s["llm_base_url"], "model": s["llm_model"], "enabled": s["llm_enabled"],
                    "reachable": core.llm.reachable()}}


@api.get("/api/settings")
def get_settings():
    return _public_settings()


@api.put("/api/settings")
def put_settings(body: SettingsIn):
    with core.lock:
        upd = body.model_dump(exclude_none=True)
        if upd.get("sfmc_client_secret") == "":
            upd.pop("sfmc_client_secret")
        core.settings.update(upd)
        core.save()
        core.reconfigure()
    return _public_settings()


# ----------------------------------------------------------------------------- catalogo

@api.get("/api/scopes")
def get_scopes():
    return scopes.SCOPES


def _with_active(j: dict) -> dict:
    act = [c["name"] for c in core.state["control_groups"] if c["journey_id"] == j["id"]]
    return {**j, "active_control_groups": act}


@api.get("/api/journeys")
def list_journeys():
    try:
        return [_with_active(j) for j in core.sfmc.list_journeys()]
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Errore SFMC: {e}") from e


@api.get("/api/journeys/{jid}")
def get_journey(jid: str):
    return _with_active(core.journey(jid))


# ----------------------------------------------------------------------------- advisor

def _check_scope(scope_id: str):
    sc = scopes.get(scope_id)
    if not sc:
        raise HTTPException(400, "Scopo sconosciuto")
    if not sc["enabled"]:
        raise HTTPException(400, f"Scopo non disponibile: {sc['disabled_reason']}")


@api.post("/api/advisor/interpret")
def interpret(body: InterpretIn):
    return advisor.interpret(core.llm, body.question, core.journey(body.journey_id))


@api.post("/api/advisor/positions")
def positions(body: PositionsIn):
    _check_scope(body.scope_id)
    return advisor.positions(core.llm, core.journey(body.journey_id), body.scope_id, body.activity_key)


@api.post("/api/stats/sizing")
def sizing(body: SizingIn):
    try:
        return stats.sizing(**body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@api.post("/api/advisor/explain-sizing")
def explain_sizing(body: ExplainIn):
    _check_scope(body.scope_id)
    return advisor.explain_sizing(core.llm, core.journey(body.journey_id), body.scope_id, body.request, body.sizing)


# ----------------------------------------------------------------------------- control group

@api.post("/api/control-groups")
def create_cg(body: ControlGroupIn):
    _check_scope(body.scope_id)
    journey = core.journey(body.journey_id)
    if body.scope_id == "touchpoint_value":
        if not body.activity_key:
            raise HTTPException(400, "Per il valore di un touchpoint serve l'attività su cui applicare l'holdout")
    if body.activity_key and not any(a["key"] == body.activity_key for a in journey["activities"]):
        raise HTTPException(400, "Attività non presente nel journey")
    clash = next((c for c in core.state["control_groups"] if c["journey_id"] == journey["id"]
                  and (c["scope_id"] == "journey_incrementality" or body.scope_id == "journey_incrementality"
                       or c["activity_key"] == body.activity_key)), None)
    if clash:
        raise HTTPException(409, (
            f"Sul journey «{journey['name']}» è già attivo il control group «{clash['name']}». Due holdout "
            "sovrapposti sugli stessi contatti si contaminano a vicenda e falsano il lift: elimina o concludi "
            "quello esistente prima di crearne uno nuovo."))
    req = body.model_dump()
    with core.lock:
        cg = service.build_control_group(req, journey)
        siblings = [c for c in core.state["control_groups"] if c["journey_id"] == journey["id"]]
        service.deploy(cg, core.sfmc, siblings)
        if any(s["status"] == "errore" for s in cg["deploy_log"]):
            cg["status"] = "errore deploy"
        core.state["control_groups"].append(cg)
        core.save()
        if core.sfmc.mode == "mock":
            core._write_samples()
    return cg


@api.get("/api/control-groups")
def list_cgs():
    return core.state["control_groups"]


@api.get("/api/control-groups/{cid}")
def get_cg(cid: str):
    return core.cg(cid)


@api.delete("/api/control-groups/{cid}")
def delete_cg(cid: str):
    with core.lock:
        cg = core.cg(cid)
        core.state["control_groups"].remove(cg)
        core.save()
        if core.sfmc.mode == "mock":
            j = service.internal_journey(cg["journey_id"])
            if j is not None:
                core.sfmc.simulate_journey(j, [c for c in core.state["control_groups"]
                                               if c["journey_id"] == j["id"]])
    return {"ok": True}


def _results(cg: dict) -> dict:
    try:
        snaps, source = service.load_snapshots(cg, core.sfmc)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Errore nel recupero dati: {e}") from e
    return service.analyze(cg, snaps, source)


@api.get("/api/control-groups/{cid}/results")
def results(cid: str):
    return _results(core.cg(cid))


@api.post("/api/control-groups/{cid}/refresh")
def refresh(cid: str):
    cg = core.cg(cid)
    with core.lock:
        if cg["data_source"]["type"] == "sfmc_de":
            try:
                if core.sfmc.mode == "mock":
                    core.sfmc.run_results_query(cg)
                else:
                    core.sfmc.run_query(f"CG_{cg['id'][3:]}_Results")
            except Exception as e:  # noqa: BLE001
                raise HTTPException(502, f"Impossibile eseguire la query in SFMC: {e}") from e
    return _results(cg)


@api.post("/api/control-groups/{cid}/narrative")
def narrative(cid: str):
    cg = core.cg(cid)
    res = _results(cg)
    if not res["kpis"]:
        return {"narrative": res["status"]["message"], "source": "regole"}
    return advisor.narrative(core.llm, cg, res)


# ----------------------------------------------------------------------------- sorgenti dati

@api.get("/api/datasources/types")
def ds_types():
    return datasources.TYPES


@api.post("/api/datasources/test")
def ds_test(body: DataSourceIn):
    try:
        return datasources.test(body.model_dump(), core.sfmc)
    except (KeyError, ValueError) as e:
        return {"ok": False, "message": str(e).strip("'\""), "columns": [], "sample": []}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"Errore: {e}", "columns": [], "sample": []}


@api.post("/api/datasources/upload")
async def ds_upload(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith((".csv", ".txt")):
        raise HTTPException(400, "Carica un file .csv")
    datasources.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(4)}.csv"
    dest = datasources.UPLOAD_DIR / name
    content = await file.read()
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(400, "File troppo grande (max 100 MB)")
    dest.write_bytes(content)
    try:
        df = pd.read_csv(dest, sep=None, engine="python")
    except Exception as e:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"CSV non leggibile: {e}") from e
    backend_dir = Path(__file__).resolve().parent.parent
    path = dest.relative_to(backend_dir).as_posix() if dest.is_relative_to(backend_dir) else str(dest)
    return {"path": path, "rows": len(df), "columns": [str(c) for c in df.columns]}


@api.get("/api/samples/sales.csv")
def sample_csv():
    p = SAMPLES_DIR / "sales_export.csv"
    if not p.is_file():
        raise HTTPException(404, "Esempio disponibile solo in modalità mock")
    return FileResponse(p, filename="sales_export.csv", media_type="text/csv")


# ----------------------------------------------------------------------------- frontend

if FRONTEND_DIST.is_dir():
    api.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

app = api
