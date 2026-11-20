import hashlib
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app import engine, sfmc_sql, stats


def test_bucket_matches_tsql_semantics():
    # CAST(CAST(HASHBYTES('MD5', x) AS BINARY(4)) AS BIGINT) % 100: primi 4 byte, big-endian, senza segno
    d = hashlib.md5(b"ABC123salt").digest()
    assert sfmc_sql.bucket("ABC123", "salt") == int.from_bytes(d[:4], "big") % 100


def test_assignment_is_deterministic_and_balanced():
    keys = [f"K{i}" for i in range(20000)]
    g1 = [sfmc_sql.assign_group(k, "s1", 0.2) for k in keys]
    assert g1 == [sfmc_sql.assign_group(k, "s1", 0.2) for k in keys]
    share = g1.count("CONTROL") / len(keys)
    assert 0.19 < share < 0.21
    # salt diverso => assegnazione indipendente
    g2 = [sfmc_sql.assign_group(k, "s2", 0.2) for k in keys]
    both = sum(a == b == "CONTROL" for a, b in zip(g1, g2)) / len(keys)
    assert 0.03 < both < 0.05


def test_sizing_monotonic_and_verdicts():
    big = stats.sizing(150000, 0.04, 85, 0.10, 60)
    assert big["verdict"] == "fattibile" and big["recommended_pct"] <= 0.2
    mdes = [o["mde_relative"] for o in big["options"]]
    assert mdes == sorted(mdes, reverse=True)  # più holdout => effetto minimo rilevabile più piccolo
    small = stats.sizing(4000, 0.015, 70, 0.08, 60)
    assert small["verdict"] == "non fattibile" and small["recommended_pct"] is None


def test_sizing_matches_closed_form_for_conversion():
    r = stats.sizing(30000, 0.10, 50, 0.10, 30, kpi="conversion_rate")
    o = next(x for x in r["options"] if x["holdout_pct"] == 0.5)
    z = 1.959964 + 0.841621
    expected = z * np.sqrt(0.1 * 0.9 * (1 / 15000 + 1 / 15000)) / 0.1
    assert o["mde_relative"] == pytest.approx(expected, rel=1e-3)


def test_compare_detects_known_effect_and_srm():
    c = {"contacts": 50000, "converters": 1500, "orders": 1500, "revenue": 0, "revenue_sq": 0,
         "orders_sq": 1500, "revenue_orders": 0}
    t = {**c, "contacts": 200000, "converters": 7200, "orders": 7200, "orders_sq": 7200}
    k = stats.compare(c, t, "conversion_rate")
    assert k["rel_lift"] == pytest.approx(0.2, abs=1e-6)
    assert k["significant"] and k["ci_low"] < 0.2 < k["ci_high"]
    assert stats.srm_check(50000, 200000, 0.2)["ok"]
    assert not stats.srm_check(45000, 205000, 0.2)["ok"]


def _brute(assign, sales, days, day):
    a = assign.copy()
    a["exp"] = pd.to_datetime(a["AssignedDate"])
    a = a[a["exp"] < pd.Timestamp(day) + pd.Timedelta(days=1)]
    s = sales.copy()
    s["OrderDate"] = pd.to_datetime(s["OrderDate"])
    m = s.merge(a, on="SubscriberKey")
    m = m[(m.OrderDate >= m.exp) & (m.OrderDate < m.exp + pd.Timedelta(days=days))
          & (m.OrderDate < pd.Timestamp(day) + pd.Timedelta(days=1))]
    per = m.groupby("SubscriberKey").agg(o=("OrderID", "count"), r=("Amount", "sum"))
    p = a.set_index("SubscriberKey").join(per).fillna(0)
    return p.groupby("CG_Group").agg(n=("o", "size"), o=("o", "sum"), r=("r", "sum"),
                                     rs=("r", lambda x: (x ** 2).sum()), os_=("o", lambda x: (x ** 2).sum()))


def test_vectorized_snapshots_equal_brute_force():
    rng = np.random.default_rng(1)
    start = date(2026, 1, 1)
    n = 3000
    assign = pd.DataFrame({"SubscriberKey": [f"S{i}" for i in range(n)],
                           "CG_Group": rng.choice(["CONTROL", "TREATMENT"], n),
                           "AssignedDate": [(start + timedelta(days=int(d))).isoformat()
                                            for d in rng.integers(0, 30, n)]})
    m = 900
    sales = pd.DataFrame({"OrderID": [f"O{i}" for i in range(m)],
                          "SubscriberKey": [f"S{i}" for i in rng.integers(0, n, m)],
                          "OrderDate": [(pd.Timestamp(start) + pd.Timedelta(hours=int(h))).isoformat()
                                        for h in rng.integers(-100, 50 * 24, m)],
                          "Amount": rng.lognormal(4, 1, m).round(2)})
    snaps = engine.compute_snapshots(assign, sales, 14, start, start + timedelta(days=45), False)
    for day in [start + timedelta(days=5), start + timedelta(days=20), start + timedelta(days=45)]:
        got = snaps[snaps.SnapshotDate == day.isoformat()].set_index("CG_Group")
        exp = _brute(assign, sales, 14, day)
        for g in exp.index:
            assert got.loc[g, "Contacts"] == exp.loc[g, "n"]
            assert got.loc[g, "Orders"] == exp.loc[g, "o"]
            assert got.loc[g, "Revenue"] == pytest.approx(exp.loc[g, "r"])
            assert got.loc[g, "RevenueSq"] == pytest.approx(exp.loc[g, "rs"])
            assert got.loc[g, "OrdersSq"] == exp.loc[g, "os_"]
