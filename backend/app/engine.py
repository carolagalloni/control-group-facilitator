"""Calcolo degli snapshot giornalieri per gruppo: equivalente Python della Query Activity 2.

Usato (a) dal mock SFMC per "eseguire" la query e popolare la DE dei risultati e
(b) dalle sorgenti dati esterne (CSV, SQL), dove i dati di vendita non stanno in SFMC.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

SNAPSHOT_COLS = ["SnapshotDate", "CG_Group", "Contacts", "Converters", "Orders", "Revenue",
                 "RevenueSq", "OrdersSq", "RevenueOrders"]


def compute_snapshots(assign: pd.DataFrame, sales: pd.DataFrame, attribution_days: int,
                      start: date, end: date, touchpoint: bool) -> pd.DataFrame:
    """assign: SubscriberKey, CG_Group, AssignedDate, ExposureDate
    sales: OrderID, SubscriberKey, OrderDate, Amount
    Ritorna una riga per (giorno, gruppo) con gli aggregati cumulati a quel giorno."""
    a = assign.copy()
    exp_col = "ExposureDate" if touchpoint else "AssignedDate"
    a["exp"] = pd.to_datetime(a[exp_col], errors="coerce")
    a = a.dropna(subset=["exp"])[["SubscriberKey", "CG_Group", "exp"]]

    s = sales[["OrderID", "SubscriberKey", "OrderDate", "Amount"]].copy()
    s["OrderDate"] = pd.to_datetime(s["OrderDate"], errors="coerce")
    s["Amount"] = pd.to_numeric(s["Amount"], errors="coerce").fillna(0.0)
    s["SubscriberKey"] = s["SubscriberKey"].astype(str)
    a["SubscriberKey"] = a["SubscriberKey"].astype(str)

    m = s.merge(a, on="SubscriberKey", how="inner")
    window = pd.Timedelta(days=attribution_days)
    m = m[(m["OrderDate"] >= m["exp"]) & (m["OrderDate"] < m["exp"] + window)]

    # Vettoriale: ogni ordine è un evento che aggiorna gli aggregati del suo contatto.
    # Le somme dei quadrati si aggiornano con la differenza (nuovo^2 - vecchio^2), poi cumsum per giorno.
    m = m.sort_values(["SubscriberKey", "OrderDate", "OrderID"])
    g = m.groupby("SubscriberKey", sort=False)
    rev_new = g["Amount"].cumsum()
    ord_new = g.cumcount() + 1
    rev_old, ord_old = rev_new - m["Amount"], ord_new - 1
    ev = pd.DataFrame({
        "day": m["OrderDate"].dt.normalize(), "CG_Group": m["CG_Group"],
        "Converters": (ord_old == 0).astype(int), "Orders": 1, "Revenue": m["Amount"],
        "RevenueSq": rev_new ** 2 - rev_old ** 2, "OrdersSq": ord_new ** 2 - ord_old ** 2,
        "RevenueOrders": rev_new * ord_new - rev_old * ord_old,
    })
    days = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="D")
    groups = sorted(a["CG_Group"].unique())
    idx = pd.MultiIndex.from_product([days, groups], names=["day", "CG_Group"])
    contacts = a.assign(day=a["exp"].dt.normalize()).groupby(["day", "CG_Group"]).size().rename("Contacts")
    metrics = ev.groupby(["day", "CG_Group"]).sum()
    # eventi precedenti a start vanno sommati nel primo giorno
    first = pd.Timestamp(start)
    contacts.index = contacts.index.set_levels(contacts.index.levels[0].where(
        contacts.index.levels[0] >= first, first), level=0, verify_integrity=False)
    contacts = contacts.groupby(level=[0, 1]).sum()
    if len(metrics):
        metrics.index = metrics.index.set_levels(metrics.index.levels[0].where(
            metrics.index.levels[0] >= first, first), level=0, verify_integrity=False)
        metrics = metrics.groupby(level=[0, 1]).sum()
    daily = pd.concat([contacts, metrics], axis=1).reindex(idx).fillna(0.0)
    cum = daily.groupby(level="CG_Group").cumsum().reset_index()
    cum = cum[cum["Contacts"] > 0]
    cum["SnapshotDate"] = cum["day"].dt.date.map(lambda d: d.isoformat())
    return cum[SNAPSHOT_COLS].reset_index(drop=True)
