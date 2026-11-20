"""Percorso LLM con server finto compatibile OpenAI: verifica chiamata, parsing e validazione."""
import json

import httpx
import pytest

from app import advisor
from app.llm import LLMClient
from app.sfmc_mock import MockSFMC

journey = MockSFMC().get_journey("j-welcome")


def fake_llm(monkeypatch, content: str):
    calls = []

    def post(url, json=None, timeout=None):  # noqa: A002
        calls.append((url, json))
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", post)
    return calls


def test_llm_interpret_valid_json_in_code_fence(monkeypatch):
    calls = fake_llm(monkeypatch, '```json\n{"scope_id":"touchpoint_value","activity_key":"PUSH1",'
                                  '"confidence":"alta","rationale":"La push","kpi_suggestion":"conversion_rate"}\n```')
    r = advisor.interpret(LLMClient("http://x/v1", "m"), "la push serve?", journey)
    assert r["source"] == "llm" and r["activity_key"] == "PUSH1" and r["kpi_suggestion"] == "conversion_rate"
    url, body = calls[0]
    assert url == "http://x/v1/chat/completions" and body["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("bad", [
    '{"scope_id":"universal_holdout"}',                  # scopo non abilitato
    '{"scope_id":"touchpoint_value","activity_key":"INVENTATA"}',  # attività inesistente, nessun indizio
    "non è json",
])
def test_llm_invalid_answers_fall_back_to_rules(monkeypatch, bad):
    fake_llm(monkeypatch, bad)
    r = advisor.interpret(LLMClient("http://x/v1", "m"), "il journey porta vendite?", journey)
    assert r["source"] == "regole" and r["scope_id"] == "journey_incrementality"


def test_llm_positions_cannot_invent_candidates(monkeypatch):
    fake_llm(monkeypatch, json.dumps({"recommended_id": "pos-FAKE", "narrative": "x"}))
    r = advisor.positions(LLMClient("http://x/v1", "m"), journey, "journey_incrementality", None)
    assert r["source"] == "regole"
    fake_llm(monkeypatch, json.dumps({"recommended_id": "pos-entry", "narrative": "All'ingresso."}))
    r = advisor.positions(LLMClient("http://x/v1", "m"), journey, "journey_incrementality", None)
    assert r["source"] == "llm" and next(c for c in r["candidates"] if c["recommended"])["id"] == "pos-entry"
