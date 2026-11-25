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
        "folder": "Onboarding", "last_modified": "2026-10-02",
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
        "folder": "Carrello e conversione", "last_modified": "2026-11-10",
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
        "folder": "Riattivazione", "last_modified": "2026-09-18",
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

# ----------------------------------------------------------------------------- catalogo sintetico
# Una BU reale ha migliaia di journey: il mock ne genera ~2.400 (deterministici) oltre ai tre "curati".
# Sono completi (attività, baseline, effetto nascosto) e si possono usare nel wizard; le loro DE di
# ingresso vengono create solo quando servono, per non rallentare l'avvio.

SYNTH_COUNT = 2400
FOLDERS = {
    "Acquisizione": ["Lead nurturing", "Prima registrazione", "Download app", "Iscrizione newsletter",
                     "Lead da evento", "Referral amico"],
    "Onboarding": ["Benvenuto", "Completa il profilo", "Primo acquisto", "Attiva la carta fedeltà",
                   "Scopri l'app", "Preferenze di contatto"],
    "Carrello e conversione": ["Carrello abbandonato", "Navigazione abbandonata", "Prodotto tornato disponibile",
                               "Calo di prezzo", "Wishlist", "Checkout interrotto"],
    "Cross-sell e upsell": ["Prodotti complementari", "Upgrade premium", "Accessori post-acquisto",
                            "Bundle stagionale", "Garanzia estesa", "Riordino consumabili"],
    "Retention": ["Post-acquisto", "Recensione prodotto", "Compleanno", "Anniversario cliente",
                  "Rinnovo abbonamento", "Promo stagionale"],
    "Riattivazione": ["Clienti dormienti 6 mesi", "Clienti dormienti 12 mesi", "Win-back abbonati",
                      "Carta fedeltà inattiva", "App disinstallata", "Ultima chiamata"],
    "Loyalty": ["Cambio livello", "Punti in scadenza", "Premio disponibile", "Doppi punti",
                "Evento esclusivo", "Membri VIP"],
    "Transazionale": ["Conferma ordine", "Spedizione", "Reso e rimborso", "Promemoria appuntamento",
                      "Scadenza pagamento", "Cambio password"],
}
SEGMENTS = ["Tutti", "Nuovi clienti", "Clienti ricorrenti", "Alto valore", "Giovani", "Famiglie",
            "Business", "Studenti"]
MARKETS = ["IT", "ES", "FR", "DE", "CH"]
STATUSES = [("Running", 0.55), ("Paused", 0.08), ("Draft", 0.17), ("Stopped", 0.15), ("Finishing", 0.05)]
_CH_TYPE = {"email": "EMAIL", "sms": "SMS", "push": "PUSH"}
_CH_LABEL = {"email": "Email", "sms": "SMS", "push": "Push"}


def _synthetic(i: int) -> dict:
    rng = np.random.default_rng(10_000 + i)
    folders = list(FOLDERS)
    folder = folders[i % len(folders)]
    rest = i // len(folders)
    topic = FOLDERS[folder][rest % 6]
    rest //= 6
    segment = SEGMENTS[rest % len(SEGMENTS)]
    rest //= len(SEGMENTS)
    market = MARKETS[rest % len(MARKETS)]
    version = rest // len(MARKETS) + 1
    name = f"{topic} – {segment} – {market}" + (f" v{version}" if version > 1 else "")
    key = f"{folder[:3].upper()}_{i:05d}"
    status = rng.choice([s for s, _ in STATUSES], p=[p for _, p in STATUSES])
    volume = int(round(float(np.exp(rng.uniform(np.log(600), np.log(90_000)))), -2)) or 100
    p0 = float(rng.uniform(0.01, 0.09))
    j_lift = float(rng.uniform(0.02, 0.12))
    n_msg = int(rng.integers(2, 6))
    acts = [_a("ENTRY", f"Ingresso: {topic.lower()}", "ENTRY", 0, 0, 1.0, [])]
    true_lift = {"journey": j_lift}
    reach, step = 1.0, 1
    for k in range(1, n_msg + 1):
        if k > 1:
            wk = f"WAIT{k - 1}"
            acts[-1]["next"] = [wk]
            days = int(rng.choice([1, 2, 3, 5, 7]))
            acts.append(_a(wk, f"Attendi {days} giorn{'o' if days == 1 else 'i'}", "WAIT", step, 0, reach, []))
            step += 1
        ch = str(rng.choice(["email", "sms", "push"], p=[0.65, 0.2, 0.15]))
        mk = f"{_CH_TYPE[ch]}{k}"
        acts[-1]["next"] = [mk]
        acts.append(_a(mk, f"{_CH_LABEL[ch]} {k}: {topic.lower()}", _CH_TYPE[ch], step, 0, round(reach, 2), [], ch))
        true_lift[mk] = round(j_lift * (0.6 if k == 1 else 0.3 / k), 4)
        step += 1
        reach *= float(rng.uniform(0.75, 1.0))
    acts[-1]["next"] = ["EXIT1"]
    acts.append(_a("EXIT1", "Uscita", "EXIT", step, 0, 1.0, []))
    modified = date(2024, 1, 1) + timedelta(days=int(rng.integers(0, 690)))
    return {
        "id": f"j-{i:05d}", "key": key, "name": name, "status": str(status), "folder": folder,
        "last_modified": modified.isoformat(),
        "entry_source": f"Data Extension: {key}_Entry", "entry_de": f"{key}_Entry",
        "entry_event_key": f"DEAudience-{key.lower()}", "monthly_volume": volume, "sk_prefix": f"S{i:05d}-",
        "baseline": {"conversion_rate": round(p0, 4), "avg_order_value": round(float(rng.uniform(35, 180)), 2),
                     "expected_lift": round(float(rng.uniform(0.05, 0.12)), 3)},
        "true_lift": true_lift, "activities": acts,
    }


_CATALOG: list[dict] | None = None


def catalog() -> list[dict]:
    """I tre journey curati + quelli sintetici. Costruito una volta, poi in cache."""
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = [*JOURNEYS, *(_synthetic(i) for i in range(1, SYNTH_COUNT + 1))]
    return _CATALOG


def _prefix(j: dict) -> str:
    return j.get("sk_prefix") or j["key"][:3].upper()


def _channels(j: dict) -> list[str]:
    return sorted({a["channel"] for a in j["activities"] if a.get("channel")})


def search(items: list[dict], q: str = "", status: str = "", folder: str = "", channel: str = "",
           sort: str = "name", page: int = 1, page_size: int = 25) -> dict:
    """Ricerca, filtri, ordinamento e paginazione su una lista di journey (vista pubblica)."""
    words = [w for w in q.lower().split() if w]

    def match(j, skip=""):
        text = f"{j['name']} {j['key']} {j.get('folder', '')}".lower()
        return (all(w in text for w in words)
                and (skip == "status" or not status or j["status"] == status)
                and (skip == "folder" or not folder or j.get("folder") == folder)
                and (not channel or channel in j.get("channels", [])))

    hits = [j for j in items if match(j)]
    keyf = {"name": lambda j: j["name"].lower(), "volume": lambda j: -j["monthly_volume"],
            "modified": lambda j: j.get("last_modified") or ""}.get(sort, lambda j: j["name"].lower())
    hits.sort(key=keyf, reverse=sort == "modified")
    if words:  # prima chi ha tutte le parole nel nome, poi chi le ha solo in chiave/cartella
        hits.sort(key=lambda j: not all(w in j["name"].lower() for w in words))
    facets = {}
    for f in ("status", "folder"):
        counts: dict[str, int] = {}
        for j in items:
            if match(j, skip=f) and j.get(f):
                counts[j[f]] = counts.get(j[f], 0) + 1
        facets[f] = dict(sorted(counts.items(), key=lambda kv: -kv[1]))
    page_size = max(1, min(page_size, 100))
    page = max(1, page)
    return {"items": hits[(page - 1) * page_size: page * page_size], "total": len(hits), "page": page,
            "page_size": page_size, "facets": facets}


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
        return [self._public(j) for j in catalog()]

    def search_journeys(self, **kw) -> dict:
        return search([self._public(j) for j in catalog()], **kw)

    def get_journey(self, jid: str) -> dict | None:
        j = internal_journey(jid)
        if not j:
            return None
        out = self._public(j)
        out["activities"] = [{**a, "monthly_volume": int(round(j["monthly_volume"] * a["reach_rate"]))}
                             for a in j["activities"]]
        return out

    @staticmethod
    def _public(j: dict) -> dict:
        keys = ["id", "key", "name", "status", "entry_source", "monthly_volume", "baseline", "entry_de",
                "entry_event_key", "folder", "last_modified"]
        out = {k: j[k] for k in keys}
        out["activity_count"] = len(j["activities"])
        out["channels"] = _channels(j)
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
            self._ensure_entries(j)

    def _ensure_entries(self, j: dict) -> None:
        if j["entry_de"] in self.de:
            return
        rng = np.random.default_rng(_stable_seed(j["id"]))
        daily = j["monthly_volume"] / 30
        counts = rng.poisson(daily, HISTORY_DAYS)
        days = np.repeat([(self.start + timedelta(days=d)).isoformat() for d in range(HISTORY_DAYS)], counts)
        pre = _prefix(j)
        df = pd.DataFrame({"SubscriberKey": [f"{pre}{n:07d}" for n in range(1, len(days) + 1)], "EntryDate": days})
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
        self._ensure_entries(j)
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
                rows.append((f"{_prefix(j)}-O{oid:07d}", keys[i], od.strftime("%Y-%m-%d %H:%M:%S"),
                             round(float(rng.lognormal(mu, sigma)), 2),
                             rng.choice(["ecommerce", "negozio", "app"], p=[0.6, 0.3, 0.1])))
        return pd.DataFrame(rows, columns=["OrderID", "SubscriberKey", "OrderDate", "Amount", "Channel"])

    # ------------------------------------------------------------------ deploy & run
    def _assign(self, cg: dict, j: dict) -> tuple[pd.DataFrame, np.ndarray]:
        """Emula la Query 1 (+ Update Contact per i touchpoint). Ritorna la DE e il moltiplicatore."""
        self._ensure_entries(j)
        entries = self.de[j["entry_de"]]
        keys = entries["SubscriberKey"]
        buckets = keys.map(lambda k: sfmc_sql.bucket(k, cg["salt"]))
        groups = np.where(buckets < round(cg["holdout_pct"] * 100), "CONTROL", "TREATMENT")
        touch = cg["activity_key"]
        if touch:
            col = "Reach_" + touch
            # attività non di comunicazione (es. un'attesa dopo il primo invio): la raggiungono tutti
            reached = entries[col].to_numpy() if col in entries else np.ones(len(entries), dtype=bool)
            default = j["true_lift"]["journey"] / 2 if cg["scope_id"] == "journey_incrementality" else 0.0
            lift = j["true_lift"].get(touch, default)
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
        self._ensure_entries(j)
        mult = np.ones(len(self.de[j["entry_de"]]))
        for cg in cgs:
            assign, m = self._assign(cg, j)
            self.de[cg["artifacts"]["assignment_de"]["key"]] = assign
            mult = mult * m
        if cgs:
            self.de[j["entry_de"]]["CG_Group"] = self.de[cgs[-1]["artifacts"]["assignment_de"]["key"]]["CG_Group"]
        new_sales = self._gen_sales(j, mult, seed_extra="".join(c["salt"] for c in cgs))
        prefix = _prefix(j)
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
    j = next((x for x in JOURNEYS if x["id"] == jid), None)
    if j is None and jid.startswith("j-") and jid[2:].isdigit():
        i = int(jid[2:])
        if 1 <= i <= SYNTH_COUNT:
            j = catalog()[len(JOURNEYS) + i - 1]
    return j


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
