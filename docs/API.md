# Contratto API — Control Group Facilitator

Base path: `/api`. Tutte le risposte sono JSON. Errori: HTTP 4xx/5xx con `{"detail": "messaggio"}`.
Percentuali e tassi sono **frazioni** (0.10 = 10%) salvo dove indicato. Valute in EUR.

## Sistema

### GET /api/health
```json
{ "version": "0.1.0", "sfmc_mode": "mock", "sfmc_error": null,
  "llm": { "base_url": "http://localhost:11434/v1", "model": "qwen2.5:7b-instruct", "enabled": true, "reachable": false } }
```

### GET /api/settings · PUT /api/settings
```json
{ "llm_enabled": true, "llm_base_url": "http://localhost:11434/v1", "llm_model": "qwen2.5:7b-instruct",
  "sfmc_mode": "mock", "sfmc_subdomain": "", "sfmc_mid": "", "sfmc_client_id": "", "sfmc_client_secret_set": false }
```
PUT accetta gli stessi campi (tutti opzionali) più `sfmc_client_secret` (write-only). Risponde con le settings aggiornate.

## Catalogo

### GET /api/scopes
```json
[{ "id": "journey_incrementality", "name": "Incrementalità del journey",
   "question": "Il journey nel suo complesso genera vendite aggiuntive?",
   "description": "...", "position_rule": "entry", "volume_need": "basso",
   "requires_activity": false, "enabled": true, "disabled_reason": null }]
```
id possibili: `journey_incrementality`, `touchpoint_value`, `universal_holdout` (enabled=false), `frequency` (enabled=false).

### GET /api/journeys
```json
[{ "id": "j-welcome", "key": "Welcome_Journey", "name": "Welcome Journey", "status": "Running",
   "entry_source": "Data Extension: Welcome_Entry", "monthly_volume": 50000, "activity_count": 9,
   "baseline": { "conversion_rate": 0.03, "avg_order_value": 85.0, "expected_lift": 0.10 },
   "active_control_groups": ["nome CG già attivo"] }]
```

### GET /api/journeys/{id}
Come sopra più:
```json
"activities": [{ "key": "ENTRY", "name": "Ingresso", "type": "ENTRY", "channel": null,
  "step": 0, "lane": 0, "reach_rate": 1.0, "monthly_volume": 50000, "next": ["EMAIL1"], "branch_label": null }]
```
`type` ∈ `ENTRY | EMAIL | SMS | PUSH | WAIT | DECISION | EXIT`. `step` = colonna (ordine), `lane` = riga (ramo).
`next` = chiavi delle attività successive (DECISION ne ha 2+; `branch_label` sull'attività figlia descrive il ramo).

## Advisor (LLM + regole)

Ogni risposta advisor ha `source`: `"llm"` se generata dal modello locale, `"regole"` se fallback deterministico (LLM spento/irraggiungibile).

### POST /api/advisor/interpret
Req `{ "question": "L'SMS di reminder serve davvero?", "journey_id": "j-welcome" }`
Res `{ "scope_id": "touchpoint_value", "activity_key": "SMS1" | null, "confidence": "alta|media|bassa", "rationale": "...", "kpi_suggestion": "revenue_per_contact|conversion_rate", "source": "llm" }`

### POST /api/advisor/positions
Req `{ "journey_id": "j-welcome", "scope_id": "touchpoint_value", "activity_key": "SMS1" | null }`
Res
```json
{ "candidates": [{ "id": "pos-entry", "activity_key": null, "label": "All'ingresso del journey",
   "description": "...", "monthly_volume": 50000, "recommended": true, "expected_lift": 0.10,
   "pros": ["..."], "cons": ["..."] }],
  "narrative": "...", "source": "regole" }
```
`activity_key = null` significa "subito dopo l'ingresso". Altrimenti il holdout è applicato immediatamente PRIMA di quell'attività.

### POST /api/stats/sizing
Req
```json
{ "monthly_volume": 50000, "baseline_conversion": 0.03, "avg_order_value": 85.0, "aov_cv": 1.0,
  "expected_lift": 0.06, "duration_days": 60, "alpha": 0.05, "power": 0.8, "kpi": "revenue_per_contact" }
```
Res
```json
{ "recommended_pct": 0.15, "feasible": true, "verdict": "fattibile|al limite|non fattibile",
  "explanation": "testo deterministico",
  "options": [{ "holdout_pct": 0.05, "control_size": 5000, "treatment_size": 95000, "mde_relative": 0.11,
     "days_to_detect": 210, "opportunity_cost": 2550.0, "detectable": false }],
  "assumptions": { "entrants_in_period": 100000, "revenue_per_contact": 2.55 } }
```
`days_to_detect` può essere `null` (non rilevabile entro 365 giorni). `opportunity_cost` = vendite attese perse nel periodo tenendo fuori il gruppo (stima con `expected_lift`).

### POST /api/advisor/explain-sizing
Req `{ "journey_id": "j-welcome", "scope_id": "journey_incrementality", "sizing": <risposta /stats/sizing>, "request": <richiesta /stats/sizing> }`
Res `{ "narrative": "...", "source": "llm|regole" }`

## Control group

### POST /api/control-groups
Req
```json
{ "name": "Welcome – holdout 15%", "journey_id": "j-welcome", "scope_id": "journey_incrementality",
  "activity_key": null, "holdout_pct": 0.15,
  "primary_kpi": "revenue_per_contact", "kpis": ["revenue_per_contact", "conversion_rate", "orders_per_contact"],
  "attribution_days": 30,
  "data_source": { "type": "sfmc_de", "config": { "sales_de_key": "Sales" } },
  "guardrails": { "srm_alpha": 0.001, "alert_negative_lift": true } }
```
KPI disponibili: `revenue_per_contact`, `conversion_rate`, `orders_per_contact`, `avg_order_value`.

Res: oggetto **ControlGroup**
```json
{ "id": "cg-ab12cd", "name": "...", "journey_id": "...", "journey_name": "...", "scope_id": "...", "activity_key": null,
  "activity_name": null, "holdout_pct": 0.15, "primary_kpi": "...", "kpis": ["..."], "attribution_days": 30,
  "data_source": {...}, "guardrails": {...}, "salt": "a1b2c3", "status": "attivo", "created_at": "ISO8601",
  "artifacts": {
    "assignment_de": { "key": "CG_Assign_ab12cd", "fields": [{ "name": "SubscriberKey", "type": "Text", "pk": true }] },
    "results_de":    { "key": "CG_Results_ab12cd", "fields": [...] },
    "assignment_sql": "SELECT ...", "results_sql": "SELECT ...",
    "journey_change": { "description": "...", "target_journey": "...", "decision_split": { ... } },
    "automation": { "name": "...", "schedule": "Ogni giorno 06:00", "steps": ["..."] }
  },
  "deploy_log": [{ "step": "Creazione DE di assegnazione", "status": "ok|simulato|errore|manuale", "detail": "..." }] }
```

`409` se sullo stesso journey c'è già un control group che si sovrapporrebbe (holdout sovrapposti si contaminano).

### GET /api/control-groups → `[ControlGroup]`
### GET /api/control-groups/{id} → `ControlGroup`
### DELETE /api/control-groups/{id} → `{ "ok": true }`

### GET /api/control-groups/{id}/results
```json
{ "as_of": "2026-11-20", "days_running": 60, "source": "SFMC DE CG_Results_ab12cd",
  "groups": { "control": { "contacts": 15000, "converters": 410, "orders": 450, "revenue": 36000.0 },
              "treatment": { "contacts": 85000, "converters": 2500, "orders": 2750, "revenue": 220000.0 } },
  "kpis": [{ "id": "revenue_per_contact", "name": "Ricavo per contatto", "unit": "€",
     "control": 2.40, "treatment": 2.59, "abs_diff": 0.19, "rel_lift": 0.079,
     "ci_low": 0.01, "ci_high": 0.15, "p_value": 0.03, "significant": true, "primary": true }],
  "srm": { "expected_pct": 0.15, "observed_pct": 0.149, "p_value": 0.62, "ok": true },
  "incremental_revenue": { "estimate": 16000.0, "ci_low": 2000.0, "ci_high": 30000.0 },
  "timeseries": [{ "date": "2026-09-22", "day": 1, "rel_lift": 0.0, "ci_low": -0.5, "ci_high": 0.5, "p_value": 0.9,
                   "control_contacts": 250, "treatment_contacts": 1400 }],
  "status": { "level": "ok|warning|error", "message": "..." } }
```
`rel_lift`, `ci_low`, `ci_high` sono lift relativi (frazioni). `timeseries` riguarda il KPI primario (cumulato).

### POST /api/control-groups/{id}/refresh → stessa risposta di /results (in live lancia le query SFMC).
### POST /api/control-groups/{id}/narrative → `{ "narrative": "...", "source": "llm|regole" }`

## Sorgenti dati

### GET /api/datasources/types
```json
[{ "type": "sfmc_de", "name": "Data Extension SFMC", "description": "...", "default": true,
   "fields": [{ "name": "sales_de_key", "label": "External Key DE vendite", "kind": "text", "default": "Sales" }] }]
```
type: `sfmc_de`, `csv`, `sql`. `kind` ∈ `text | password | textarea | file`.

### POST /api/datasources/test
Req `{ "type": "sfmc_de", "config": { ... } }` → `{ "ok": true, "message": "...", "columns": ["..."], "sample": [{...}] }`

### POST /api/datasources/upload (multipart, campo `file`) → `{ "path": "uploads/xyz.csv", "rows": 1234, "columns": ["..."] }`

### GET /api/samples/sales.csv
CSV di esempio delle vendite (solo modalità mock), utile per provare la sorgente CSV.
