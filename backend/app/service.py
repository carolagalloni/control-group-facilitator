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
    "sfmc_export_dir": "",  # modalità "file": cartella degli export (vuota = data/sfmc_export)
}


def export_dir(settings: dict) -> Path:
    return Path(settings.get("sfmc_export_dir") or DATA_DIR / "sfmc_export")


# ----------------------------------------------------------------------------- persistenza

def load_state() -> dict:
    if STATE_FILE.is_file():
        st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    else:
        st = {}
    st.setdefault("settings", {})
    st["settings"] = {**DEFAULT_SETTINGS, **st["settings"]}
    st.setdefault("control_groups", [])
    st.setdefault("manual_journeys", [])
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


# ----------------------------------------------------------------------------- collegamento SFMC

def resolve_link(req: dict, journey: dict) -> dict:
    """Dove e su cosa agisce il control group in SFMC: DE di ingresso e chiave del contatto (per journey),
    cartelle di DE, query e automation. Quello che l'utente non indica si deduce dal journey."""
    link = req.get("sfmc_link") or {}
    jl = (link.get("journeys") or {}).get(journey["id"]) or {}
    s = lambda d, k: str(d.get(k) or "").strip()  # noqa: E731
    return {"entry_de": s(jl, "entry_de") or journey.get("entry_de") or "",
            "contact_field": s(jl, "contact_field") or "SubscriberKey",
            "entry_event_key": s(jl, "entry_event_key") or journey.get("entry_event_key") or "",
            "de_folder": s(link, "de_folder"), "query_folder": s(link, "query_folder"),
            "automation_folder": s(link, "automation_folder")}


def _has(fields: list[str], name: str) -> bool:
    return name.lower() in {f.lower() for f in fields}


def check_link(sfmc, journeys: list[dict], req: dict) -> list[dict]:
    """Verifica su SFMC che DE di ingresso, campi, cartelle e DE vendite esistano davvero.
    status: ok | warning | error | unverified (senza API non si può controllare)."""
    out: list[dict] = []
    can = sfmc.mode != "file"

    def add(item, status, message):
        out.append({"item": item, "status": status, "message": message})

    def fields_of(key):
        try:
            return sfmc.de_fields(key), None
        except Exception as e:  # noqa: BLE001
            return None, str(e)[:300]

    for j in journeys:
        link = resolve_link(req, j)
        name = f"«{j['name']}»"
        if not link["entry_de"]:
            add(f"DE di ingresso {name}", "error", "Non indicata: inserisci l'External Key della DE di ingresso.")
        elif not can:
            add(f"DE di ingresso {name}", "unverified",
                f"{link['entry_de']}: senza API controlla in Contact Builder che esista e abbia il campo "
                f"{link['contact_field']} e un campo CG_Group.")
        else:
            if sfmc.mode == "mock":
                ij = internal_journey(j["id"])
                if ij is not None:
                    sfmc._ensure_entries(ij)
            fields, err = fields_of(link["entry_de"])
            if err:
                add(f"DE di ingresso {name}", "error", f"Verifica non riuscita: {err}")
            elif fields is None:
                add(f"DE di ingresso {name}", "error", f"La DE «{link['entry_de']}» non esiste nella BU.")
            elif not _has(fields, link["contact_field"]):
                add(f"DE di ingresso {name}", "error",
                    f"La DE «{link['entry_de']}» non ha il campo «{link['contact_field']}». "
                    f"Campi: {', '.join(fields[:15])}.")
            elif not _has(fields, "CG_Group"):
                add(f"DE di ingresso {name}", "warning",
                    f"«{link['entry_de']}» esiste ma non ha il campo CG_Group: aggiungilo (Text 20) prima di "
                    "attivare l'automation, la query 1b lo scrive.")
            else:
                add(f"DE di ingresso {name}", "ok",
                    f"«{link['entry_de']}» esiste, chiave contatto {link['contact_field']}, campo CG_Group presente.")
        if not link["entry_event_key"]:
            add(f"Evento di ingresso {name}", "warning",
                "Event Definition Key non nota: nel Decision Split scegli a mano il campo CG_Group dell'evento.")

    link = resolve_link(req, journeys[0]) if journeys else resolve_link(req, {"id": ""})
    for label, key, ctype in (("Cartella delle Data Extension", "de_folder", "dataextension"),
                              ("Cartella delle Query Activity", "query_folder", "queryactivity")):
        if not link[key]:
            add(label, "ok", "Nessuna indicata: si usa la cartella principale.")
        elif not can:
            add(label, "unverified", f"«{link[key]}»: senza API crea gli oggetti in questa cartella a mano.")
        else:
            try:
                sfmc.find_folder(link[key], ctype)
                add(label, "ok", f"«{link[key]}» trovata.")
            except Exception as e:  # noqa: BLE001
                add(label, "error", str(e)[:300])
    if link["automation_folder"]:
        add("Cartella dell'automation", "ok" if can else "unverified",
            f"«{link['automation_folder']}»: l'automation si crea a mano in Automation Studio, in questa cartella.")

    ds = req.get("data_source") or {}
    if ds.get("type") == "sfmc_de":
        cfg = ds.get("config") or {}
        key = str(cfg.get("sales_de_key") or "").strip()
        cols = sfmc_sql.sales_columns(cfg)
        if not key:
            add("DE vendite", "error", "Non indicata: inserisci l'External Key della DE con gli ordini.")
        elif not can:
            add("DE vendite", "unverified",
                f"«{key}»: senza API controlla che abbia le colonne {', '.join(cols.values())}.")
        else:
            fields, err = fields_of(key)
            missing = [c for c in cols.values() if fields is not None and not _has(fields, c)]
            if err:
                add("DE vendite", "error", f"Verifica non riuscita: {err}")
            elif fields is None:
                add("DE vendite", "error", f"La DE «{key}» non esiste nella BU.")
            elif missing:
                add("DE vendite", "error", f"Nella DE «{key}» mancano le colonne {', '.join(missing)}. "
                                           f"Campi: {', '.join(fields[:15])}.")
            else:
                add("DE vendite", "ok", f"«{key}» esiste con le colonne {', '.join(cols.values())}.")
    return out


# ----------------------------------------------------------------------------- deploy

def build_control_group(req: dict, journey: dict, export: bool = False) -> dict:
    """export=True (modalità senza API): l'automation esporta anche le DE che l'app deve leggere."""
    cid = secrets.token_hex(3)
    salt = secrets.token_hex(3)
    activity = next((a for a in journey["activities"] if a["key"] == req.get("activity_key")), None)
    touch = activity is not None
    assign_key, results_key = f"CG_Assign_{cid}", f"CG_Results_{cid}"
    ds_cfg = req["data_source"].get("config", {})
    sales_key = ds_cfg.get("sales_de_key") or "Sales"
    link = resolve_link(req, journey)
    entry_de = link["entry_de"] or "ENTRY_DE"
    where_q = f" (cartella «{link['query_folder']}»)" if link["query_folder"] else ""
    artifacts = {
        "assignment_de": {"key": assign_key, "fields": sfmc_sql.ASSIGN_FIELDS, "folder": link["de_folder"] or None},
        "results_de": {"key": results_key, "fields": sfmc_sql.RESULTS_FIELDS, "folder": link["de_folder"] or None},
        "assignment_sql": sfmc_sql.assignment_sql(entry_de, assign_key, salt, req["holdout_pct"],
                                                  journey["key"], touch, link["contact_field"]),
        "results_sql": sfmc_sql.results_sql(assign_key, sales_key, results_key, req["attribution_days"], touch,
                                            ds_cfg if req["data_source"]["type"] == "sfmc_de" else None),
        "journey_change": sfmc_sql.journey_change(journey, activity, assign_key,
                                                  link["entry_event_key"] or "ENTRY_EVENT",
                                                  exit_control=req["scope_id"] == "journey_incrementality"),
        "automation": {
            "name": f"CG_{cid}_Daily",
            "folder": link["automation_folder"] or None,
            "schedule": "Ogni giorno alle 06:00 (prima dell'ingresso nel journey)",
            "steps": [
                f"1. Import/aggiornamento della DE di ingresso {entry_de} (attività esistente)",
                f"2. Query Activity CG_{cid}_Assign → {assign_key} (assegnazione deterministica){where_q}",
                f"3. Query Activity CG_{cid}_AssignFlag → {entry_de} (propaga CG_Group){where_q}",
                f"4. Query Activity CG_{cid}_Results → {results_key} (snapshot KPI){where_q}"
                + ("" if req["data_source"]["type"] == "sfmc_de" else " — non necessaria: KPI calcolati "
                   "dall'app con la sorgente esterna"),
            ],
        },
    }
    if export:
        # senza API l'app legge solo file: la DE dei risultati (2 righe al giorno, nessun dato personale)
        # oppure, con vendite fuori da SFMC, la DE di assegnazione
        exp = results_key if req["data_source"]["type"] == "sfmc_de" else assign_key
        artifacts["automation"]["steps"] += [
            f"5. Data Extract «Data Extension Extract» di {exp} → file {exp}.csv (delimitatore virgola, "
            "con intestazioni, UTF-8) nella cartella Safehouse",
            f"6. File Transfer: sposta {exp}.csv dalla Safehouse all'SFTP (o alla cartella) letta dall'app",
        ]
        artifacts["export_file"] = f"{exp}.csv"
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
        "sfmc_link": link,
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

    link = cg.get("sfmc_link") or {}
    de_folder, q_folder, au_folder = (link.get(k) or None for k in ("de_folder", "query_folder", "automation_folder"))
    in_de = f" in «{de_folder}»" if de_folder else ""
    in_q = f" in «{q_folder}»" if q_folder else ""
    in_au = f", cartella «{au_folder}»" if au_folder else ""
    entry_de = link.get("entry_de") or "di ingresso"
    if sfmc.mode == "file":
        # senza API nulla si crea da qui: si elencano i passi, con le definizioni nella scheda «Artefatti SFMC»
        manual = [
            (f"Creazione DE di assegnazione {a['assignment_de']['key']}{in_de}",
             "In Contact Builder → Data Extensions, con i campi indicati negli artefatti (PK SubscriberKey)."),
            (f"Creazione DE risultati {a['results_de']['key']}{in_de}",
             "In Contact Builder, con i campi indicati negli artefatti (PK SnapshotDate + CG_Group)."),
            (f"Campo CG_Group nella DE {entry_de}",
             "Aggiungi un campo Text(20) CG_Group alla DE di ingresso del journey, se manca."),
            (f"Query Activity di assegnazione{in_q}",
             "In Automation Studio: incolla lo SQL «Assegnazione» (azione Update)."),
        ]
        if cg["data_source"]["type"] == "sfmc_de":
            manual.append((f"Query Activity dei risultati{in_q}",
                           "In Automation Studio: incolla lo SQL «Risultati» (azione Update)."))
        manual += [
            ("Nuova versione journey con Decision Split",
             "In Journey Builder seguendo i passi nella scheda «Modifica journey»."),
            (f"Automation giornaliera con export{in_au}",
             f"Passi nella scheda «Automation», compresi Data Extract e File Transfer di {a.get('export_file')}: "
             "l'app legge quel file dalla cartella degli export o lo puoi caricare dal monitoraggio."),
        ]
        for name, detail in manual:
            step(name, None, detail)
        return
    step(f"Creazione DE di assegnazione {a['assignment_de']['key']}{in_de}",
         lambda: sfmc.create_de(a["assignment_de"]["key"], a["assignment_de"]["fields"], folder=de_folder))
    step(f"Creazione DE risultati {a['results_de']['key']}{in_de}",
         lambda: sfmc.create_de(a["results_de"]["key"], a["results_de"]["fields"], folder=de_folder))
    step(f"Query Activity di assegnazione{in_q}",
         lambda: sfmc.create_query(f"CG_{cg['id'][3:]}_Assign", a["assignment_sql"], a["assignment_de"]["key"],
                                   folder=q_folder))
    if cg["data_source"]["type"] == "sfmc_de":
        step(f"Query Activity dei risultati{in_q}",
             lambda: sfmc.create_query(f"CG_{cg['id'][3:]}_Results", a["results_sql"], a["results_de"]["key"],
                                       folder=q_folder))
    if sfmc.mode == "mock":
        step(f"Nuova versione journey con Decision Split ({a['journey_change']['description']})",
             lambda: "simulato")
        step(f"Automation giornaliera{in_au}", lambda: "simulato")
        j = internal_journey(cg["journey_id"])
        step("Retro-simulazione di 75 giorni di test (dati sintetici con effetto reale nascosto)",
             lambda: (sfmc.simulate_journey(j, [*(siblings or []), cg]), "simulato")[1])
    else:
        step("Nuova versione journey con Decision Split", None,
             "Da applicare in Journey Builder seguendo i passi nella scheda «Modifica journey» "
             "(la modifica di un journey attivo via API è volutamente non automatica).")
        step(f"Automation giornaliera{in_au}", None,
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


def make_sfmc(settings: dict, manual_journeys: list[dict] | None = None):
    if settings["sfmc_mode"] == "file":
        from .sfmc_file import FileSFMC
        return FileSFMC(export_dir(settings), manual_journeys if manual_journeys is not None else [])
    if settings["sfmc_mode"] == "live":
        from .sfmc_live import LiveSFMC
        return LiveSFMC(settings["sfmc_subdomain"], settings["sfmc_client_id"], settings["sfmc_client_secret"],
                        settings.get("sfmc_mid") or None)
    return MockSFMC()
