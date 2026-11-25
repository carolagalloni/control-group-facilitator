"""Adapter SFMC reale (Installed Package server-to-server). Stessa interfaccia di MockSFMC.

NOTA: scritto sulla base della documentazione pubblica delle API SFMC; non è stato possibile
testarlo contro una BU reale nell'ambiente di sviluppo. Verificare su una BU di test prima della demo.
Permessi richiesti al package: Journeys (Read/Write), Data Extensions (Read/Write),
Automations (Read/Write/Execute), List and Subscribers (Read).
"""
from __future__ import annotations

import time
from xml.sax.saxutils import escape

import httpx
import pandas as pd

TYPE_MAP = {
    "EMAILV2": "EMAIL", "EMAIL": "EMAIL", "SMSSYNC": "SMS", "SMS": "SMS",
    "PUSHNOTIFICATIONACTIVITY": "PUSH", "PUSHINBOXACTIVITY": "PUSH", "INAPPSYNC": "PUSH",
    "WAIT": "WAIT", "WAITBYDURATION": "WAIT", "WAITBYATTRIBUTE": "WAIT", "STOWAIT": "WAIT",
    "MULTICRITERIADECISION": "DECISION", "RANDOMSPLIT": "DECISION", "ENGAGEMENTSPLIT": "DECISION",
    "ENGAGEMENTDECISION": "DECISION", "ABNTEST": "DECISION",
}
CHANNEL = {"EMAIL": "email", "SMS": "sms", "PUSH": "push"}
DEFAULT_BASELINE = {"conversion_rate": 0.03, "avg_order_value": 85.0, "expected_lift": 0.08}
DEFAULT_VOLUME = 10000


class SFMCError(RuntimeError):
    pass


class LiveSFMC:
    mode = "live"

    def __init__(self, subdomain: str, client_id: str, client_secret: str, mid: str | None = None):
        if not (subdomain and client_id and client_secret):
            raise SFMCError("Configurazione SFMC incompleta: servono subdomain, client id e client secret")
        self.subdomain, self.client_id, self.client_secret, self.mid = subdomain, client_id, client_secret, mid
        self._token: str | None = None
        self._exp = 0.0
        self.rest = f"https://{subdomain}.rest.marketingcloudapis.com"
        self.soap = f"https://{subdomain}.soap.marketingcloudapis.com/Service.asmx"
        self.http = httpx.Client(timeout=60)
        self._journeys: dict[str, dict] = {}

    # ------------------------------------------------------------------ auth
    def token(self) -> str:
        if self._token and time.time() < self._exp - 60:
            return self._token
        body = {"grant_type": "client_credentials", "client_id": self.client_id,
                "client_secret": self.client_secret}
        if self.mid:
            body["account_id"] = self.mid
        r = self.http.post(f"https://{self.subdomain}.auth.marketingcloudapis.com/v2/token", json=body)
        if r.status_code != 200:
            raise SFMCError(f"Autenticazione SFMC fallita ({r.status_code}): {r.text[:300]}")
        data = r.json()
        self._token, self._exp = data["access_token"], time.time() + data.get("expires_in", 1000)
        if data.get("rest_instance_url"):
            self.rest = data["rest_instance_url"].rstrip("/")
        if data.get("soap_instance_url"):
            self.soap = data["soap_instance_url"].rstrip("/") + "/Service.asmx"
        return self._token

    def _req(self, method: str, path: str, **kw) -> dict:
        r = self.http.request(method, self.rest + path, headers={"Authorization": f"Bearer {self.token()}"}, **kw)
        if r.status_code >= 400:
            raise SFMCError(f"SFMC {method} {path} → {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    def _soap(self, action: str, body: str) -> str:
        env = f"""<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">
<s:Header><a:Action s:mustUnderstand="1">{action}</a:Action><a:To s:mustUnderstand="1">{self.soap}</a:To>
<fueloauth xmlns="http://exacttarget.com">{self.token()}</fueloauth></s:Header>
<s:Body xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">{body}</s:Body></s:Envelope>"""
        r = self.http.post(self.soap, content=env.encode(),
                           headers={"Content-Type": "application/soap+xml; charset=utf-8"})
        if r.status_code >= 400 or "<OverallStatus>Error" in r.text:
            raise SFMCError(f"SOAP {action} fallita: {r.text[:500]}")
        return r.text

    # ------------------------------------------------------------------ journeys
    def list_journeys(self) -> list[dict]:
        data = self._req("GET", "/interaction/v1/interactions",
                         params={"mostRecentVersionOnly": "true", "$pageSize": 50, "extras": "activities"})
        out = []
        for it in data.get("items", []):
            j = self._map_journey(it)
            self._journeys[j["id"]] = j
            out.append({k: v for k, v in j.items() if k != "activities"})
        return out

    def search_journeys(self, q: str = "", status: str = "", folder: str = "", channel: str = "",
                        sort: str = "name", page: int = 1, page_size: int = 25) -> dict:
        """Ricerca lato SFMC (GET /interaction/v1/interactions): con migliaia di journey non si scarica
        tutto il catalogo, si chiede a Marketing Cloud solo la pagina richiesta."""
        page_size = max(1, min(page_size, 100))
        params = {"mostRecentVersionOnly": "true", "extras": "activities", "$page": max(1, page),
                  "$pageSize": page_size,
                  "$orderBy": {"name": "name ASC", "modified": "modifiedDate DESC"}.get(sort, "name ASC")}
        if q:
            params["nameOrDescription"] = q
        if status:
            params["status"] = status
        data = self._req("GET", "/interaction/v1/interactions", params=params)
        items = []
        for it in data.get("items", []):
            j = self._map_journey(it)
            self._journeys[j["id"]] = j
            pub = {k: v for k, v in j.items() if k != "activities"}
            pub["channels"] = sorted({a["channel"] for a in j["activities"] if a.get("channel")})
            pub["last_modified"] = (it.get("modifiedDate") or "")[:10] or None
            pub["folder"] = None
            items.append(pub)
        if channel:
            items = [j for j in items if channel in j["channels"]]
        return {"items": items, "total": int(data.get("count", len(items))), "page": page,
                "page_size": page_size, "facets": {}}

    def get_journey(self, jid: str) -> dict | None:
        it = self._req("GET", f"/interaction/v1/interactions/{jid}")
        j = self._map_journey(it)
        self._journeys[jid] = j
        return j

    def _map_journey(self, it: dict) -> dict:
        acts = it.get("activities", []) or []
        trig = (it.get("triggers") or [{}])[0]
        event_key = (trig.get("metaData") or {}).get("eventDefinitionKey") or \
            (trig.get("configurationArguments") or {}).get("eventDefinitionKey", "")
        by_key = {a["key"]: a for a in acts}
        nexts = {a["key"]: [o.get("next") for o in a.get("outcomes", []) if o.get("next")] for a in acts}
        targets = {n for v in nexts.values() for n in v}
        roots = [a["key"] for a in acts if a["key"] not in targets] or ([acts[0]["key"]] if acts else [])
        # layout: step = profondità BFS, lane = indice di ramo
        step, lane, order = {}, {}, []
        queue = [(k, 1, i) for i, k in enumerate(roots)]
        while queue:
            k, s, ln = queue.pop(0)
            if k in step or k not in by_key:
                continue
            step[k], lane[k] = s, ln
            order.append(k)
            for bi, n in enumerate(nexts[k]):
                queue.append((n, s + 1, ln + bi))
        activities = [{"key": "ENTRY", "name": "Ingresso", "type": "ENTRY", "channel": None, "step": 0, "lane": 0,
                       "reach_rate": 1.0, "monthly_volume": DEFAULT_VOLUME, "next": roots, "branch_label": None}]
        for k in order:
            a = by_key[k]
            t = TYPE_MAP.get(str(a.get("type", "")).upper(), "WAIT")
            activities.append({"key": k, "name": a.get("name") or k, "type": t, "channel": CHANNEL.get(t),
                               "step": step[k], "lane": lane[k], "reach_rate": 1.0,
                               "monthly_volume": DEFAULT_VOLUME, "next": nexts[k], "branch_label": None})
        if not any(a["type"] == "EXIT" for a in activities):
            last = max(step.values(), default=0) + 1
            activities.append({"key": "EXIT", "name": "Uscita", "type": "EXIT", "channel": None, "step": last,
                               "lane": 0, "reach_rate": 1.0, "monthly_volume": DEFAULT_VOLUME, "next": [],
                               "branch_label": None})
            for a in activities:
                if a["type"] != "EXIT" and not a["next"]:
                    a["next"] = ["EXIT"]
        return {
            "id": it["id"], "key": it.get("key", ""), "name": it.get("name", ""), "status": it.get("status", ""),
            "entry_source": f"Evento: {event_key}" if event_key else "n/d",
            "entry_de": (trig.get("configurationArguments") or {}).get("dataExtensionKey", ""),
            "entry_event_key": event_key,
            # Volumi e baseline non sono esposti dall'API journey: valori di default modificabili nel wizard.
            "monthly_volume": DEFAULT_VOLUME, "baseline": dict(DEFAULT_BASELINE),
            "activity_count": len(acts), "activities": activities,
        }

    # ------------------------------------------------------------------ data extensions
    def create_de(self, key: str, fields: list[dict]) -> str:
        def field_xml(f):
            extra = ""
            if f["type"] == "Text":
                extra = f"<MaxLength>{f.get('length', 254)}</MaxLength>"
            if f["type"] == "Decimal":
                extra = f"<Precision>{f.get('precision', 18)}</Precision><Scale>{f.get('scale', 2)}</Scale>"
            pk = "true" if f.get("pk") else "false"
            return (f"<Field><Name>{escape(f['name'])}</Name><FieldType>{f['type']}</FieldType>{extra}"
                    f"<IsPrimaryKey>{pk}</IsPrimaryKey><IsRequired>{pk}</IsRequired></Field>")
        body = (f'<CreateRequest xmlns="http://exacttarget.com/wsdl/partnerAPI"><Objects xsi:type="DataExtension">'
                f"<CustomerKey>{escape(key)}</CustomerKey><Name>{escape(key)}</Name>"
                f"<Fields>{''.join(field_xml(f) for f in fields)}</Fields></Objects></CreateRequest>")
        self._soap("Create", body)
        return "ok"

    def de_exists(self, key: str) -> bool:
        try:
            self._req("GET", f"/data/v1/customobjectdata/key/{key}/rowset", params={"$pageSize": 1})
            return True
        except SFMCError:
            return False

    def read_de(self, key: str, limit: int | None = None) -> pd.DataFrame:
        rows, page = [], 1
        while True:
            size = min(limit, 2500) if limit else 2500
            data = self._req("GET", f"/data/v1/customobjectdata/key/{key}/rowset",
                             params={"$page": page, "$pageSize": size})
            for it in data.get("items", []):
                rows.append({**it.get("keys", {}), **it.get("values", {})})
            if limit and len(rows) >= limit:
                break
            if page * size >= data.get("count", 0) or not data.get("items"):
                break
            page += 1
        df = pd.DataFrame(rows)
        # le API restituiscono i nomi colonna in minuscolo
        return df.rename(columns={c: _canon(c) for c in df.columns})

    def create_query(self, name: str, sql: str, target: str, update_type: int = 1) -> str:
        payload = {"name": name, "key": name, "queryText": sql, "targetName": target, "targetKey": target,
                   "targetUpdateTypeId": update_type}  # 0 = overwrite, 1 = update, 2 = append
        self._req("POST", "/automation/v1/queries", json=payload)
        return "ok"

    def run_query(self, name: str) -> None:
        found = self._req("GET", "/automation/v1/queries", params={"$filter": f"key eq '{name}'"})
        items = found.get("items", [])
        if not items:
            raise SFMCError(f"Query Activity {name} non trovata")
        self._req("POST", f"/automation/v1/queries/{items[0]['queryDefinitionId']}/actions/start/")


_CANON = {c.lower(): c for c in ["SnapshotDate", "CG_Group", "Contacts", "Converters", "Orders", "Revenue",
                                 "RevenueSq", "OrdersSq", "RevenueOrders", "SubscriberKey", "OrderID",
                                 "OrderDate", "Amount", "Channel", "AssignedDate", "ExposureDate", "Bucket",
                                 "JourneyKey"]}


def _canon(c: str) -> str:
    return _CANON.get(c.lower(), c)
