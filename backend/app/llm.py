"""Client minimale per LLM locali con API compatibile OpenAI (Ollama, LM Studio, vLLM, llama.cpp)."""
from __future__ import annotations

import json
import re
import time

import httpx


class LLMUnavailable(RuntimeError):
    pass


class LLMClient:
    def __init__(self, base_url: str, model: str, enabled: bool = True, timeout: float = 120):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.enabled = enabled
        self.timeout = timeout
        self._reach_cache: tuple[float, bool] = (0.0, False)

    def reachable(self) -> bool:
        if not self.enabled:
            return False
        ts, ok = self._reach_cache
        if time.time() - ts < 20:
            return ok
        try:
            r = httpx.get(f"{self.base_url}/models", timeout=2)
            ok = r.status_code == 200
        except httpx.HTTPError:
            ok = False
        self._reach_cache = (time.time(), ok)
        return ok

    def chat(self, system: str, user: str, json_mode: bool = False, temperature: float = 0.2) -> str:
        if not self.enabled:
            raise LLMUnavailable("LLM disattivato nelle impostazioni")
        body = {"model": self.model, "temperature": temperature,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            r = httpx.post(f"{self.base_url}/chat/completions", json=body, timeout=self.timeout)
        except httpx.HTTPError as e:
            self._reach_cache = (time.time(), False)
            raise LLMUnavailable(f"LLM non raggiungibile: {e}") from e
        if r.status_code != 200:
            raise LLMUnavailable(f"LLM ha risposto {r.status_code}: {r.text[:200]}")
        return r.json()["choices"][0]["message"]["content"].strip()

    def chat_json(self, system: str, user: str) -> dict:
        text = self.chat(system, user, json_mode=True)
        return parse_json(text)


def parse_json(text: str) -> dict:
    """I modelli piccoli a volte avvolgono il JSON in ```...``` o testo: estrai il primo oggetto."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if not m:
            raise LLMUnavailable("Risposta LLM non in formato JSON")
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError as e:
            raise LLMUnavailable("Risposta LLM non in formato JSON") from e
