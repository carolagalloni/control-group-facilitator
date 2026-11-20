"""SFMC simulato: journey, Data Extension in memoria, esecuzione delle Query Activity.

I dati di vendita sono sintetici ma contengono un effetto reale (nascosto) del journey:
la demo deve "scoprirlo" con il motore statistico, non inventarlo.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from . import engine, sfmc_sql

HISTORY_DAYS = 75  # il test simulato è partito 75 giorni fa


def _a(key, name, typ, step, lane, reach, nxt, channel=None, branch=None):
    return {"key": key, "name": name, "type": typ, "channel": channel, "step": step, "lane": lane,
            "reach_rate": reach, "next": nxt, "branch_label": branch}


JOURNEYS = [
    {
        "id": "j-welcome", "key": "Welcome_Journey", "name": "Welcome Journey", "status": "Running",
        "entry_source": "Data Extension: Welcome_Entry", "entry_de": "Welcome_Entry",
        "entry_event_key": "DEAudience-welcome-01", "monthly_volume": 150000,
        "baseline": {"conversion_rate": 0.04, "avg_order_value": 85.0, "expected_lift": 0.10},
        # effetto reale nascosto: lift relativo sulla probabilità di acquisto
        "true_lift": {"journey": 0.10, "EMAIL1": 0.06, "EMAIL2": 0.05, "SMS1": 0.02, "EMAIL3": 0.015,
                      "PUSH1": 0.01},
        "activities": [
            _a("ENTRY", "Ingresso: nuovi iscritti", "ENTRY", 0, 0, 1.0, ["EMAIL1"]),
            _a("EMAIL1", "Email di benvenuto", "EMAIL", 1, 0, 1.0, ["WAIT1"], "email"),
            _a("WAIT1", "Attendi 2 giorni", "WAIT", 2, 0, 1.0, ["DEC1"]),
            _a("DEC1", "Ha aperto l'email?", "DECISION", 3, 0, 1.0, ["EMAIL2", "EMAIL3"]),
            _a("EMAIL2", "Email offerta -10%", "EMAIL", 4, 0, 0.35, ["WAIT2"], "email", "Sì, ha aperto"),
            _a("WAIT2", "Attendi 3 giorni", "WAIT", 5, 0, 0.35, ["SMS1"]),
            _a("SMS1", "SMS reminder codice sconto", "SMS", 6, 0, 0.33, ["EXIT1"], "sms"),
            _a("EMAIL3", "Email reinvio (oggetto alternativo)", "EMAIL", 4, 1, 0.65, ["PUSH1"], "email",
               "No, non ha aperto"),
            _a("PUSH1", "Push: scopri la collezione", "PUSH", 5, 1, 0.20, ["EXIT1"], "push"),
            _a("EXIT1", "Uscita", "EXIT", 7, 0, 1.0, []),
        ],
    },
    {
        "id": "j-cart", "key": "Abandoned_Cart", "name": "Carrello abbandonato", "status": "Running",
        "entry_source": "Data Extension: Cart_Abandon_Entry", "entry_de": "Cart_Abandon_Entry",
        "entry_event_key": "DEAudience-cart-01", "monthly_volume": 40000,
        "baseline": {"conversion_rate": 0.08, "avg_order_value": 120.0, "expected_lift": 0.12},
        "true_lift": {"journey": 0.12, "EMAIL1": 0.10, "SMS1": 0.04},
        "activities": [
            _a("ENTRY", "Ingresso: carrello abbandonato", "ENTRY", 0, 0, 1.0, ["WAIT1"]),
            _a("WAIT1", "Attendi 1 ora", "WAIT", 1, 0, 1.0, ["EMAIL1"]),
            _a("EMAIL1", "Email: hai dimenticato qualcosa?", "EMAIL", 2, 0, 1.0, ["WAIT2"], "email"),
            _a("WAIT2", "Attendi 1 giorno", "WAIT", 3, 0, 1.0, ["DEC1"]),
            _a("DEC1", "Ha completato l'acquisto?", "DECISION", 4, 0, 1.0, ["EXIT1", "SMS1"]),
            _a("EXIT1", "Uscita (acquisto)", "EXIT", 5, 0, 0.30, [], branch="Sì"),
            _a("SMS1", "SMS codice sconto 5%", "SMS", 5, 1, 0.70, ["EXIT2"], "sms", "No"),
            _a("EXIT2", "Uscita", "EXIT", 6, 1, 0.70, []),
        ],
    },
    {
        "id": "j-winback", "key": "Winback_Dormant", "name": "Riattivazione clienti dormienti",
        "status": "Running", "entry_source": "Data Extension: Winback_Entry", "entry_de": "Winback_Entry",
        "entry_event_key": "DEAudience-winback-01", "monthly_volume": 4000,
        "baseline": {"conversion_rate": 0.015, "avg_order_value": 70.0, "expected_lift": 0.08},
        "true_lift": {"journey": 0.05, "EMAIL1": 0.03, "EMAIL2": 0.02},
        "activities": [
            _a("ENTRY", "Ingresso: inattivi da 12 mesi", "ENTRY", 0, 0, 1.0, ["EMAIL1"]),
            _a("EMAIL1", "Email: ci manchi", "EMAIL", 1, 0, 1.0, ["WAIT1"], "email"),
            _a("WAIT1", "Attendi 7 giorni", "WAIT", 2, 0, 1.0, ["EMAIL2"]),
            _a("EMAIL2", "Email: buono 15 €", "EMAIL", 3, 0, 1.0, ["EXIT1"], "email"),
            _a("EXIT1", "Uscita", "EXIT", 4, 0, 1.0, []),
        ],
    },
]


class MockSFMC:
    mode = "mock"

    def __init__(self, today: date | None = None):
        self.today = today or date.today()
        self.start = self.today - timedelta(days=HISTORY_DAYS)
        self.de: dict[str, pd.DataFrame] = {}
        self.queries: dict[str, dict] = {}
        self._seed_entries()
        self._seed_baseline_sales()

    # ------------------------------------------------------------------ journeys
    def list_journeys(self) -> list[dict]:
        return [self._public(j) for j in JOURNEYS]

    def get_journey(self, jid: str) -> dict | None:
        j = next((x for x in JOURNEYS if x["id"] == jid), None)
        if not j:
            return None
        out = self._public(j)
        out["activities"] = [{**a, "monthly_volume": int(round(j["monthly_volume"] * a["reach_rate"]))}
                             for a in j["activities"]]
        return out

    @staticmethod
    def _public(j: dict) -> dict:
        keys = ["id", "key", "name", "status", "entry_source", "monthly_volume", "baseline", "entry_de",
                "entry_event_key"]
        out = {k: j[k] for k in keys}
        out["activity_count"] = len(j["activities"])
        return out

    # ------------------------------------------------------------------ data extensions
    def create_de(self, key: str, fields: list[dict]) -> str:
        self.de[key] = pd.DataFrame(columns=[f["name"] for f in fields])
        return "simulato"

    def read_de(self, key: str, limit: int | None = None) -> pd.DataFrame:
        if key not in self.de:
            raise KeyError(f"Data Extension «{key}» non trovata in SFMC (mock)")
        df = self.de[key]
        return df.head(limit) if limit else df

    def de_exists(self, key: str) -> bool:
        return key in self.de

    def create_query(self, name: str, sql: str, target: str) -> str:
        self.queries[name] = {"sql": sql, "target": target}
        return "simulato"

    # ------------------------------------------------------------------ seed
    def _seed_entries(self):
        for j in JOURNEYS:
            rng = np.random.default_rng(_stable_seed(j["id"]))
            daily = j["monthly_volume"] / 30
            rows = []
            n = 0
            for d in range(HISTORY_DAYS):
                day = self.start + timedelta(days=d)
                for _ in range(rng.poisson(daily)):
                    n += 1
                    rows.append((f"{j['key'][:3].upper()}{n:07d}", day.isoformat()))
            df = pd.DataFrame(rows, columns=["SubscriberKey", "EntryDate"])
            # chi raggiunge ogni attività (dipende dai rami): campionato una volta, stabile
            for a in j["activities"]:
                if a["type"] in ("EMAIL", "SMS", "PUSH"):
                    df["Reach_" + a["key"]] = rng.random(len(df)) < a["reach_rate"]
            df["CG_Group"] = ""
            self.de[j["entry_de"]] = df

    def _seed_baseline_sales(self):
        """Vendite senza alcun control group (nessun effetto): servono a test di connessione e campioni."""
        frames = [self._gen_sales(j, None) for j in JOURNEYS]
        self.de["Sales"] = pd.concat(frames, ignore_index=True)

    def _gen_sales(self, j: dict, multiplier: np.ndarray | None, seed_extra: str = "") -> pd.DataFrame:
        """Probabilità di acquisto = p0 * multiplier. Chi è nel controllo perde l'effetto del journey
        (o del touchpoint, se lo ha raggiunto): multiplier = 1 / (1 + lift). Gli altri: 1."""
        entries = self.de[j["entry_de"]]
        rng = np.random.default_rng(_stable_seed(j["id"] + seed_extra))
        p0 = j["baseline"]["conversion_rate"]
        aov = j["baseline"]["avg_order_value"]
        n = len(entries)
        p = np.full(n, p0) if multiplier is None else p0 * multiplier
        buyers = rng.random(n) < p
        idx = np.nonzero(buyers)[0]
        rows = []
        sigma = np.sqrt(np.log(1 + 1.0 ** 2))  # CV = 1
        mu = np.log(aov) - sigma ** 2 / 2
        entry_dates = pd.to_datetime(entries["EntryDate"]).to_numpy()
        keys = entries["SubscriberKey"].to_numpy()
        oid = 0
        for i in idx:
            n_orders = 1 + rng.poisson(0.15)
            for _ in range(n_orders):
                delay = min(rng.exponential(9.0), 44)
                od = pd.Timestamp(entry_dates[i]) + pd.Timedelta(days=float(delay))
                if od.date() > self.today:
                    continue
                oid += 1
                rows.append((f"{j['key'][:3].upper()}-O{oid:07d}", keys[i], od.strftime("%Y-%m-%d %H:%M:%S"),
                             round(float(rng.lognormal(mu, sigma)), 2),
                             rng.choice(["ecommerce", "negozio", "app"], p=[0.6, 0.3, 0.1])))
        return pd.DataFrame(rows, columns=["OrderID", "SubscriberKey", "OrderDate", "Amount", "Channel"])

    # ------------------------------------------------------------------ deploy & run
    def _assign(self, cg: dict, j: dict) -> tuple[pd.DataFrame, np.ndarray]:
        """Emula la Query 1 (+ Update Contact per i touchpoint). Ritorna la DE e il moltiplicatore."""
        entries = self.de[j["entry_de"]]
        keys = entries["SubscriberKey"]
        buckets = keys.map(lambda k: sfmc_sql.bucket(k, cg["salt"]))
        groups = np.where(buckets < round(cg["holdout_pct"] * 100), "CONTROL", "TREATMENT")
        touch = cg["activity_key"]
        if touch:
            reached = entries["Reach_" + touch].to_numpy()
            lift = j["true_lift"].get(touch, 0.0)
            step = next(a["step"] for a in j["activities"] if a["key"] == touch)
            exp_dates = pd.to_datetime(entries["EntryDate"]) + pd.Timedelta(days=max(step - 1, 0))
            exposure = exp_dates.dt.strftime("%Y-%m-%d").where(reached, None)
        else:
            reached = np.ones(len(entries), dtype=bool)
            lift = j["true_lift"]["journey"]
            exposure = entries["EntryDate"]
        held_out = (groups == "CONTROL") & reached
        assign = pd.DataFrame({"SubscriberKey": keys, "CG_Group": groups, "Bucket": buckets,
                               "AssignedDate": entries["EntryDate"], "ExposureDate": exposure,
                               "JourneyKey": j["key"]})
        return assign, np.where(held_out, 1 / (1 + lift), 1.0)

    def simulate_journey(self, j: dict, cgs: list[dict]) -> None:
        """Retro-simula 75 giorni di test per tutti i control group di un journey: assegnazione,
        esposizione e vendite con l'effetto reale nascosto; poi esegue le query dei risultati."""
        mult = np.ones(len(self.de[j["entry_de"]]))
        for cg in cgs:
            assign, m = self._assign(cg, j)
            self.de[cg["artifacts"]["assignment_de"]["key"]] = assign
            mult = mult * m
        if cgs:
            self.de[j["entry_de"]]["CG_Group"] = self.de[cgs[-1]["artifacts"]["assignment_de"]["key"]]["CG_Group"]
        new_sales = self._gen_sales(j, mult, seed_extra="".join(c["salt"] for c in cgs))
        prefix = j["key"][:3].upper()
        other = self.de["Sales"][~self.de["Sales"]["SubscriberKey"].str.startswith(prefix)]
        self.de["Sales"] = pd.concat([other, new_sales], ignore_index=True)
        for cg in cgs:
            if cg["data_source"]["type"] == "sfmc_de":
                self.run_results_query(cg)

    def run_results_query(self, cg: dict, sales: pd.DataFrame | None = None) -> None:
        """Emula la Query Activity 2 per ogni giorno del periodo (in produzione: 1 snapshot/giorno)."""
        assign = self.de[cg["artifacts"]["assignment_de"]["key"]]
        sales = self.de[cg["data_source"]["config"].get("sales_de_key", "Sales")] if sales is None else sales
        snaps = engine.compute_snapshots(assign, sales, cg["attribution_days"], self.start, self.today,
                                         touchpoint=bool(cg["activity_key"]))
        self.de[cg["artifacts"]["results_de"]["key"]] = snaps

    def export_sales_csv(self, path) -> None:
        self.de["Sales"].to_csv(path, index=False)


def _stable_seed(s: str) -> int:
    import hashlib
    return int.from_bytes(hashlib.sha256(s.encode()).digest()[:4], "big")


def internal_journey(jid: str) -> dict | None:
    return next((x for x in JOURNEYS if x["id"] == jid), None)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
