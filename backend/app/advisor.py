"""Advisor: l'LLM locale interpreta, argomenta e spiega. Numeri e vincoli restano deterministici.

Ogni funzione prova l'LLM e, se non disponibile o se la risposta non è valida, usa regole esplicite.
Le risposte LLM sono sempre validate contro le opzioni ammesse (nessun id/attività inventati).
"""
from __future__ import annotations

import json
import re

from . import scopes
from .llm import LLMClient, LLMUnavailable

SYSTEM = ("Sei un consulente senior di marketing analytics esperto di Salesforce Marketing Cloud e di "
          "esperimenti con gruppo di controllo (holdout). Rispondi sempre in italiano, in modo conciso, "
          "concreto e onesto: se un test non è fattibile dillo chiaramente. Non inventare numeri: usa solo "
          "quelli forniti.")

MESSAGING = ("EMAIL", "SMS", "PUSH")


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%".replace(".", ",")


def _n(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


# ----------------------------------------------------------------------------- interpret

def _rules_interpret(question: str, journey: dict) -> dict:
    q = question.lower()
    acts = [a for a in journey["activities"] if a["type"] in MESSAGING]
    channel_words = {"sms": "SMS", "push": "PUSH", "notifica": "PUSH", "email": "EMAIL", "mail": "EMAIL",
                     "newsletter": "EMAIL"}
    target = None
    for word, typ in channel_words.items():
        if word in q:
            cands = [a for a in acts if a["type"] == typ]
            # preferisci l'attività il cui nome condivide parole con la domanda
            cands.sort(key=lambda a: -sum(w in q for w in re.findall(r"\w{4,}", a["name"].lower())))
            if cands:
                target = cands[0]
                break
    if target is None:
        for a in acts:
            if any(w in q for w in re.findall(r"\w{5,}", a["name"].lower())):
                target = a
                break
    if any(w in q for w in ["tutto il marketing", "complessivo del crm", "tutte le comunicazioni", "universal"]):
        return {"scope_id": "journey_incrementality", "activity_key": None, "confidence": "bassa",
                "rationale": ("La domanda riguarda l'holdout universale, non ancora disponibile nella demo: "
                              "propongo di partire dall'incrementalità di questo journey."),
                "kpi_suggestion": "revenue_per_contact"}
    if any(w in q for w in ["frequenz", "troppe", "troppi", "meno comunicazioni", "satur"]):
        return {"scope_id": "journey_incrementality", "activity_key": None, "confidence": "bassa",
                "rationale": ("La domanda riguarda la frequenza di contatto, scopo non ancora disponibile: "
                              "un primo passo è misurare l'incrementalità dell'intero journey."),
                "kpi_suggestion": "revenue_per_contact"}
    if target is not None and any(w in q for w in ["serve", "utile", "funziona", "vale", "inutile", "togliere",
                                                   "eliminare", "singol", "specific", "reminder", "solo"]):
        return {"scope_id": "touchpoint_value", "activity_key": target["key"], "confidence": "media",
                "rationale": f"La domanda riguarda una comunicazione specifica («{target['name']}»): "
                             "serve un holdout immediatamente prima di quell'attività.",
                "kpi_suggestion": "conversion_rate" if "conver" in q else "revenue_per_contact"}
    return {"scope_id": "journey_incrementality", "activity_key": None, "confidence": "media",
            "rationale": ("La domanda riguarda il valore del journey nel suo complesso: holdout all'ingresso, "
                          "con KPI sulle vendite."),
            "kpi_suggestion": "conversion_rate" if "conver" in q else "revenue_per_contact"}


def interpret(llm: LLMClient, question: str, journey: dict) -> dict:
    acts = [{"key": a["key"], "nome": a["name"], "tipo": a["type"]} for a in journey["activities"]
            if a["type"] in MESSAGING]
    prompt = f"""Domanda di business del cliente: "{question}"
Journey: {journey['name']}. Attività di comunicazione: {json.dumps(acts, ensure_ascii=False)}
Scopi disponibili:
- journey_incrementality: misura il valore dell'intero journey (holdout all'ingresso)
- touchpoint_value: misura il valore di UNA comunicazione specifica (holdout prima di quella attività)
Rispondi SOLO con JSON: {{"scope_id": "...", "activity_key": "chiave attività o null",
"confidence": "alta|media|bassa", "rationale": "max 2 frasi", "kpi_suggestion": "revenue_per_contact|conversion_rate"}}"""
    try:
        r = llm.chat_json(SYSTEM, prompt)
        keys = {a["key"] for a in acts}
        scope_id = r.get("scope_id")
        if scope_id not in scopes.ENABLED:
            raise LLMUnavailable("scope non valido")
        ak = r.get("activity_key")
        ak = ak if ak in keys else None
        if scope_id == "touchpoint_value" and ak is None:
            ak = _rules_interpret(question, journey).get("activity_key")
            if ak is None:
                raise LLMUnavailable("touchpoint senza attività")
        if scope_id == "journey_incrementality":
            ak = None
        return {"scope_id": scope_id, "activity_key": ak,
                "confidence": r.get("confidence") if r.get("confidence") in ("alta", "media", "bassa") else "media",
                "rationale": str(r.get("rationale", ""))[:600],
                "kpi_suggestion": r.get("kpi_suggestion") if r.get("kpi_suggestion") in
                ("revenue_per_contact", "conversion_rate") else "revenue_per_contact",
                "source": "llm"}
    except (LLMUnavailable, KeyError, TypeError, ValueError):
        return {**_rules_interpret(question, journey), "source": "regole"}


# ----------------------------------------------------------------------------- positions

def _candidates(journey: dict, scope_id: str, activity_key: str | None) -> list[dict]:
    entry_vol = journey["monthly_volume"]
    acts = journey["activities"]
    if scope_id == "journey_incrementality":
        first = next((a for a in acts if a["type"] in MESSAGING), None)
        cands = [{
            "id": "pos-entry", "activity_key": None, "label": "All'ingresso del journey",
            "description": "Il controllo entra nel journey ed esce subito: non riceve nessuna comunicazione.",
            "monthly_volume": entry_vol, "recommended": True,
            "expected_lift": journey["baseline"].get("expected_lift", 0.08),
            "pros": ["Misura l'effetto totale del journey sulle vendite",
                     "Massimo volume disponibile: il test arriva prima alla significatività",
                     "Implementazione semplice e robusta (un solo Decision Split)"],
            "cons": ["Non dice quale singola comunicazione funziona meglio"],
        }]
        if first:
            nxt = next((a for a in acts if a["type"] in MESSAGING and a["key"] != first["key"]), None)
            if nxt:
                cands.append({
                    "id": f"pos-{nxt['key']}", "activity_key": nxt["key"],
                    "label": f"Dopo «{first['name']}»",
                    "description": "Tutti ricevono il primo invio; il controllo salta il resto del journey.",
                    "monthly_volume": nxt["monthly_volume"], "recommended": False,
                    "expected_lift": round(journey["baseline"].get("expected_lift", 0.08) / 2, 3),
                    "pros": ["Misura il valore dei follow-up rispetto al solo primo messaggio",
                             "Il primo invio (spesso transazionale/di servizio) resta garantito a tutti"],
                    "cons": ["Effetto atteso più piccolo: richiede più volume o più tempo",
                             "Non misura il valore del primo invio"],
                })
        return cands

    cands = []
    for a in acts:
        if a["type"] not in MESSAGING:
            continue
        cands.append({
            "id": f"pos-{a['key']}", "activity_key": a["key"], "label": f"Prima di «{a['name']}»",
            "description": f"Il controllo salta solo «{a['name']}» e prosegue nel journey.",
            "monthly_volume": a["monthly_volume"], "recommended": False,
            "expected_lift": 0.03,
            "pros": [f"Isola il contributo di «{a['name']}» ({a['type']})",
                     "Il resto del journey resta identico per entrambi i gruppi"],
            "cons": [f"Raggiunge solo il {_fmt_pct(a['reach_rate'])} degli ingressi "
                     f"({_n(a['monthly_volume'])} contatti/mese)",
                     "L'effetto marginale di un singolo invio è tipicamente piccolo (1-5%)"],
        })
    pick = next((c for c in cands if c["activity_key"] == activity_key), None) or \
        max(cands, key=lambda c: c["monthly_volume"], default=None)
    if pick:
        pick["recommended"] = True
    return cands


def positions(llm: LLMClient, journey: dict, scope_id: str, activity_key: str | None) -> dict:
    cands = _candidates(journey, scope_id, activity_key)
    rec = next((c for c in cands if c["recommended"]), None)
    rules_text = _rules_positions_text(journey, scope_id, rec)
    if not cands:
        return {"candidates": [], "narrative": "Il journey non contiene attività di comunicazione.",
                "source": "regole"}
    flow = [f"{a['step']}. {a['name']} ({a['type']}, {a['monthly_volume']} contatti/mese"
            f"{', ramo: ' + a['branch_label'] if a['branch_label'] else ''})" for a in journey["activities"]]
    prompt = f"""Journey «{journey['name']}», {journey['monthly_volume']} ingressi/mese, flusso:
{chr(10).join(flow)}
Scopo del control group: {scopes.get(scope_id)['name']}.
Posizioni candidate: {json.dumps([{k: c[k] for k in ('id', 'label', 'monthly_volume')} for c in cands], ensure_ascii=False)}
Scegli la posizione migliore e spiega in 3-4 frasi perché, citando volumi e rischi
(es. contaminazione, contatti già in viaggio). Se il cliente ha indicato un'attività ({activity_key}), rispettala
salvo motivi forti. Rispondi SOLO con JSON: {{"recommended_id": "...", "narrative": "..."}}"""
    try:
        r = llm.chat_json(SYSTEM, prompt)
        ids = {c["id"] for c in cands}
        rid = r.get("recommended_id")
        if rid not in ids or not r.get("narrative"):
            raise LLMUnavailable("risposta non valida")
        for c in cands:
            c["recommended"] = c["id"] == rid
        return {"candidates": cands, "narrative": str(r["narrative"])[:1500], "source": "llm"}
    except (LLMUnavailable, KeyError, TypeError, ValueError):
        return {"candidates": cands, "narrative": rules_text, "source": "regole"}


def _rules_positions_text(journey: dict, scope_id: str, rec: dict | None) -> str:
    if rec is None:
        return ""
    if scope_id == "journey_incrementality":
        return (f"Consiglio l'holdout all'ingresso di «{journey['name']}»: è l'unico punto che misura l'effetto "
                f"complessivo del journey e usa tutto il volume disponibile ({_n(journey['monthly_volume'])} "
                "ingressi/mese). Il flag viene calcolato prima dell'ingresso, quindi i contatti già in viaggio "
                "non sono toccati.")
    label = rec["label"][0].lower() + rec["label"][1:]
    return (f"Consiglio l'holdout {label}: isola il contributo di quella comunicazione. "
            f"Attenzione al volume: solo {_n(rec['monthly_volume'])} contatti/mese arrivano a quel punto, quindi "
            "verifica nel passo successivo che il test sia fattibile.")


# ----------------------------------------------------------------------------- spiegazioni

def explain_sizing(llm: LLMClient, journey: dict, scope_id: str, req: dict, sizing: dict) -> dict:
    opts = [{k: o[k] for k in ("holdout_pct", "mde_relative", "days_to_detect", "opportunity_cost")}
            for o in sizing["options"]]
    prompt = f"""Journey «{journey['name']}», scopo: {scopes.get(scope_id)['name']}.
Parametri: {json.dumps(req, ensure_ascii=False)}
Esito motore statistico: verdetto «{sizing['verdict']}», % consigliata {sizing['recommended_pct']}.
Opzioni: {json.dumps(opts)}
Spiega a un marketing manager, in 4-5 frasi e senza formule, perché questa % e qual è il compromesso
tra costo opportunità e tempo per avere una risposta. Se non è fattibile dillo chiaramente e proponi
un'alternativa concreta (più durata, scopo diverso, KPI diverso). Testo semplice, niente elenchi."""
    try:
        return {"narrative": llm.chat(SYSTEM, prompt)[:2000], "source": "llm"}
    except LLMUnavailable:
        text = sizing["explanation"]
        if sizing["verdict"] == "non fattibile" and scope_id == "touchpoint_value":
            text += (" Suggerimento: misura prima l'incrementalità dell'intero journey, che usa tutto il volume "
                     "e ha un effetto atteso più grande.")
        elif sizing["recommended_pct"]:
            text += (" Una % più alta accorcia il test ma aumenta le vendite potenzialmente perse; una % più "
                     "bassa costa meno ma richiede più tempo per una risposta affidabile.")
        return {"narrative": text, "source": "regole"}


def narrative(llm: LLMClient, cg: dict, results: dict) -> dict:
    k = [{x: kp[x] for x in ("name", "control", "treatment", "rel_lift", "ci_low", "ci_high", "p_value",
                             "significant")} for kp in results["kpis"]]
    prompt = f"""Control group «{cg['name']}» sul journey «{cg['journey_name']}» (holdout {cg['holdout_pct']:.0%},
attivo da {results['days_running']} giorni). KPI: {json.dumps(k, ensure_ascii=False)}
SRM ok: {results['srm']['ok']} (p={results['srm']['p_value']}). Ricavo incrementale stimato: {json.dumps(results['incremental_revenue'])}.
Scrivi un commento per il management in 4-6 frasi: cosa dicono i dati, quanto sono affidabili, cosa fare
adesso (continuare, fermare, estendere). Non inventare numeri. Testo semplice, niente elenchi."""
    try:
        return {"narrative": llm.chat(SYSTEM, prompt)[:2500], "source": "llm"}
    except LLMUnavailable:
        return {"narrative": _rules_narrative(cg, results), "source": "regole"}


def _rules_narrative(cg: dict, res: dict) -> str:
    p = next(x for x in res["kpis"] if x["primary"])
    if not res["srm"]["ok"]:
        return ("Attenzione: la proporzione tra gruppo di controllo e trattamento non corrisponde a quella "
                "configurata (Sample Ratio Mismatch). I risultati non sono affidabili finché non si individua la "
                "causa (filtri a monte, errori nel Decision Split, contatti rientrati).")
    lift = _fmt_pct(p["rel_lift"])
    ci = f"{_fmt_pct(p['ci_low'])} / {_fmt_pct(p['ci_high'])}"
    inc = res["incremental_revenue"]
    if p["significant"] and p["rel_lift"] > 0:
        return (f"Dopo {res['days_running']} giorni il journey genera un lift del {lift} sul {p['name'].lower()} "
                f"(intervallo di confidenza 95%: {ci}), statisticamente significativo. Il ricavo incrementale "
                f"stimato è di circa € {_n(inc['estimate'])}. Il risultato è solido: si può ridurre il gruppo "
                "di controllo per limitare il costo opportunità, mantenendo un holdout minimo per il monitoraggio "
                "continuo.")
    if p["significant"] and p["rel_lift"] < 0:
        return (f"Il gruppo di controllo performa meglio del trattamento ({lift}, IC {ci}): il journey sembra "
                "ridurre le vendite. Verificare frequenza, pressione commerciale e contenuti prima di proseguire.")
    return (f"Dopo {res['days_running']} giorni il lift osservato è {lift} (IC 95%: {ci}) ma non ancora "
            "significativo. Non è una prova che il journey non funzioni: servono più dati. Proseguire il test "
            "senza modificare la configurazione.")
