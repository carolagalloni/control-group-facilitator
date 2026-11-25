"""Orchestrazione: deploy di un control group su SFMC e calcolo dei risultati."""
from __future__ import annotations

import json
import os
import secrets
from datetime import date
from pathlib import Path

import pandas as pd

from . import datasources, engine, sfmc_sql, stats
from .sfmc_mock import MockSFMC, internal_journey, now_iso

DATA_DIR = Path(os.environ.get("CGF_DATA_DIR") or Path(__file__).resolve().parent.parent / "data")
STATE_FILE = DATA_DIR / "state.json"

DEFAULT_SETTINGS = {
    "llm_enabled": True,
    "llm_base_url": "http://localhost:11434/v1",
    "llm_model": "qwen2.5:7b-instruct",
    "sfmc_mode": "mock",
    "sfmc_subdomain": "",
    "sfmc_mid": "",
    "sfmc_client_id": "",
    "sfmc_client_secret": "",
}


# ----------------------------------------------------------------------------- persistenza

def load_state() -> dict:
    if STATE_FILE.is_file():
        st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    else:
        st = {}
    st.setdefault("settings", {})
    st["settings"] = {**DEFAULT_SETTINGS, **st["settings"]}
    st.setdefault("control_groups", [])
    for cg in st["control_groups"]:
        normalize(cg)
    return st


CATEGORIES = ["Acquisizione", "Onboarding", "Carrello e conversione", "Cross-sell e upsell", "Retention",
              "Riattivazione", "Loyalty", "Transazionale"]
NO_CATEGORY = "Senza categoria"


def normalize(cg: dict) -> dict:
    """Control group salvati prima di iniziative e categorie: ognuno diventa un'iniziativa di un journey."""
    cg.setdefault("initiative_id", "in-" + cg["id"].removeprefix("cg-"))
    cg.setdefault("initiative_name", cg["name"])
    if not cg.get("category"):
        j = internal_journey(cg["journey_id"])
        cg["category"] = (j or {}).get("folder") or NO_CATEGORY
    return cg


def save_state(st: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(st, indent=2, ensure_ascii=False), encoding="utf-8")


# ----------------------------------------------------------------------------- deploy

def build_control_group(req: dict, journey: dict) -> dict:
    cid = secrets.token_hex(3)
    salt = secrets.token_hex(3)
    activity = next((a for a in journey["activities"] if a["key"] == req.get("activity_key")), None)
    touch = activity is not None
    assign_key, results_key = f"CG_Assign_{cid}", f"CG_Results_{cid}"
    sales_key = req["data_source"].get("config", {}).get("sales_de_key", "Sales")
    entry_de = journey.get("entry_de") or "ENTRY_DE"
    artifacts = {
        "assignment_de": {"key": assign_key, "fields": sfmc_sql.ASSIGN_FIELDS},
        "results_de": {"key": results_key, "fields": sfmc_sql.RESULTS_FIELDS},
        "assignment_sql": sfmc_sql.assignment_sql(entry_de, assign_key, salt, req["holdout_pct"],
                                                  journey["key"], touch),
        "results_sql": sfmc_sql.results_sql(assign_key, sales_key, results_key, req["attribution_days"], touch),
        "journey_change": sfmc_sql.journey_change(journey, activity, assign_key,
                                                  journey.get("entry_event_key") or "ENTRY_EVENT",
                                                  exit_control=req["scope_id"] == "journey_incrementality"),
        "automation": {
            "name": f"CG_{cid}_Daily",
            "schedule": "Ogni giorno alle 06:00 (prima dell'ingresso nel journey)",
            "steps": [
                f"1. Import/aggiornamento della DE di ingresso {entry_de} (attività esistente)",
                f"2. Query Activity CG_{cid}_Assign → {assign_key} (assegnazione deterministica)",
                f"3. Query Activity CG_{cid}_AssignFlag → {entry_de} (propaga CG_Group)",
                f"4. Query Activity CG_{cid}_Results → {results_key} (snapshot KPI)"
                + ("" if req["data_source"]["type"] == "sfmc_de" else " — non necessaria: KPI calcolati "
                   "dall'app con la sorgente esterna"),
            ],
        },
    }
    return {
        "id": f"cg-{cid}", "name": req["name"], "journey_id": journey["id"], "journey_name": journey["name"],
        "initiative_id": req.get("initiative_id") or f"in-{cid}",
        "initiative_name": req.get("initiative_name") or req["name"],
        "category": req.get("category") or journey.get("folder") or NO_CATEGORY,
        "scope_id": req["scope_id"], "activity_key": activity["key"] if activity else None,
        "activity_name": activity["name"] if activity else None,
        "holdout_pct": req["holdout_pct"], "primary_kpi": req["primary_kpi"],
        "kpis": list(dict.fromkeys([req["primary_kpi"], *req.get("kpis", [])])),
        "attribution_days": req["attribution_days"], "data_source": req["data_source"],
        "guardrails": {"srm_alpha": 0.001, "alert_negative_lift": True, **(req.get("guardrails") or {})},
        "salt": salt, "status": "attivo", "created_at": now_iso(), "artifacts": artifacts, "deploy_log": [],
    }


def deploy(cg: dict, sfmc, siblings: list[dict] | None = None) -> None:
    """siblings: altri control group già attivi sullo stesso journey (servono al mock)."""
    a = cg["artifacts"]
    log = cg["deploy_log"]

    def step(name, fn, manual_detail=None):
        if fn is None:
            log.append({"step": name, "status": "manuale", "detail": manual_detail})
            return
        try:
            status = fn()
            log.append({"step": name, "status": status,
                        "detail": "Eseguito in SFMC simulato" if status == "simulato" else "Eseguito in SFMC"})
        except Exception as e:  # noqa: BLE001 - riportiamo l'errore al cliente
            log.append({"step": name, "status": "errore", "detail": str(e)[:400]})

    step(f"Creazione DE di assegnazione {a['assignment_de']['key']}",
         lambda: sfmc.create_de(a["assignment_de"]["key"], a["assignment_de"]["fields"]))
    step(f"Creazione DE risultati {a['results_de']['key']}",
         lambda: sfmc.create_de(a["results_de"]["key"], a["results_de"]["fields"]))
    step("Query Activity di assegnazione",
         lambda: sfmc.create_query(f"CG_{cg['id'][3:]}_Assign", a["assignment_sql"], a["assignment_de"]["key"]))
    if cg["data_source"]["type"] == "sfmc_de":
        step("Query Activity dei risultati",
             lambda: sfmc.create_query(f"CG_{cg['id'][3:]}_Results", a["results_sql"], a["results_de"]["key"]))
    if sfmc.mode == "mock":
        step(f"Nuova versione journey con Decision Split ({a['journey_change']['description']})",
             lambda: "simulato")
        step("Automation giornaliera", lambda: "simulato")
        j = internal_journey(cg["journey_id"])
        step("Retro-simulazione di 75 giorni di test (dati sintetici con effetto reale nascosto)",
             lambda: (sfmc.simulate_journey(j, [*(siblings or []), cg]), "simulato")[1])
    else:
        step("Nuova versione journey con Decision Split", None,
             "Da applicare in Journey Builder seguendo i passi nella scheda «Modifica journey» "
             "(la modifica di un journey attivo via API è volutamente non automatica).")
        step("Automation giornaliera", None,
             "Creare l'automation in Automation Studio con gli step indicati nella scheda «Automation».")


# ----------------------------------------------------------------------------- risultati

def load_snapshots(cg: dict, sfmc) -> tuple[pd.DataFrame, str]:
    ds = cg["data_source"]
    a = cg["artifacts"]
    if ds["type"] == "sfmc_de":
        return sfmc.read_de(a["results_de"]["key"]), f"SFMC DE {a['results_de']['key']}"
    assign = sfmc.read_de(a["assignment_de"]["key"])
    sales = datasources.load_sales(ds, sfmc)
    start = pd.to_datetime(assign["AssignedDate"]).min().date() if len(assign) else date.today()
    snaps = engine.compute_snapshots(assign, sales, cg["attribution_days"], start, date.today(),
                                     touchpoint=bool(cg["activity_key"]))
    label = {"csv": "CSV", "sql": "database SQL"}[ds["type"]]
    return snaps, f"Assegnazioni da SFMC DE {a['assignment_de']['key']} + vendite da {label}"


def _group(row) -> dict:
    return {"contacts": int(row["Contacts"]), "converters": int(row["Converters"]), "orders": int(row["Orders"]),
            "revenue": float(row["Revenue"]), "revenue_sq": float(row["RevenueSq"]),
            "orders_sq": float(row["OrdersSq"]), "revenue_orders": float(row["RevenueOrders"])}


def analyze(cg: dict, snaps: pd.DataFrame, source: str) -> dict:
    if snaps is None or snaps.empty:
        return {"as_of": date.today().isoformat(), "days_running": 0, "source": source,
                "groups": {"control": None, "treatment": None}, "kpis": [], "srm": None,
                "incremental_revenue": None, "timeseries": [],
                "status": {"level": "warning", "message": "Nessun dato ancora disponibile: il primo snapshot "
                                                          "arriva dopo la prima esecuzione dell'automation."}}
    snaps = snaps.copy()
    for c in engine.SNAPSHOT_COLS[2:]:
        snaps[c] = pd.to_numeric(snaps[c], errors="coerce").fillna(0)
    snaps["SnapshotDate"] = pd.to_datetime(snaps["SnapshotDate"]).dt.date
    dates = sorted(snaps["SnapshotDate"].unique())

    timeseries = []
    for i, d in enumerate(dates, start=1):
        day = snaps[snaps["SnapshotDate"] == d].set_index("CG_Group")
        if not {"CONTROL", "TREATMENT"} <= set(day.index):
            continue
        c, t = _group(day.loc["CONTROL"]), _group(day.loc["TREATMENT"])
        if c["contacts"] < 30 or t["contacts"] < 30:
            continue
        k = stats.compare(c, t, cg["primary_kpi"])
        timeseries.append({"date": d.isoformat(), "day": i, "rel_lift": k["rel_lift"], "ci_low": k["ci_low"],
                           "ci_high": k["ci_high"], "p_value": k["p_value"],
                           "control_contacts": c["contacts"], "treatment_contacts": t["contacts"]})

    last = snaps[snaps["SnapshotDate"] == dates[-1]].set_index("CG_Group")
    if not {"CONTROL", "TREATMENT"} <= set(last.index):
        return {**analyze(cg, pd.DataFrame(), source),
                "status": {"level": "error", "message": "Lo snapshot più recente non contiene entrambi i gruppi."}}
    c, t = _group(last.loc["CONTROL"]), _group(last.loc["TREATMENT"])
    kpis = []
    for kid in cg["kpis"]:
        k = stats.compare(c, t, kid)
        k["primary"] = kid == cg["primary_kpi"]
        kpis.append(k)
    rpc = stats.compare(c, t, "revenue_per_contact")
    se = rpc.pop("_se_diff")
    for k in kpis:
        k.pop("_se_diff", None)
    inc = {"estimate": round(rpc["abs_diff"] * t["contacts"], 2),
           "ci_low": round((rpc["abs_diff"] - 1.96 * se) * t["contacts"], 2),
           "ci_high": round((rpc["abs_diff"] + 1.96 * se) * t["contacts"], 2)}
    srm = stats.srm_check(c["contacts"], t["contacts"], cg["holdout_pct"], cg["guardrails"].get("srm_alpha", 0.001))
    primary = next(k for k in kpis if k["primary"])
    days = len(dates)

    if not srm["ok"]:
        status = {"level": "error", "message": (
            f"Sample Ratio Mismatch: il controllo è il {stats._pct(srm['observed_pct'])} invece del "
            f"{stats._pct(srm['expected_pct'], 0)}. Verificare assegnazione e Decision Split prima di leggere i risultati.")}
    elif primary["significant"] and primary["rel_lift"] < 0 and cg["guardrails"].get("alert_negative_lift", True):
        status = {"level": "error", "message": "Lift negativo significativo: il journey sta riducendo le vendite."}
    elif primary["significant"]:
        status = {"level": "ok", "message": (f"Risultato significativo dopo {days} giorni: lift "
                                             f"{'+' if primary['rel_lift'] >= 0 else ''}{stats._pct(primary['rel_lift'])} su {primary['name'].lower()}.")}
    elif days < 14:
        status = {"level": "warning", "message": "Test appena avviato: i risultati non sono ancora leggibili."}
    else:
        status = {"level": "warning", "message": "Dati in raccolta: differenza non ancora significativa."}

    return {"as_of": dates[-1].isoformat(), "days_running": days, "source": source,
            "groups": {"control": {k: c[k] for k in ("contacts", "converters", "orders", "revenue")},
                       "treatment": {k: t[k] for k in ("contacts", "converters", "orders", "revenue")}},
            "kpis": kpis, "srm": srm, "incremental_revenue": inc, "timeseries": timeseries, "status": status}


def results_for(cg: dict, sfmc) -> tuple[dict | None, pd.DataFrame | None, str | None]:
    """Risultati di un singolo journey; gli errori di sorgente non bloccano le viste aggregate."""
    try:
        snaps, source = load_snapshots(cg, sfmc)
        return analyze(cg, snaps, source), snaps, None
    except Exception as e:  # noqa: BLE001
        return None, None, str(e)


def pool_snapshots(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Somma gli snapshot di più journey con la stessa % di holdout (stesse statistiche sufficienti).
    Si tengono solo le date presenti in tutti, così l'ultimo snapshot include ogni journey."""
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return pd.DataFrame(columns=engine.SNAPSHOT_COLS)
    cols = engine.SNAPSHOT_COLS[2:]
    norm = []
    for f in frames:
        f = f.copy()
        f["SnapshotDate"] = pd.to_datetime(f["SnapshotDate"]).dt.date
        for c in cols:
            f[c] = pd.to_numeric(f[c], errors="coerce").fillna(0)
        norm.append(f)
    last = min(f["SnapshotDate"].max() for f in norm)
    df = pd.concat(norm, ignore_index=True)
    df = df[df["SnapshotDate"] <= last]
    return df.groupby(["SnapshotDate", "CG_Group"], as_index=False)[cols].sum()[engine.SNAPSHOT_COLS]


def _member(cg: dict, res: dict | None, err: str | None) -> dict:
    return {"cg_id": cg["id"], "journey_id": cg["journey_id"], "journey_name": cg["journey_name"],
            "activity_name": cg.get("activity_name"), "status": cg["status"], "results": res, "error": err}


def initiative_results(cgs: list[dict], sfmc) -> dict:
    """Monitoraggio di un'iniziativa: un blocco per ogni journey + il totale (snapshot sommati)."""
    members, frames = [], []
    for cg in cgs:
        res, snaps, err = results_for(cg, sfmc)
        members.append(_member(cg, res, err))
        if snaps is not None:
            frames.append(snaps)
    if len(cgs) == 1:
        total = members[0]["results"]
    else:
        total = analyze(cgs[0], pool_snapshots(frames), f"Totale di {len(frames)} journey (snapshot sommati)")
    return {"total": total, "members": members}


def _row(cg: dict, res: dict | None, err: str | None) -> dict:
    row = {"cg_id": cg["id"], "initiative_id": cg["initiative_id"], "initiative_name": cg["initiative_name"],
           "category": cg["category"], "journey_id": cg["journey_id"], "journey_name": cg["journey_name"],
           "activity_name": cg.get("activity_name"), "scope_id": cg["scope_id"], "holdout_pct": cg["holdout_pct"],
           "error": err, "primary": None, "groups": None, "incremental_revenue": None, "srm_ok": None,
           "status": None, "days_running": 0}
    if res and res["kpis"]:
        row.update(primary=next(k for k in res["kpis"] if k["primary"]), groups=res["groups"],
                   incremental_revenue=res["incremental_revenue"], srm_ok=res["srm"]["ok"],
                   status=res["status"], days_running=res["days_running"])
    elif res:
        row["status"] = res["status"]
    return row


def overview(cgs: list[dict], sfmc) -> dict:
    """Vista per categoria: una riga per journey e i totali di categoria.
    Le % di holdout possono differire tra journey, quindi non si sommano gli snapshot: si somma il
    ricavo incrementale (stimato journey per journey) e la sua varianza."""
    rows = [_row(cg, *results_for(cg, sfmc)[::2]) for cg in cgs]
    cats: dict[str, dict] = {}
    for r in rows:
        c = cats.setdefault(r["category"], {"category": r["category"], "initiatives": set(), "journeys": 0,
                                            "control_contacts": 0, "treatment_contacts": 0, "treatment_revenue": 0.0,
                                            "inc": 0.0, "var": 0.0, "positive": 0, "negative": 0, "inconclusive": 0,
                                            "no_data": 0})
        c["initiatives"].add(r["initiative_id"])
        c["journeys"] += 1
        if not r["primary"]:
            c["no_data"] += 1
            continue
        c["control_contacts"] += r["groups"]["control"]["contacts"]
        c["treatment_contacts"] += r["groups"]["treatment"]["contacts"]
        c["treatment_revenue"] += r["groups"]["treatment"]["revenue"]
        inc = r["incremental_revenue"]
        c["inc"] += inc["estimate"]
        c["var"] += ((inc["ci_high"] - inc["ci_low"]) / (2 * 1.96)) ** 2
        p = r["primary"]
        c["positive" if p["significant"] and p["rel_lift"] > 0 else
          "negative" if p["significant"] else "inconclusive"] += 1
    out = []
    for c in cats.values():
        half = 1.96 * c.pop("var") ** 0.5
        inc = c.pop("inc")
        base = c["treatment_revenue"] - inc  # ricavo che i trattati avrebbero fatto senza le comunicazioni
        c["initiatives"] = len(c["initiatives"])
        c["incremental_revenue"] = {"estimate": round(inc, 2), "ci_low": round(inc - half, 2),
                                    "ci_high": round(inc + half, 2)}
        c["revenue_lift"] = round(inc / base, 5) if base > 0 else None
        c["revenue_lift_ci"] = ([round((inc - half) / base, 5), round((inc + half) / base, 5)]
                                if base > 0 else None)
        out.append(c)
    out.sort(key=lambda c: -c["incremental_revenue"]["estimate"])
    return {"categories": out, "rows": rows}


def make_sfmc(settings: dict):
    if settings["sfmc_mode"] == "live":
        from .sfmc_live import LiveSFMC
        return LiveSFMC(settings["sfmc_subdomain"], settings["sfmc_client_id"], settings["sfmc_client_secret"],
                        settings.get("sfmc_mid") or None)
    return MockSFMC()
