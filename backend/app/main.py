"""API FastAPI del Control Group Facilitator. Contratto: docs/API.md"""
from __future__ import annotations

import logging
import re
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
            self.sfmc = service.make_sfmc(s, self.state["manual_journeys"])
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


DEMO_INITIATIVES = [
    # (nome, cartella, argomento nel nome, n. journey, holdout)
    ("Promo stagionale autunno", "Retention", "Promo stagionale", 3, 0.10),
    ("Cross-sell post-acquisto", "Cross-sell e upsell", "Prodotti complementari", 2, 0.15),
    ("Programma fedeltà – punti in scadenza", "Loyalty", "Punti in scadenza", 2, 0.10),
]


def _seed_initiatives():
    """Iniziative di esempio su più journey (solo journey sintetici: i tre curati restano liberi per la demo)."""
    for name, folder, topic, n, pct in DEMO_INITIATIVES:
        found = core.sfmc.search_journeys(q=topic, status="Running", folder=folder, sort="volume", page_size=100)
        picks = [j for j in found["items"] if 8_000 <= j["monthly_volume"] <= 60_000][:n]
        iid = "in-" + secrets.token_hex(3)
        for j in picks:
            jd = core.sfmc.get_journey(j["id"])
            req = {"name": f"{name} · {jd['name']}", "scope_id": "journey_incrementality", "activity_key": None,
                   "holdout_pct": pct, "primary_kpi": "revenue_per_contact",
                   "kpis": ["conversion_rate", "orders_per_contact", "avg_order_value"], "attribution_days": 30,
                   "data_source": {"type": "sfmc_de", "config": {"sales_de_key": "Sales"}}, "guardrails": {},
                   "initiative_id": iid, "initiative_name": name, "category": folder}
            cg = service.build_control_group(req, jd)
            service.deploy(cg, core.sfmc)
            core.state["control_groups"].append(cg)


def _seed_demo():
    """Al primo avvio in mock crea control group e iniziative di esempio, così le dashboard non sono vuote."""
    if core.sfmc.mode != "mock":
        return
    if not core.state.get("seeded_initiatives"):
        core.state["seeded_initiatives"] = True
        _seed_initiatives()
        core._write_samples()
        core.save()
    if core.state.get("seeded"):
        return
    core.state["seeded"] = True
    if not any(c["journey_id"] == "j-cart" for c in core.state["control_groups"]):
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
    sfmc_mode: Optional[Literal["mock", "live", "file"]] = None
    sfmc_export_dir: Optional[str] = None
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


class JourneyLinkIn(BaseModel):
    entry_de: str = ""         # External Key della DE di ingresso (vuoto = quella letta dal journey)
    contact_field: str = ""    # campo con la chiave del contatto nella DE di ingresso (vuoto = SubscriberKey)
    entry_event_key: str = ""  # Event Definition Key, per il Decision Split


class SfmcLinkIn(BaseModel):
    """Collegamento SFMC: dove creare gli oggetti e su quali DE agire."""
    de_folder: str = ""
    query_folder: str = ""
    automation_folder: str = ""
    journeys: dict[str, JourneyLinkIn] = {}


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
    category: Optional[str] = None
    sfmc_link: SfmcLinkIn = SfmcLinkIn()


class CheckLinkIn(BaseModel):
    journey_ids: list[str] = Field(min_length=1, max_length=50)
    sfmc_link: SfmcLinkIn = SfmcLinkIn()
    data_source: DataSourceIn = DataSourceIn(type="sfmc_de", config={"sales_de_key": "Sales"})


class ManualJourneyIn(BaseModel):
    """Modalità senza API: il journey non si legge da SFMC, lo descrive l'utente."""
    name: str = Field(min_length=1)
    key: str = ""
    entry_de: str = Field(min_length=1)
    monthly_volume: int = Field(gt=0)
    conversion_rate: float = Field(gt=0, lt=1)
    avg_order_value: float = Field(gt=0)
    expected_lift: float = Field(default=0.08, gt=0, lt=5)
    messages: list[str] = []
    folder: Optional[str] = None


class InitiativeIn(ControlGroupIn):
    """Un'iniziativa = lo stesso control group applicato a uno o più journey (un holdout per journey)."""
    journey_id: Optional[str] = None  # type: ignore[assignment]
    journey_ids: list[str] = Field(min_length=1, max_length=50)


# ----------------------------------------------------------------------------- sistema

def _public_settings() -> dict:
    s = dict(core.settings)
    s["sfmc_client_secret_set"] = bool(s.pop("sfmc_client_secret", ""))
    return s


@api.get("/api/health")
def health():
    s = core.settings
    return {"version": VERSION, "sfmc_mode": core.sfmc.mode, "sfmc_error": core.sfmc_error,
            "sfmc_export_dir": str(core.sfmc.folder) if core.sfmc.mode == "file" else None,
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
def list_journeys(q: str = "", status: str = "", folder: str = "", channel: str = "", sort: str = "name",
                  page: int = 1, page_size: int = 25):
    """Ricerca paginata: una BU può avere migliaia di journey, non si restituisce mai tutto il catalogo."""
    try:
        out = core.sfmc.search_journeys(q=q.strip(), status=status, folder=folder, channel=channel, sort=sort,
                                        page=page, page_size=page_size)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Errore SFMC: {e}") from e
    out["items"] = [_with_active(j) for j in out["items"]]
    return out


@api.get("/api/categories")
def get_categories():
    used = {c["category"] for c in core.state["control_groups"]}
    return [*service.CATEGORIES, *sorted(used - set(service.CATEGORIES))]


@api.post("/api/journeys/manual")
def add_manual_journey(body: ManualJourneyIn):
    if core.sfmc.mode != "file":
        raise HTTPException(400, "I journey si inseriscono a mano solo nella modalità senza API (export su file)")
    with core.lock:
        n = len(core.state["manual_journeys"]) + 1
        key = body.key.strip() or re.sub(r"\W+", "_", body.name.strip())[:40]
        j = {"id": f"m-{secrets.token_hex(3)}", "key": key, "name": body.name.strip(),
             "entry_de": body.entry_de.strip(), "monthly_volume": body.monthly_volume, "folder": body.folder,
             "baseline": {"conversion_rate": body.conversion_rate, "avg_order_value": body.avg_order_value,
                          "expected_lift": body.expected_lift},
             "messages": [m.strip() for m in body.messages if m.strip()], "status": "Running", "n": n}
        core.state["manual_journeys"].append(j)
        core.save()
    return _with_active(core.journey(j["id"]))


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

def _validate(journey: dict, scope_id: str, activity_key: str | None):
    if scope_id == "touchpoint_value" and not activity_key:
        raise HTTPException(400, "Per il valore di un touchpoint serve l'attività su cui applicare l'holdout")
    if activity_key and not any(a["key"] == activity_key for a in journey["activities"]):
        raise HTTPException(400, f"Attività non presente nel journey «{journey['name']}»")
    clash = next((c for c in core.state["control_groups"] if c["journey_id"] == journey["id"]
                  and (c["scope_id"] == "journey_incrementality" or scope_id == "journey_incrementality"
                       or c["activity_key"] == activity_key)), None)
    if clash:
        raise HTTPException(409, (
            f"Sul journey «{journey['name']}» è già attivo il control group «{clash['name']}». Due holdout "
            "sovrapposti sugli stessi contatti si contaminano a vicenda e falsano il lift: elimina o concludi "
            "quello esistente prima di crearne uno nuovo."))


def _check_link_or_400(journeys: list[dict], req: dict) -> None:
    """Prima di creare qualunque cosa: DE, campi e cartelle devono esistere (dove si può verificare)."""
    errors = [c for c in service.check_link(core.sfmc, journeys, req) if c["status"] == "error"]
    if errors:
        raise HTTPException(400, "Collegamento SFMC non valido: "
                                 + " · ".join(f"{c['item']}: {c['message']}" for c in errors))


@api.post("/api/sfmc/check-link")
def check_link(body: CheckLinkIn):
    journeys = [core.journey(j) for j in dict.fromkeys(body.journey_ids)]
    checks = service.check_link(core.sfmc, journeys, body.model_dump())
    links = {j["id"]: service.resolve_link(body.model_dump(), j) for j in journeys}
    return {"verifiable": core.sfmc.mode != "file", "ok": not any(c["status"] == "error" for c in checks),
            "checks": checks, "resolved": links}


def _deploy(req: dict, journey: dict) -> dict:
    cg = service.build_control_group(req, journey, export=core.sfmc.mode == "file")
    siblings = [c for c in core.state["control_groups"] if c["journey_id"] == journey["id"]]
    service.deploy(cg, core.sfmc, siblings)
    if any(s["status"] == "errore" for s in cg["deploy_log"]):
        cg["status"] = "errore deploy"
    core.state["control_groups"].append(cg)
    return cg


@api.post("/api/control-groups")
def create_cg(body: ControlGroupIn):
    _check_scope(body.scope_id)
    journey = core.journey(body.journey_id)
    _validate(journey, body.scope_id, body.activity_key)
    _check_link_or_400([journey], body.model_dump())
    with core.lock:
        cg = _deploy(body.model_dump(), journey)
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


def _remove(cgs: list[dict]):
    with core.lock:
        for cg in cgs:
            core.state["control_groups"].remove(cg)
        core.save()
        if core.sfmc.mode == "mock":
            for jid in {cg["journey_id"] for cg in cgs}:
                j = service.internal_journey(jid)
                if j is not None:
                    core.sfmc.simulate_journey(j, [c for c in core.state["control_groups"]
                                                   if c["journey_id"] == jid])


@api.delete("/api/control-groups/{cid}")
def delete_cg(cid: str):
    _remove([core.cg(cid)])
    return {"ok": True}


# ----------------------------------------------------------------------------- iniziative

def _initiative(iid: str) -> list[dict]:
    cgs = [c for c in core.state["control_groups"] if c["initiative_id"] == iid]
    if not cgs:
        raise HTTPException(404, "Iniziativa non trovata")
    return cgs


def _initiative_summary(cgs: list[dict]) -> dict:
    c0 = cgs[0]
    status = "errore deploy" if any(c["status"] == "errore deploy" for c in cgs) else c0["status"]
    return {"id": c0["initiative_id"], "name": c0["initiative_name"], "category": c0["category"],
            "scope_id": c0["scope_id"], "holdout_pct": c0["holdout_pct"], "primary_kpi": c0["primary_kpi"],
            "kpis": c0["kpis"], "attribution_days": c0["attribution_days"], "created_at": c0["created_at"],
            "status": status,
            "journeys": [{"cg_id": c["id"], "journey_id": c["journey_id"], "journey_name": c["journey_name"],
                          "activity_name": c.get("activity_name"), "status": c["status"]} for c in cgs]}


@api.post("/api/initiatives")
def create_initiative(body: InitiativeIn):
    _check_scope(body.scope_id)
    ids = list(dict.fromkeys(body.journey_ids))
    if len(ids) > 1 and body.scope_id != "journey_incrementality":
        raise HTTPException(400, "Più journey nella stessa iniziativa solo per l'incrementalità del journey: "
                                 "il valore di un touchpoint riguarda un messaggio di un journey specifico.")
    journeys = [core.journey(j) for j in ids]
    activity = body.activity_key if len(ids) == 1 else None
    for j in journeys:  # tutto validato prima di toccare SFMC: o si crea tutto o niente
        _validate(j, body.scope_id, activity)
    _check_link_or_400(journeys, body.model_dump())
    iid = "in-" + secrets.token_hex(3)
    out = []
    with core.lock:
        for j in journeys:
            req = {**body.model_dump(exclude={"journey_ids"}), "journey_id": j["id"], "activity_key": activity,
                   "initiative_id": iid, "initiative_name": body.name,
                   "name": body.name if len(journeys) == 1 else f"{body.name} · {j['name']}"}
            out.append(_deploy(req, j))
        core.save()
        if core.sfmc.mode == "mock":
            core._write_samples()
    return {**_initiative_summary(out), "control_groups": out}


@api.get("/api/initiatives")
def list_initiatives():
    groups: dict[str, list[dict]] = {}
    for c in core.state["control_groups"]:
        groups.setdefault(c["initiative_id"], []).append(c)
    return [_initiative_summary(g) for g in groups.values()]


@api.get("/api/initiatives/{iid}")
def get_initiative(iid: str):
    cgs = _initiative(iid)
    return {**_initiative_summary(cgs), "control_groups": cgs}


@api.get("/api/initiatives/{iid}/results")
def initiative_results(iid: str):
    return service.initiative_results(_initiative(iid), core.sfmc)


@api.post("/api/initiatives/{iid}/refresh")
def initiative_refresh(iid: str):
    for cg in _initiative(iid):
        refresh(cg["id"])
    return initiative_results(iid)


@api.post("/api/initiatives/{iid}/narrative")
def initiative_narrative(iid: str):
    cgs = _initiative(iid)
    res = service.initiative_results(cgs, core.sfmc)["total"]
    if not res or not res["kpis"]:
        return {"narrative": res["status"]["message"] if res else "Nessun dato disponibile.", "source": "regole"}
    names = ", ".join(c["journey_name"] for c in cgs)
    return advisor.narrative(core.llm, {**cgs[0], "name": cgs[0]["initiative_name"], "journey_name": names}, res)


@api.delete("/api/initiatives/{iid}")
def delete_initiative(iid: str):
    _remove(_initiative(iid))
    return {"ok": True}


@api.get("/api/overview")
def get_overview():
    return service.overview(core.state["control_groups"], core.sfmc)


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
        if cg["data_source"]["type"] == "sfmc_de" and core.sfmc.mode != "file":  # in "file" si rilegge l'export
            try:
                if core.sfmc.mode == "mock":
                    core.sfmc.run_results_query(cg)
                else:
                    core.sfmc.run_query(f"CG_{cg['id'][3:]}_Results")
            except Exception as e:  # noqa: BLE001
                raise HTTPException(502, f"Impossibile eseguire la query in SFMC: {e}") from e
    return _results(cg)


@api.post("/api/control-groups/{cid}/export")
async def upload_export(cid: str, file: UploadFile = File(...)):
    """Modalità senza API: carica a mano l'export della DE che l'app deve leggere (risultati o assegnazione)."""
    cg = core.cg(cid)
    if core.sfmc.mode != "file":
        raise HTTPException(400, "Il caricamento degli export serve solo nella modalità senza API")
    a = cg["artifacts"]
    key = a["results_de"]["key"] if cg["data_source"]["type"] == "sfmc_de" else a["assignment_de"]["key"]
    raw = await file.read()
    if len(raw) > 200 * 1024 * 1024:
        raise HTTPException(400, "File troppo grande (max 200 MB)")
    try:
        core.sfmc.save_export(key, raw)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Export non leggibile: {e}") from e
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

@api.middleware("http")
async def _no_cache_html(request, call_next):
    """index.html sempre rivalidato: dopo un aggiornamento il browser non resta sulla versione vecchia."""
    resp = await call_next(request)
    if resp.headers.get("content-type", "").startswith("text/html"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


if FRONTEND_DIST.is_dir():
    api.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

app = api
