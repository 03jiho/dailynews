import pytest

from briefing import llm as llm_mod
from briefing.cluster import cluster_articles
from briefing.llm import OpenAICompatibleLLM, build_llm, resolve_llm_config
from briefing.summarize import summarize_clusters

from .samples import ALL


class FakeResp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


OK_BODY = {
    "choices": [{"message": {"content": "[]"}}],
    "usage": {"prompt_tokens": 12, "completion_tokens": 3},
}


def test_openai_compatible_parses_text_and_usage(monkeypatch):
    seen = {}

    def fake_post(url, json, headers, timeout):
        seen.update(url=url, auth=headers["Authorization"], model=json["model"], roles=[m["role"] for m in json["messages"]], fmt=json["response_format"]["type"])
        return FakeResp(200, OK_BODY)

    monkeypatch.setattr(llm_mod.requests, "post", fake_post)
    text, usage = OpenAICompatibleLLM("https://x.test/v1/", "KEY", "m1")("sys", "user")
    assert text == "[]" and usage == {"input_tokens": 12, "output_tokens": 3}
    assert seen == {"url": "https://x.test/v1/chat/completions", "auth": "Bearer KEY", "model": "m1", "roles": ["system", "user"], "fmt": "json_object"}


def test_truncated_response_raises_instead_of_returning_broken_json(monkeypatch):
    body = {"choices": [{"message": {"content": '{"items": [{"clus'}, "finish_reason": "length"}]}
    monkeypatch.setattr(llm_mod.requests, "post", lambda *a, **k: FakeResp(200, body))
    with pytest.raises(RuntimeError, match="잘림"):
        OpenAICompatibleLLM("https://x.test/v1/", "KEY", "m1")("sys", "user")


def test_retries_on_rate_limit_then_succeeds(monkeypatch):
    responses = iter([FakeResp(429), FakeResp(429), FakeResp(200, OK_BODY)])
    monkeypatch.setattr(llm_mod.requests, "post", lambda *a, **k: next(responses))
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)
    text, _ = OpenAICompatibleLLM("https://x.test", "K", "m")("s", "u")
    assert text == "[]"


def test_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr(llm_mod.requests, "post", lambda *a, **k: FakeResp(429))
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        OpenAICompatibleLLM("https://x.test", "K", "m", max_attempts=2)("s", "u")


def test_build_llm_provider_rules(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    cfg = resolve_llm_config(None)
    assert cfg["provider"] == "openai_compatible" and cfg["api_key_env"] == "GEMINI_API_KEY"
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        build_llm(cfg)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert isinstance(build_llm(cfg), OpenAICompatibleLLM)
    assert build_llm({**cfg, "provider": "none"}) is None  # 키 없이도 동작
    with pytest.raises(ValueError):
        build_llm({**cfg, "provider": "???"})


def test_model_env_override(monkeypatch):
    monkeypatch.setenv("BRIEFING_MODEL", "other-model")
    assert resolve_llm_config({"model": "from-config"})["model"] == "other-model"


def test_no_llm_mode_lists_each_outlet_headline():
    clusters = [c for c in cluster_articles(ALL) if len(c.sources) >= 2]
    briefings, usage = summarize_clusters(clusters, None)
    assert usage["llm_calls"] == 0
    rate = max(briefings, key=lambda b: len(b.sources))
    assert "• 연합뉴스: 한국은행 기준금리 연 2.50%로 동결" in rate.summary
    assert "• 한겨레:" in rate.summary and rate.flags == []
