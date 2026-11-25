"""SFMC senza API: l'app legge gli export delle Data Extension da una cartella.

In Marketing Cloud un'automation esporta ogni giorno la DE dei risultati (Data Extract → File Transfer
verso l'SFTP); la cartella letta dall'app è quella dove arrivano i file (SFTP montato, cartella condivisa
o sincronizzata) oppure i file vengono caricati a mano dall'interfaccia.
Senza API l'app non può creare oggetti in SFMC né leggere il catalogo journey: i journey si inseriscono a
mano e Data Extension, query e automation si creano in SFMC con le definizioni generate dall'app.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd

from . import sfmc_mock

_CHANNEL_WORDS = {"sms": "sms", "push": "push", "whatsapp": "sms", "notifica": "push"}


def file_name(de_key: str) -> str:
    return f"{de_key}.csv"


def read_export(raw: bytes) -> pd.DataFrame:
    """CSV o testo delimitato da tab come lo produce una Data Extract (UTF-8 o UTF-16, con intestazioni)."""
    for enc in ("utf-8-sig", "utf-16"):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        if "\x00" in text:
            continue
        df = pd.read_csv(io.StringIO(text), sep=None, engine="python")
        df.columns = [str(c).strip() for c in df.columns]
        return df
    raise ValueError("File non leggibile: atteso un CSV UTF-8 o UTF-16 con intestazioni")


def build_journey(j: dict) -> dict:
    """Journey inserito a mano: messaggi in ordine → attività lineari compatibili con advisor e diagramma."""
    acts = [{"key": "ENTRY", "name": f"Ingresso: {j['entry_de']}", "type": "ENTRY", "channel": None, "step": 0,
             "lane": 0, "reach_rate": 1.0, "next": [], "branch_label": None}]
    step = 1
    for i, name in enumerate(m for m in j.get("messages", []) if m.strip()):
        low = name.lower()
        ch = next((c for w, c in _CHANNEL_WORDS.items() if w in low), "email")
        key = f"{ch.upper()}{i + 1}"
        acts[-1]["next"] = [key]
        acts.append({"key": key, "name": name.strip(), "type": ch.upper(), "channel": ch, "step": step, "lane": 0,
                     "reach_rate": 1.0, "next": [], "branch_label": None})
        step += 1
    acts[-1]["next"] = ["EXIT"]
    acts.append({"key": "EXIT", "name": "Uscita", "type": "EXIT", "channel": None, "step": step, "lane": 0,
                 "reach_rate": 1.0, "next": [], "branch_label": None})
    out = {k: j[k] for k in ("id", "key", "name", "entry_de", "monthly_volume", "baseline")}
    out.update(status=j.get("status") or "Running", entry_source=f"Data Extension: {j['entry_de']}",
               entry_event_key=j.get("entry_event_key") or "", folder=j.get("folder") or None,
               last_modified=None, activity_count=len(acts) - 2,
               channels=sorted({a["channel"] for a in acts if a["channel"]}))
    out["activities"] = [{**a, "monthly_volume": j["monthly_volume"]} for a in acts]
    return out


class FileSFMC:
    mode = "file"

    def __init__(self, folder: str | Path, journeys: list[dict]):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self._journeys = journeys  # lista viva dello stato: i journey aggiunti a mano compaiono subito

    # ------------------------------------------------------------------ journey (inseriti a mano)
    def list_journeys(self) -> list[dict]:
        return [{k: v for k, v in build_journey(j).items() if k != "activities"} for j in self._journeys]

    def search_journeys(self, **kw) -> dict:
        return sfmc_mock.search(self.list_journeys(), **kw)

    def get_journey(self, jid: str) -> dict | None:
        j = next((x for x in self._journeys if x["id"] == jid), None)
        return build_journey(j) if j else None

    # ------------------------------------------------------------------ data extension (da export)
    def path_for(self, key: str) -> Path | None:
        """L'export più recente della DE: «KEY.csv» oppure «KEY_20261125.csv», «KEY 2026-11-25.txt»…"""
        pat = re.compile(rf"^{re.escape(key)}([ _\-.]?\d[\d\-_]*)?\.(csv|txt|tsv)$", re.IGNORECASE)
        files = [p for p in self.folder.iterdir() if p.is_file() and pat.match(p.name)]
        return max(files, key=lambda p: p.stat().st_mtime) if files else None

    def read_de(self, key: str, limit: int | None = None) -> pd.DataFrame:
        p = self.path_for(key)
        if p is None:
            raise KeyError(f"Export della DE «{key}» non trovato in {self.folder}: aggiungi all'automation "
                           f"una Data Extract + File Transfer del file {file_name(key)}, oppure caricalo dall'app")
        df = read_export(p.read_bytes())
        return df.head(limit) if limit else df

    def de_exists(self, key: str) -> bool:
        return self.path_for(key) is not None

    def save_export(self, key: str, raw: bytes) -> Path:
        read_export(raw)  # valida prima di salvare
        dest = self.folder / file_name(key)
        dest.write_bytes(raw)
        return dest
