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


def test_llm_interpret_activity_key_in_scope_field(monkeypatch):
    # qwen2.5:7b a volte mette la chiave dell'attività in scope_id
    fake_llm(monkeypatch, '{"scope_id":"SMS1","activity_key":"SMS1","confidence":"alta","rationale":"x"}')
    r = advisor.interpret(LLMClient("http://x/v1", "m"), "l'sms serve?", journey)
    assert r["source"] == "llm" and r["scope_id"] == "touchpoint_value" and r["activity_key"] == "SMS1"


def test_llm_positions_cannot_override_rule_choice(monkeypatch):
    # la posizione è decisa dalle regole: un'altra posizione valida proposta dal modello è scartata
    fake_llm(monkeypatch, json.dumps({"recommended_id": "pos-WAIT1", "narrative": "Dopo il primo invio."}))
    r = advisor.positions(LLMClient("http://x/v1", "m"), journey, "journey_incrementality", None)
    assert r["source"] == "regole" and next(c for c in r["candidates"] if c["recommended"])["id"] == "pos-entry"
    calls = fake_llm(monkeypatch, json.dumps({"recommended_id": "pos-SMS1", "narrative": "Prima dell'SMS."}))
    r = advisor.positions(LLMClient("http://x/v1", "m"), journey, "touchpoint_value", "SMS1")
    assert r["source"] == "llm" and next(c for c in r["candidates"] if c["recommended"])["id"] == "pos-SMS1"
    assert "pos-SMS1" in calls[0][1]["messages"][1]["content"]


def test_llm_text_cleanup_truncation_and_ids(monkeypatch):
    # in JSON mode una virgoletta doppia chiude la stringa: il testo arriva troncato a metà frase
    fake_llm(monkeypatch, json.dumps({"recommended_id": "pos-entry",
                                      "narrative": "Misura tutto il journey. L'alternativa 'Dopo "}))
    r = advisor.positions(LLMClient("http://x/v1", "m"), journey, "journey_incrementality", None)
    assert r["source"] == "llm" and r["narrative"] == "Misura tutto il journey."
    fake_llm(monkeypatch, '{"scope_id":"journey_incrementality","activity_key":null,"confidence":"bassa",'
                          '"rationale":"Non si può usare touchpoint_value."}')
    r = advisor.interpret(LLMClient("http://x/v1", "m"), "troppe comunicazioni?", journey)
    assert "touchpoint_value" not in r["rationale"]


def test_llm_explain_sizing_gets_oriented_facts(monkeypatch):
    from app import stats
    req = {"monthly_volume": 40000, "baseline_conversion": 0.08, "avg_order_value": 120.0, "aov_cv": 1.0,
           "expected_lift": 0.12, "duration_days": 60, "alpha": 0.05, "power": 0.8, "kpi": "revenue_per_contact"}
    sz = stats.sizing(**req)
    assert sz["verdict"] == "al limite"
    calls = fake_llm(monkeypatch, "Il test è al limite.")
    r = advisor.explain_sizing(LLMClient("http://x/v1", "m"), journey, "journey_incrementality", req, sz)
    prompt = calls[0][1]["messages"][1]["content"]
    assert r["source"] == "llm" and "costerebbe di più" in prompt and "allungare il test a circa" in prompt
