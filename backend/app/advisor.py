"""Advisor: l'LLM locale interpreta, argomenta e spiega. Numeri e vincoli restano deterministici.

Ogni funzione prova l'LLM e, se non disponibile o se la risposta non è valida, usa regole esplicite.
Le risposte LLM sono sempre validate contro le opzioni ammesse (nessun id/attività inventati).
"""
from __future__ import annotations

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


def _clean(text: str) -> str:
    """Ripulisce il testo del modello: niente id tecnici, niente frase finale troncata.

    In JSON mode Ollama vincola l'output alla grammatica JSON: se il modello scrive una virgoletta doppia (spesso
    al posto di «») la stringa si chiude lì e il testo arriva troncato a metà frase. Lo stesso succede quando
    si raggiunge max_tokens.
    """
    text = str(text).strip()
    for sid in ("journey_incrementality", "touchpoint_value"):
        text = text.replace(sid, scopes.get(sid)["name"].lower())
    if text and text[-1] not in ".!?»)":
        cut = max(text.rfind(". "), text.rfind("! "), text.rfind("? "))
        if cut > 0:  # senza una frase completa prima, meglio il testo così com'è che niente
            text = text[:cut + 1]
    return text


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
    if target is not None and any(w in q for w in ["serve", "utile", "funziona", "vale", "inutile", "togli",
                                                   "elimin", "senso", "singol", "specific", "reminder", "solo"]):
        return {"scope_id": "touchpoint_value", "activity_key": target["key"], "confidence": "media",
                "rationale": f"La domanda riguarda una comunicazione specifica («{target['name']}»): "
                             "serve un holdout immediatamente prima di quell'attività.",
                "kpi_suggestion": "conversion_rate" if "conver" in q else "revenue_per_contact"}
    return {"scope_id": "journey_incrementality", "activity_key": None, "confidence": "media",
            "rationale": ("La domanda riguarda il valore del journey nel suo complesso: holdout all'ingresso, "
                          "con KPI sulle vendite."),
            "kpi_suggestion": "conversion_rate" if "conver" in q else "revenue_per_contact"}


def interpret(llm: LLMClient, question: str, journey: dict) -> dict:
    acts = [{"key": a["key"], "name": a["name"], "type": a["type"]} for a in journey["activities"]
            if a["type"] in MESSAGING]
    # ordine di invio esplicito: senza, «la seconda email» / «l'ultima comunicazione» non vengono risolte
    def _tag(i: int) -> str:
        return " - PRIMA comunicazione" if i == 1 else " - ULTIMA comunicazione" if i == len(acts) else ""
    lines = "\n".join(f"{i}. chiave {a['key']}: «{a['name']}» ({a['type']}){_tag(i)}"
                      for i, a in enumerate(acts, 1))
    ex = next((a for a in acts if a["type"] == "SMS"), acts[-1] if acts else None)
    ex_key, ex_name = (ex["key"], ex["name"]) if ex else ("null", "")
    # qwen2.5:7b, senza regole ed esempi, classificava quasi tutto come journey_incrementality; con esempi in
    # forma abbreviata metteva la chiave dell'attività in scope_id. Esempi in JSON completo, uno per caso.
    prompt = f"""Domanda del cliente: "{question}"
Journey «{journey['name']}». Comunicazioni, in ordine di invio:
{lines}

scope_id può valere SOLO "touchpoint_value" oppure "journey_incrementality".
Caso A, touchpoint_value: la domanda riguarda UNA comunicazione precisa, cioè un canale (SMS, push, notifica,
email, newsletter), un messaggio citato per nome o per posizione («la seconda email», «l'ultima comunicazione»,
«il reminder»), o chiede se un invio serve o si può togliere. activity_key = la chiave di quella comunicazione.
Esempio per "L'SMS serve davvero?":
{{"scope_id": "touchpoint_value", "activity_key": "{ex_key}", "confidence": "alta", "rationale": "La domanda riguarda solo «{ex_name}»: serve un holdout subito prima di quell'invio.", "kpi_suggestion": "revenue_per_contact"}}
Caso B, journey_incrementality: la domanda riguarda il journey nel complesso o le sue vendite.
Esempio per "Il journey porta vendite in più?":
{{"scope_id": "journey_incrementality", "activity_key": null, "confidence": "alta", "rationale": "La domanda riguarda il valore dell'intero journey: holdout all'ingresso, misurato sulle vendite.", "kpi_suggestion": "revenue_per_contact"}}
Caso C, SOLO se la domanda parla del valore di tutto il marketing o CRM, oppure di troppe o meno comunicazioni:
quello scopo non è disponibile. Usa journey_incrementality, activity_key null, confidence "bassa" e scrivi nel
rationale che lo scopo richiesto non è ancora disponibile e che si parte dall'intero journey.
kpi_suggestion: "conversion_rate" se la domanda parla di conversioni, altrimenti "revenue_per_contact".
rationale: 1-2 frasi per un marketing manager, cita le comunicazioni per nome tra «», mai per chiave.
Rispondi SOLO con il JSON."""
    try:
        r = llm.chat_json(SYSTEM, prompt)
        keys = {a["key"] for a in acts}
        scope_id = r.get("scope_id")
        if scope_id in keys:  # errore tipico dei modelli piccoli: la chiave dell'attività al posto dello scopo
            r.setdefault("activity_key", scope_id)
            scope_id = "touchpoint_value"
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
                "rationale": _clean(r.get("rationale", ""))[:600],
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
        if first and first["next"]:
            # holdout subito dopo il primo invio: sull'attività successiva, che raggiunge tutti
            nxt = next((a for a in acts if a["key"] == first["next"][0]), None)
            if nxt and nxt["type"] != "EXIT":
                cands.append({
                    "id": f"pos-{nxt['key']}", "activity_key": nxt["key"],
                    "label": f"Dopo «{first['name']}»",
                    "description": "Tutti ricevono il primo invio; il controllo esce dal journey subito dopo.",
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
            "cons": ([f"Raggiunge solo il {_fmt_pct(a['reach_rate'])} degli ingressi "
                      f"({_n(a['monthly_volume'])} contatti/mese)"] if a["reach_rate"] < 1 else []) +
                    ["L'effetto marginale di un singolo invio è tipicamente piccolo (1-5%)"],
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
    # La scelta della posizione è una regola di design (ingresso per l'intero journey, attività indicata dal
    # cliente per il touchpoint): lasciata al modello, qwen2.5:7b sceglieva «dopo il primo invio» o un'altra
    # attività con motivazioni inventate. Il modello argomenta la scelta usando solo pro e contro forniti.
    scope = scopes.get(scope_id)
    vol = journey["monthly_volume"]

    def _desc(c: dict) -> str:
        return (f"«{c['label']}»: {c['description']} Volume: {_n(c['monthly_volume'])} contatti/mese "
                f"({_fmt_pct(c['monthly_volume'] / vol)} degli ingressi).")
    if scope_id == "journey_incrementality":
        # le alternative misurano la stessa cosa in un altro punto: ha senso dire perché non sceglierle
        alt = "".join(f"\nAlternativa scartata: {_desc(c)} Contro: {'; '.join(c['cons'])}."
                      for c in cands if c is not rec)
        ask = "perché questa posizione, cosa misura, il limite principale e perché non l'alternativa"
    else:
        # sul touchpoint le altre posizioni misurano altre comunicazioni: confrontarle portava il modello a
        # inventare motivazioni («raggiunge il 100% quindi l'effetto è troppo piccolo»)
        alt = ""
        ask = "cosa misura questa posizione, perché va bene per la domanda del cliente e il limite principale"
    prompt = f"""Journey «{journey['name']}», {_n(vol)} ingressi/mese.
Scopo del control group: {scope['name']}. {scope['description']}
Posizione consigliata (decisa dall'app, non cambiarla): {_desc(rec)}
Pro: {'; '.join(rec['pros'])}.
Contro: {'; '.join(rec['cons'])}.{alt}
Nota tecnica: il gruppo di ogni contatto è calcolato prima dell'ingresso con un hash del SubscriberKey, quindi
i contatti già in viaggio non vengono toccati e chi rientra resta nello stesso gruppo.
Scrivi 3-4 frasi per un marketing manager: {ask}. Usa solo i pro, i contro e i volumi indicati, non inventare
altri rischi. Nel testo non usare virgolette doppie.
Rispondi SOLO con JSON: {{"recommended_id": "{rec['id']}", "narrative": "..."}}"""
    try:
        r = llm.chat_json(SYSTEM, prompt)
        rid = r.get("recommended_id", rec["id"])
        if rid != rec["id"] or not r.get("narrative"):
            raise LLMUnavailable("risposta non valida")
        return {"candidates": cands, "narrative": _clean(r["narrative"])[:1500], "source": "llm"}
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

def _sizing_alternative(scope_id: str, sizing: dict) -> str | None:
    """Alternativa concreta decisa dall'app (il modello la spiega, non la sceglie)."""
    ref = next((o for o in sizing["options"] if o["holdout_pct"] == 0.20), None)
    if sizing["verdict"] == "al limite":
        if ref and ref["days_to_detect"]:
            return (f"allungare il test a circa {ref['days_to_detect']} giorni: così basta un holdout del 20% e si "
                    "perdono meno vendite")
        return "allungare il test, così da scendere sotto il 20% di holdout e perdere meno vendite"
    if sizing["verdict"] != "non fattibile":
        return None
    if scope_id == "touchpoint_value":
        return ("misurare prima l'incrementalità dell'intero journey (holdout all'ingresso), che usa tutto il "
                "volume e ha un effetto atteso più grande")
    if ref and ref["days_to_detect"]:
        return f"allungare il test a circa {ref['days_to_detect']} giorni con un holdout del 20%"
    return ("non lanciare il test: il volume è troppo basso anche in un anno. Si possono misurare solo effetti "
            "molto più grandi, oppure unire journey simili per avere più contatti")


def explain_sizing(llm: LLMClient, journey: dict, scope_id: str, req: dict, sizing: dict) -> dict:
    # qwen2.5:7b con le opzioni in JSON grezzo contraddiceva il motore (proponeva un'altra %), inventava effetti
    # sulla potenza e scriveva «% consigliata zero». Gli passiamo frasi già pronte con i soli numeri da citare.
    opts = sizing["options"]
    kpi_name = "tasso di conversione" if req.get("kpi") == "conversion_rate" else "ricavo per contatto"
    entrants = sizing.get("assumptions", {}).get("entrants_in_period")

    def _opt(o: dict) -> str:
        days = f"risposta in circa {o['days_to_detect']} giorni" if o["days_to_detect"] else \
            "nessuna risposta entro un anno"
        return (f"holdout {_fmt_pct(o['holdout_pct'])}: minimo lift rilevabile {_fmt_pct(o['mde_relative'])}, "
                f"{days}, costo opportunità circa € {_n(o['opportunity_cost'])}")

    facts = [f"Journey «{journey['name']}», scopo: {scopes.get(scope_id)['name']}.",
             f"KPI: {kpi_name}. Lift atteso: {_fmt_pct(req['expected_lift'])}. Durata prevista del test: "
             f"{req['duration_days']} giorni" + (f", {_n(entrants)} contatti attesi." if entrants else ".")]
    rec = sizing["recommended_pct"]
    if rec is not None:
        i = next(i for i, o in enumerate(opts) if o["holdout_pct"] == rec)
        facts.append(f"Verdetto del motore statistico: «{sizing['verdict']}». Holdout consigliato: "
                     f"{_fmt_pct(rec)} ({_opt(opts[i])}).")
        # confronti già orientati: lasciati al modello, invertiva la direzione («il 25% ridurrebbe il costo»)
        if i > 0:
            lo = opts[i - 1]
            slow = f"{lo['days_to_detect']} giorni" if lo["days_to_detect"] else "oltre un anno"
            facts.append(f"Un holdout più basso ({_fmt_pct(lo['holdout_pct'])}) costerebbe meno "
                         f"(€ {_n(lo['opportunity_cost'])}) ma darebbe una risposta troppo tardi ({slow}, oltre "
                         f"i {req['duration_days']} giorni previsti).")
        if i + 1 < len(opts) and opts[i + 1]["days_to_detect"]:
            hi = opts[i + 1]
            facts.append(f"Un holdout più alto ({_fmt_pct(hi['holdout_pct'])}) darebbe una risposta prima "
                         f"({hi['days_to_detect']} giorni) ma costerebbe di più (€ {_n(hi['opportunity_cost'])}).")
        if sizing["verdict"] == "al limite":
            facts.append("«Al limite» significa che il test è fattibile, ma serve un gruppo di controllo grande "
                         "(oltre il 20%), quindi molte vendite potenzialmente perse.")
    else:
        facts.append(f"Verdetto del motore statistico: «non fattibile». Nessuna % di holdout rileva il lift "
                     f"atteso nella durata prevista: anche con {_opt(opts[-1])}.")
    alt = _sizing_alternative(scope_id, sizing)
    if alt:
        facts.append(f"Alternativa proposta dall'app: {alt}.")
    prompt = "\n".join(facts) + """
Spiega a un marketing manager, in 4-5 frasi e senza formule, il verdetto e il compromesso tra costo opportunità
e tempo per avere una risposta. Inizia dal verdetto, con la stessa parola del motore («fattibile», «al limite»
o «non fattibile»). Se c'è un'alternativa, proponila con parole tue.
Regole: usa solo i numeri sopra; non proporre una % diversa da quella consigliata;
non parlare di potenza statistica, alpha o formule. Testo semplice, niente elenchi."""
    try:
        return {"narrative": _clean(llm.chat(SYSTEM, prompt, max_tokens=350))[:2000], "source": "llm"}
    except LLMUnavailable:
        text = sizing["explanation"]
        if sizing["verdict"] == "non fattibile":
            # la frase del motore suggerisce «cambia scopo (es. incrementalità dell'intero journey)» anche quando
            # lo scopo è già quello: qui l'alternativa dipende dallo scopo
            text = text.split("Neanche in un anno")[0].rstrip()
            text += f" Suggerimento: {alt}."
        elif sizing["recommended_pct"]:
            text += (" Una % più alta accorcia il test ma aumenta le vendite potenzialmente perse; una % più "
                     "bassa costa meno ma richiede più tempo per una risposta affidabile.")
        return {"narrative": text, "source": "regole"}


def narrative(llm: LLMClient, cg: dict, results: dict) -> dict:
    # Con i KPI in JSON grezzo qwen2.5:7b, per non «inventare numeri», non ne citava nessuno e il prompt lungo
    # sfiorava il timeout su CPU. Gli passiamo frasi già formattate e la raccomandazione decisa dalle regole.
    def _kpi(kp: dict) -> str:
        sig = "statisticamente significativo" if kp["significant"] else "non ancora significativo"
        return (f"{kp['name']}: lift {_fmt_pct(kp['rel_lift'])} (intervallo di confidenza 95% da "
                f"{_fmt_pct(kp['ci_low'])} a {_fmt_pct(kp['ci_high'])}), {sig}")
    kpis = results["kpis"]
    primary = next((x for x in kpis if x["primary"]), kpis[0])
    inc = results["incremental_revenue"]
    srm = results["srm"]
    srm_txt = ("La divisione tra controllo e trattamento è quella configurata (nessun Sample Ratio Mismatch)."
               if srm["ok"] else "ATTENZIONE: la divisione tra controllo e trattamento NON è quella configurata "
               "(Sample Ratio Mismatch): i risultati non sono affidabili.")
    if not srm["ok"]:
        action = "sospendere le conclusioni e cercare la causa dello squilibrio (filtri a monte, Decision Split)"
    elif primary["significant"] and primary["rel_lift"] > 0:
        action = ("il risultato è solido: si può ridurre il gruppo di controllo per limitare il costo opportunità, "
                  "mantenendo un holdout minimo per il monitoraggio continuo")
    elif primary["significant"]:
        action = "il journey sembra ridurre le vendite: rivedere frequenza, pressione commerciale e contenuti"
    else:
        action = "proseguire il test senza modificare la configurazione finché il risultato non è chiaro"
    others = "; ".join(_kpi(x) for x in kpis if x is not primary)
    prompt = f"""Control group «{cg['name']}» sul journey «{cg['journey_name']}», holdout {_fmt_pct(cg['holdout_pct'])},
attivo da {results['days_running']} giorni.
KPI principale. {_kpi(primary)}.
Altri KPI: {others or 'nessuno'}.
Ricavo incrementale stimato: circa € {_n(inc['estimate'])} (intervallo da € {_n(inc['ci_low'])} a € {_n(inc['ci_high'])}).
{srm_txt}
Raccomandazione dell'app: {action}.
Scrivi un commento per il management in 4-6 frasi: cosa dicono i dati (cita il lift del KPI principale con il
suo intervallo e il ricavo incrementale), quanto sono affidabili, cosa fare adesso seguendo la raccomandazione.
Usa solo i numeri sopra, scritti come sopra. Testo semplice, niente elenchi."""
    try:
        return {"narrative": _clean(llm.chat(SYSTEM, prompt, max_tokens=400))[:2500], "source": "llm"}
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
