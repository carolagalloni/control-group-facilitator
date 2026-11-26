"""Generazione degli artefatti SFMC (DE, SQL Query Activity, modifica journey) e
emulazione Python dell'assegnazione, identica alla SQL, per il mock e per le verifiche.
"""
from __future__ import annotations

import hashlib

ASSIGN_FIELDS = [
    {"name": "SubscriberKey", "type": "Text", "length": 254, "pk": True},
    {"name": "CG_Group", "type": "Text", "length": 10, "pk": False},
    {"name": "Bucket", "type": "Number", "pk": False},
    {"name": "AssignedDate", "type": "Date", "pk": False},
    {"name": "ExposureDate", "type": "Date", "pk": False, "nullable": True},
    {"name": "JourneyKey", "type": "Text", "length": 100, "pk": False},
]

RESULTS_FIELDS = [
    {"name": "SnapshotDate", "type": "Date", "pk": True},
    {"name": "CG_Group", "type": "Text", "length": 10, "pk": True},
    {"name": "Contacts", "type": "Number", "pk": False},
    {"name": "Converters", "type": "Number", "pk": False},
    {"name": "Orders", "type": "Number", "pk": False},
    {"name": "Revenue", "type": "Decimal", "precision": 18, "scale": 2, "pk": False},
    {"name": "RevenueSq", "type": "Decimal", "precision": 18, "scale": 2, "pk": False},
    {"name": "OrdersSq", "type": "Number", "pk": False},
    {"name": "RevenueOrders", "type": "Decimal", "precision": 18, "scale": 2, "pk": False},
]

SALES_FIELDS = [
    {"name": "OrderID", "type": "Text", "length": 50, "pk": True},
    {"name": "SubscriberKey", "type": "Text", "length": 254, "pk": False},
    {"name": "OrderDate", "type": "Date", "pk": False},
    {"name": "Amount", "type": "Decimal", "precision": 18, "scale": 2, "pk": False},
    {"name": "Channel", "type": "Text", "length": 30, "pk": False},
]


def bucket(subscriber_key: str, salt: str) -> int:
    """Replica esatta di:
    CAST(CAST(HASHBYTES('MD5', CAST(CONCAT(SubscriberKey, salt) AS VARCHAR(300))) AS BINARY(4)) AS BIGINT) % 100
    (VARCHAR → byte ASCII/codepage; BINARY(4) tiene i 4 byte più a sinistra; BIGINT li legge big-endian
    senza segno, quindi niente ABS e niente overflow).
    """
    digest = hashlib.md5((subscriber_key + salt).encode("latin-1", errors="replace")).digest()
    return int.from_bytes(digest[:4], "big", signed=False) % 100


def assign_group(subscriber_key: str, salt: str, holdout_pct: float) -> str:
    return "CONTROL" if bucket(subscriber_key, salt) < round(holdout_pct * 100) else "TREATMENT"


def _bucket_expr(col: str, salt: str) -> str:
    return (f"CAST(CAST(HASHBYTES('MD5', CAST(CONCAT({col}, '{salt}') AS VARCHAR(300))) "
            f"AS BINARY(4)) AS BIGINT) % 100")


SALES_COLUMNS = {"col_key": "SubscriberKey", "col_date": "OrderDate", "col_amount": "Amount", "col_order": "OrderID"}


def sales_columns(cfg: dict | None) -> dict:
    """Colonne della DE vendite come le ha la BU (mappate sui nomi standard del motore)."""
    cfg = cfg or {}
    return {k: (str(cfg.get(k) or "").strip() or v) for k, v in SALES_COLUMNS.items()}


def assignment_sql(entry_de: str, assign_de: str, salt: str, holdout_pct: float, journey_key: str,
                   touchpoint: bool, contact_field: str = "SubscriberKey") -> str:
    threshold = round(holdout_pct * 100)
    exposure = "NULL" if touchpoint else "GETDATE()"
    ck = f"e.[{contact_field}]"
    return f"""/* Query Activity 1 — Assegnazione deterministica al gruppo di controllo
   Target DE: {assign_de}   Azione: Update (PK SubscriberKey)
   Esegue PRIMA dell'ingresso nel journey. Hash MD5 + salt '{salt}': stesso contatto => stesso gruppo,
   riproducibile e verificabile. Soglia: bucket < {threshold}  =>  CONTROL ({holdout_pct:.0%}).
   Chiave del contatto nella DE di ingresso: {contact_field}. */
SELECT
    {ck}                                       AS SubscriberKey,
    CASE WHEN {_bucket_expr(ck, salt)} < {threshold}
         THEN 'CONTROL' ELSE 'TREATMENT' END                AS CG_Group,
    {_bucket_expr(ck, salt)}                 AS Bucket,
    GETDATE()                                               AS AssignedDate,
    {exposure}                                              AS ExposureDate,
    '{journey_key}'                                         AS JourneyKey
FROM [{entry_de}] e
LEFT JOIN [{assign_de}] a ON a.SubscriberKey = {ck}
WHERE a.SubscriberKey IS NULL   /* chi è già assegnato non cambia gruppo */

/* Query Activity 1b — Propaga il flag sulla DE di ingresso (Target: {entry_de}, Azione: Update)
SELECT {ck}, a.CG_Group
FROM [{entry_de}] e INNER JOIN [{assign_de}] a ON a.SubscriberKey = {ck} */"""


def results_sql(assign_de: str, sales_de: str, results_de: str, attribution_days: int,
                touchpoint: bool, columns: dict | None = None) -> str:
    c = sales_columns(columns)
    exposure_filter = "WHERE a.ExposureDate IS NOT NULL" if touchpoint else ""
    exposure_col = "a.ExposureDate" if touchpoint else "a.AssignedDate"
    return f"""/* Query Activity 2 — Snapshot giornaliero dei risultati
   Target DE: {results_de}   Azione: Update (PK SnapshotDate + CG_Group)
   Finestra di attribuzione: {attribution_days} giorni dall'esposizione. Le colonne *Sq e RevenueOrders
   servono al motore statistico per varianze e intervalli di confidenza senza leggere i dati riga per riga.
   DE vendite {sales_de}: contatto = {c['col_key']}, data = {c['col_date']}, importo = {c['col_amount']},
   ordine = {c['col_order']}. */
SELECT
    CAST(GETDATE() AS DATE)                    AS SnapshotDate,
    c.CG_Group,
    COUNT(*)                                   AS Contacts,
    SUM(CASE WHEN c.Orders > 0 THEN 1 ELSE 0 END) AS Converters,
    SUM(c.Orders)                              AS Orders,
    SUM(c.Revenue)                             AS Revenue,
    SUM(c.Revenue * c.Revenue)                 AS RevenueSq,
    SUM(c.Orders * c.Orders)                   AS OrdersSq,
    SUM(c.Revenue * c.Orders)                  AS RevenueOrders
FROM (
    SELECT a.SubscriberKey, a.CG_Group,
           COUNT(s.[{c['col_order']}])          AS Orders,
           ISNULL(SUM(s.[{c['col_amount']}]), 0)  AS Revenue
    FROM [{assign_de}] a
    LEFT JOIN [{sales_de}] s
           ON s.[{c['col_key']}] = a.SubscriberKey
          AND s.[{c['col_date']}] >= {exposure_col}
          AND s.[{c['col_date']}] <  DATEADD(DAY, {attribution_days}, {exposure_col})
    {exposure_filter}
    GROUP BY a.SubscriberKey, a.CG_Group
) c
GROUP BY c.CG_Group"""


def journey_change(journey: dict, activity: dict | None, assign_de: str, entry_event_key: str,
                   exit_control: bool = False) -> dict:
    """Descrive (e prepara in JSON) la modifica al journey: Decision Split sul flag CG_Group."""
    field_ref = f'Event.{entry_event_key}."CG_Group"'
    criteria = (
        '<FilterDefinition><ConditionSet Operator="AND" ConditionSetName="Individual Filter Grouping">'
        f'<Condition Key="{field_ref}" Operator="Equal" UiMetaData="{{}}"><Value><![CDATA[CONTROL]]></Value>'
        '</Condition></ConditionSet></FilterDefinition>'
    )
    position = "subito dopo l'ingresso" if activity is None else f"immediatamente prima di «{activity['name']}»"
    control_path = ("verso un'uscita: il gruppo di controllo non riceve nessuna comunicazione del journey"
                    if activity is None else
                    "verso un'uscita: il gruppo di controllo non riceve le comunicazioni successive"
                    if exit_control else
                    f"che salta «{activity['name']}» e si ricongiunge al flusso successivo")
    steps = [
        f"Creare una nuova versione di «{journey['name']}» (la versione attiva non viene toccata; "
        "i contatti già in viaggio restano sulla versione corrente).",
        f"Inserire un Decision Split {position}: ramo «Controllo» se CG_Group = CONTROL, "
        f"altrimenti ramo «Trattamento».",
        f"Ramo Controllo: {control_path}.",
    ]
    if activity is not None:
        steps.append(
            f"In entrambi i rami aggiungere un'attività Update Contact che scrive ExposureDate = oggi in "
            f"{assign_de}: serve a sapere chi è arrivato davvero a quel punto (i contatti di controllo non "
            "generano invii, quindi non sono tracciabili nelle Data View).")
    return {
        "description": f"Decision Split {position} sul campo CG_Group.",
        "target_journey": journey["name"],
        "steps": steps,
        "decision_split": {
            "key": "CG_SPLIT",
            "name": "Control group split",
            "type": "MULTICRITERIADECISION",
            "outcomes": [
                {"key": "cg_control", "arguments": {"criteriaDescription": "Controllo"},
                 "metaData": {"label": "Controllo"}},
                {"key": "cg_treatment", "arguments": {}, "metaData": {"label": "Trattamento",
                                                                     "isDefaultPath": True}},
            ],
            "configurationArguments": {"criteria": {"cg_control": criteria}},
        },
    }
