SCOPES = [
    {
        "id": "journey_incrementality",
        "name": "Incrementalità del journey",
        "question": "Il journey nel suo complesso genera vendite aggiuntive?",
        "description": ("Una quota di contatti entra nel journey ma non riceve nessuna comunicazione. "
                        "Misura il valore reale dell'intero journey: è la scelta giusta nella maggior parte dei casi."),
        "position_rule": "entry", "volume_need": "basso", "requires_activity": False,
        "enabled": True, "disabled_reason": None,
    },
    {
        "id": "touchpoint_value",
        "name": "Valore di un singolo touchpoint",
        "question": "Quella specifica comunicazione (es. l'SMS) serve davvero?",
        "description": ("Il gruppo di controllo salta solo un'attività del journey. Risponde a domande "
                        "puntuali, ma l'effetto marginale di un singolo invio è piccolo: servono volumi alti."),
        "position_rule": "before_activity", "volume_need": "alto", "requires_activity": True,
        "enabled": True, "disabled_reason": None,
    },
    {
        "id": "universal_holdout",
        "name": "Holdout universale",
        "question": "Quanto vale tutto il marketing CRM, sommato?",
        "description": ("Un gruppo di clienti escluso da tutte le comunicazioni della Business Unit per un "
                        "periodo lungo. Misura l'effetto cumulato, ma richiede governance su tutti i journey."),
        "position_rule": "global", "volume_need": "basso (ma serve tempo)", "requires_activity": False,
        "enabled": False,
        "disabled_reason": "Richiede una DE di esclusione applicata a tutti i journey e invii della BU.",
    },
    {
        "id": "frequency",
        "name": "Effetto della frequenza",
        "question": "Comunicando meno, perdiamo vendite?",
        "description": "Un ramo 'light' salta alcune comunicazioni non essenziali per misurare saturazione e fatica.",
        "position_rule": "branch", "volume_need": "molto alto", "requires_activity": False,
        "enabled": False,
        "disabled_reason": "Effetti molto piccoli: misurabili solo con volumi elevati e test lunghi.",
    },
]

ENABLED = {s["id"] for s in SCOPES if s["enabled"]}


def get(scope_id: str) -> dict | None:
    return next((s for s in SCOPES if s["id"] == scope_id), None)
