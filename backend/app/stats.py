"""Motore statistico deterministico: dimensionamento del holdout e analisi dei risultati.

Nessuna decisione numerica è delegata all'LLM: questo modulo è l'unica fonte dei numeri.
"""
from __future__ import annotations

import math

from scipy import stats as sps

CANDIDATE_PCTS = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]
MAX_DAYS = 365


def _it(n: float, decimals: int = 0) -> str:
    """Formattazione numerica italiana (1.234,5)."""
    s = f"{n:,.{decimals}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def _pct(x: float, decimals: int = 1) -> str:
    x = float(x)
    return _it(x * 100, decimals) + "%"


# --------------------------------------------------------------------------- sizing

def _unit_moments(kpi: str, p: float, aov: float, aov_cv: float) -> tuple[float, float]:
    """Media e varianza per contatto del KPI (il ricavo per contatto include gli zeri)."""
    if kpi == "conversion_rate":
        return p, p * (1 - p)
    mean = p * aov
    second_moment = p * ((aov_cv * aov) ** 2 + aov ** 2)
    return mean, max(second_moment - mean ** 2, 1e-12)


def sizing(monthly_volume: int, baseline_conversion: float, avg_order_value: float,
           expected_lift: float, duration_days: int, alpha: float = 0.05, power: float = 0.8,
           aov_cv: float = 1.0, kpi: str = "revenue_per_contact") -> dict:
    if monthly_volume <= 0 or not (0 < baseline_conversion < 1) or expected_lift <= 0 or duration_days <= 0:
        raise ValueError("Parametri non validi: volume, conversione (0-1), lift e durata devono essere positivi")

    z = sps.norm.ppf(1 - alpha / 2) + sps.norm.ppf(power)
    mean, var = _unit_moments(kpi, baseline_conversion, avg_order_value, aov_cv)
    var_rel = var / mean ** 2
    daily = monthly_volume / 30.0
    n_total = daily * duration_days
    rpc = baseline_conversion * avg_order_value

    options = []
    for h in CANDIDATE_PCTS:
        nc, nt = n_total * h, n_total * (1 - h)
        mde_rel = z * math.sqrt(var_rel * (1 / nc + 1 / nt))
        n_needed = z ** 2 * var_rel * (1 / h + 1 / (1 - h)) / expected_lift ** 2
        days = math.ceil(n_needed / daily)
        options.append({
            "holdout_pct": h,
            "control_size": int(round(nc)),
            "treatment_size": int(round(nt)),
            "mde_relative": round(mde_rel, 4),
            "days_to_detect": days if days <= MAX_DAYS else None,
            "opportunity_cost": round(nc * rpc * expected_lift, 2),
            "detectable": bool(mde_rel <= expected_lift),
        })

    detectable = [o for o in options if o["detectable"]]
    rec = detectable[0]["holdout_pct"] if detectable else None
    kpi_name = "tasso di conversione" if kpi == "conversion_rate" else "ricavo per contatto"

    if rec is not None:
        o = detectable[0]
        verdict = "fattibile" if rec <= 0.20 else "al limite"
        explanation = (
            f"Con {_it(n_total)} contatti attesi in {duration_days} giorni, un holdout del {_pct(rec, 0)} "
            f"permette di rilevare un lift del {_pct(o['mde_relative'])} sul {kpi_name} "
            f"(lift atteso {_pct(expected_lift)}, alpha {alpha}, potenza {_pct(power, 0)}). "
            f"Costo opportunità stimato: € {_it(o['opportunity_cost'])}."
        )
        if verdict == "al limite":
            explanation += (" Serve un gruppo di controllo grande: valuta di allungare il test "
                            "per scendere sotto il 20%.")
    else:
        verdict = "non fattibile"
        ref = next(x for x in options if x["holdout_pct"] == 0.20)
        best = options[-1]
        explanation = (
            f"Con {_it(n_total)} contatti in {duration_days} giorni nemmeno un holdout del 50% rileva un lift "
            f"del {_pct(expected_lift)} sul {kpi_name} (minimo rilevabile al 50%: {_pct(best['mde_relative'])}). "
        )
        if ref["days_to_detect"]:
            explanation += f"Con holdout al 20% servirebbero circa {ref['days_to_detect']} giorni."
        else:
            explanation += ("Neanche in un anno con holdout al 20%: cambia scopo (es. incrementalità "
                            "dell'intero journey) o accetta di misurare solo effetti più grandi.")

    return {
        "recommended_pct": rec,
        "feasible": rec is not None,
        "verdict": verdict,
        "explanation": explanation,
        "options": options,
        "assumptions": {
            "entrants_in_period": int(round(n_total)),
            "revenue_per_contact": round(rpc, 4),
            "kpi_mean": round(mean, 6),
            "kpi_sd": round(math.sqrt(var), 6),
            "z_alpha_plus_z_beta": round(z, 4),
        },
    }


# --------------------------------------------------------------------------- analisi risultati

KPI_META = {
    "revenue_per_contact": ("Ricavo per contatto", "€"),
    "conversion_rate": ("Tasso di conversione", "%"),
    "orders_per_contact": ("Ordini per contatto", "n"),
    "avg_order_value": ("Scontrino medio", "€"),
}


def _group_moments(g: dict, kpi: str) -> tuple[float, float, float]:
    """(media, varianza dello stimatore della media, n) per un gruppo a partire dagli aggregati."""
    n = max(g["contacts"], 1)
    if kpi == "conversion_rate":
        m = g["converters"] / n
        return m, m * (1 - m) / n, n
    if kpi == "revenue_per_contact":
        m = g["revenue"] / n
        v = max(g["revenue_sq"] / n - m ** 2, 0.0)
        return m, v / n, n
    if kpi == "orders_per_contact":
        m = g["orders"] / n
        v = max(g["orders_sq"] / n - m ** 2, 0.0)
        return m, v / n, n
    if kpi == "avg_order_value":
        # Stimatore a rapporto R/O, varianza col metodo delta su medie per contatto.
        if g["orders"] == 0:
            return 0.0, float("inf"), n
        mr, mo = g["revenue"] / n, g["orders"] / n
        vr = max(g["revenue_sq"] / n - mr ** 2, 0.0)
        vo = max(g["orders_sq"] / n - mo ** 2, 0.0)
        cov = g["revenue_orders"] / n - mr * mo
        ratio = mr / mo
        var_ratio = (vr - 2 * ratio * cov + ratio ** 2 * vo) / (mo ** 2 * n)
        return ratio, max(var_ratio, 0.0), n
    raise ValueError(f"KPI sconosciuto: {kpi}")


def compare(control: dict, treatment: dict, kpi: str, alpha: float = 0.05) -> dict:
    mc, vc, _ = _group_moments(control, kpi)
    mt, vt, _ = _group_moments(treatment, kpi)
    diff = mt - mc
    se_diff = math.sqrt(vc + vt) if math.isfinite(vc + vt) else float("inf")
    zcrit = sps.norm.ppf(1 - alpha / 2)
    if se_diff > 0 and math.isfinite(se_diff):
        p_value = float(2 * (1 - sps.norm.cdf(abs(diff) / se_diff)))
    else:
        p_value = 1.0
    if mc > 0 and mt > 0 and math.isfinite(vc + vt):
        rel = mt / mc - 1
        se_log = math.sqrt(vt / mt ** 2 + vc / mc ** 2)
        lo = math.exp(math.log(mt / mc) - zcrit * se_log) - 1
        hi = math.exp(math.log(mt / mc) + zcrit * se_log) - 1
    else:
        rel, lo, hi = 0.0, -1.0, 1.0
    name, unit = KPI_META[kpi]
    return {
        "id": kpi, "name": name, "unit": unit,
        "control": round(mc, 6), "treatment": round(mt, 6), "abs_diff": round(diff, 6),
        "rel_lift": round(rel, 5), "ci_low": round(lo, 5), "ci_high": round(hi, 5),
        "p_value": round(p_value, 5), "significant": bool(p_value < alpha),
        "_se_diff": se_diff,
    }


def srm_check(n_control: int, n_treatment: int, expected_pct: float, alpha: float = 0.001) -> dict:
    total = n_control + n_treatment
    if total == 0:
        return {"expected_pct": expected_pct, "observed_pct": 0.0, "p_value": 1.0, "ok": True}
    exp_c, exp_t = total * expected_pct, total * (1 - expected_pct)
    chi2 = (n_control - exp_c) ** 2 / exp_c + (n_treatment - exp_t) ** 2 / exp_t
    p = float(1 - sps.chi2.cdf(chi2, df=1))
    return {"expected_pct": expected_pct, "observed_pct": round(n_control / total, 5),
            "p_value": round(p, 6), "ok": bool(p >= alpha)}
