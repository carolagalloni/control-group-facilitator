"""Sorgenti dei dati di ritorno (vendite).

- sfmc_de (default): le vendite stanno in una DE SFMC e gli aggregati sono calcolati IN SFMC dalla
  Query Activity dei risultati; l'app legge solo la piccola DE CG_Results.
- csv / sql: le vendite stanno fuori da SFMC. L'app legge da SFMC solo la DE di assegnazione e calcola
  gli stessi aggregati localmente (stesso motore usato dal mock), senza importare le vendite in SFMC.
Per aggiungere una sorgente (BigQuery, Snowflake, Data Cloud, API e-commerce) basta implementare load_sales().
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pandas as pd

UPLOAD_DIR = Path(os.environ.get("CGF_DATA_DIR") or Path(__file__).resolve().parent.parent / "data") / "uploads"

COLUMN_FIELDS = [
    {"name": "col_key", "label": "Colonna chiave contatto (= SubscriberKey)", "kind": "text",
     "default": "SubscriberKey"},
    {"name": "col_date", "label": "Colonna data ordine", "kind": "text", "default": "OrderDate"},
    {"name": "col_amount", "label": "Colonna importo", "kind": "text", "default": "Amount"},
    {"name": "col_order", "label": "Colonna ID ordine", "kind": "text", "default": "OrderID"},
]

TYPES = [
    {"type": "sfmc_de", "name": "Data Extension SFMC", "default": True,
     "description": ("Le vendite vengono caricate in una DE (import/SFTP/API). Gli aggregati sono calcolati "
                     "in SFMC da una Query Activity giornaliera: nessun dato personale esce da SFMC."),
     "fields": [{"name": "sales_de_key", "label": "External Key DE vendite", "kind": "text",
                 "default": "Sales"}, *COLUMN_FIELDS]},
    {"type": "csv", "name": "File CSV (export e-commerce/ERP)", "default": False,
     "description": ("Export delle vendite da un sistema esterno. L'app incrocia il file con la DE di "
                     "assegnazione letta da SFMC e calcola i KPI localmente."),
     "fields": [{"name": "path", "label": "File CSV (percorso o upload)", "kind": "file",
                 "default": "data/samples/sales_export.csv"}, *COLUMN_FIELDS]},
    {"type": "sql", "name": "Database SQL", "default": False,
     "description": ("Query diretta su un database (SQLite incluso; Postgres/BigQuery/Snowflake via "
                     "SQLAlchemy se installato). La query deve restituire ordine, contatto, data e importo."),
     "fields": [{"name": "dsn", "label": "Connessione (percorso SQLite o URL SQLAlchemy)", "kind": "text",
                 "default": "data/samples/sales.db"},
                {"name": "query", "label": "Query", "kind": "textarea",
                 "default": "SELECT OrderID, SubscriberKey, OrderDate, Amount FROM sales"},
                *COLUMN_FIELDS]},
]


def _normalize(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    mapping = {cfg.get("col_order", "OrderID") or "OrderID": "OrderID",
               cfg.get("col_key", "SubscriberKey") or "SubscriberKey": "SubscriberKey",
               cfg.get("col_date", "OrderDate") or "OrderDate": "OrderDate",
               cfg.get("col_amount", "Amount") or "Amount": "Amount"}
    # le API SFMC restituiscono i nomi colonna in minuscolo: confronto senza distinzione di maiuscole
    by_lower = {str(c).lower(): c for c in df.columns}
    missing = [c for c in mapping if c.lower() not in by_lower]
    if missing:
        raise ValueError(f"Colonne mancanti nella sorgente: {', '.join(missing)}. "
                         f"Colonne trovate: {', '.join(map(str, df.columns))}")
    return df.rename(columns={by_lower[src.lower()]: dst for src, dst in mapping.items()})


def _resolve(path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / p
    return p


def load_sales(ds: dict, sfmc=None) -> pd.DataFrame:
    t, cfg = ds["type"], ds.get("config", {})
    if t == "sfmc_de":
        return _normalize(sfmc.read_de(cfg.get("sales_de_key", "Sales")), cfg)
    if t == "csv":
        p = _resolve(cfg.get("path", ""))
        if not p.is_file():
            raise ValueError(f"File CSV non trovato: {cfg.get('path')}")
        return _normalize(pd.read_csv(p, sep=None, engine="python"), cfg)
    if t == "sql":
        dsn, query = cfg.get("dsn", ""), cfg.get("query", "")
        if not query.strip().lower().startswith("select"):
            raise ValueError("È ammessa solo una query SELECT")
        if "://" in dsn and not dsn.startswith("sqlite:///"):
            try:
                import sqlalchemy  # noqa: F401
            except ImportError as e:
                raise ValueError("Per database diversi da SQLite installa sqlalchemy e il driver") from e
            return _normalize(pd.read_sql(query, sqlalchemy.create_engine(dsn)), cfg)
        p = _resolve(dsn.replace("sqlite:///", ""))
        if not p.is_file():
            raise ValueError(f"Database SQLite non trovato: {dsn}")
        with sqlite3.connect(f"file:{p}?mode=ro", uri=True) as con:
            return _normalize(pd.read_sql_query(query, con), cfg)
    raise ValueError(f"Tipo di sorgente sconosciuto: {t}")


def test(ds: dict, sfmc) -> dict:
    df = load_sales(ds, sfmc)
    sample = df.head(5).astype(object).where(df.head(5).notna(), None).to_dict(orient="records")
    return {"ok": True, "message": f"Connessione riuscita: {len(df):,} righe lette.".replace(",", "."),
            "columns": [str(c) for c in df.columns], "sample": sample}
