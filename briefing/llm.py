"""LLM 제공자 어댑터. 모두 (system, user) -> (텍스트, 토큰 사용량) 형태로 맞춘다.

- openai_compatible: Gemini 무료 티어, Groq, OpenRouter, 로컬 Ollama 등 /chat/completions 규격을 따르는 곳
- anthropic: Claude API (유료)
- none: LLM을 쓰지 않음 (완전 무료, 요약 대신 매체별 제목 비교만 보여줌)
"""
from __future__ import annotations

import logging
import os
import time

import requests

log = logging.getLogger(__name__)

DEFAULT_LLM = {
    "provider": "openai_compatible",
    "model": "gemini-3.8-flash",
    "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "api_key_env": "GEMINI_API_KEY",
}


class OpenAICompatibleLLM:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        max_tokens: int = 3000,
        timeout: int = 90,
        max_attempts: int = 4,
    ):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_attempts = max_attempts

    def __call__(self, system: str, user: str) -> tuple[str, dict]:
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        for attempt in range(1, self.max_attempts + 1):
            resp = requests.post(self.url, json=payload, headers=headers, timeout=self.timeout)
            # 무료 티어는 분당 한도에 자주 걸린다: 잠깐 기다렸다가 재시도
            if resp.status_code in (429, 500, 502, 503) and attempt < self.max_attempts:
                wait = 5 * attempt
                log.warning("LLM %s 응답, %d초 후 재시도 (%d/%d)", resp.status_code, wait, attempt, self.max_attempts)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"].get("content") or ""
            usage = data.get("usage") or {}
            return text, {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            }
        raise RuntimeError("LLM 호출 재시도 초과")  # 도달하지 않지만 타입 안전용


class AnthropicLLM:
    def __init__(self, model: str, api_key: str, max_tokens: int = 2500):
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens

    def __call__(self, system: str, user: str) -> tuple[str, dict]:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        return text, {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
        }


def resolve_llm_config(raw: dict | None) -> dict:
    cfg = {**DEFAULT_LLM, **(raw or {})}
    if override := os.getenv("BRIEFING_MODEL"):
        cfg["model"] = override
    return cfg


def api_key_env(cfg: dict) -> str | None:
    if cfg["provider"] == "none":
        return None
    default = "ANTHROPIC_API_KEY" if cfg["provider"] == "anthropic" else "LLM_API_KEY"
    return cfg.get("api_key_env") or default


def build_llm(cfg: dict):
    """설정에서 호출 가능한 LLM 객체를 만든다. provider가 none이면 None."""
    provider = cfg["provider"]
    if provider == "none":
        return None
    env_name = api_key_env(cfg)
    key = os.getenv(env_name or "")
    if not key:
        raise RuntimeError(f"환경변수 {env_name}가 없습니다 (.env 또는 Actions secrets 확인)")
    if provider == "openai_compatible":
        return OpenAICompatibleLLM(cfg["base_url"], key, cfg["model"])
    if provider == "anthropic":
        return AnthropicLLM(cfg["model"], key)
    raise ValueError(f"알 수 없는 provider: {provider} (openai_compatible | anthropic | none)")
