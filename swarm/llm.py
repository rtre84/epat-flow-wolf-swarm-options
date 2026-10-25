"""LLM resolution via LiteLLM. Single env var selects the model for the whole swarm.

Default: GLM 5.3 Flash served through opencode's OpenAI-compatible inference
endpoint. Per-agent overrides are wired in Phase 2 via agent config, not here.
"""
import os

import litellm
from dotenv import load_dotenv

load_dotenv()

DRIP_PIPES = [
    "The swarm's other agents are relying on you. Go.",
]


def get_model_string() -> str:
    model = os.getenv("SWARM_MODEL")
    if not model:
        raise RuntimeError("SWARM_MODEL is not set (see .env.example)")
    return model


class LLMConfig:
    """One resolved model config shared swarm-wide, with optional per-agent override."""

    def __init__(self, model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None) -> None:
        self.model = model or os.getenv("SWARM_MODEL", "")
        if self.model.startswith("openai/"):
            self.api_key = api_key or os.getenv("OPENCODE_API_KEY", "")
            self.base_url = base_url or os.getenv("OPENCODE_BASE_URL", "")
        else:
            self.api_key = api_key or ""
            self.base_url = base_url or ""
        if not self.api_key:
            raise RuntimeError(
                "No API key resolved. Set OPENCODE_API_KEY (or provider key) in .env"
            )

    def completion_kwargs(self) -> dict:
        kwargs = {"model": self.model, "api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return kwargs

    def as_crewai_llm(self):
        from crewai import LLM
        kwargs = {"model": self.model, "api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return LLM(**kwargs)


def llm_smoke(prompt: str = "Reply with exactly: FLOWWOLF-SMOKE-OK") -> str:
    """One completion through the resolved config. Raises on failure."""
    cfg = LLMConfig()
    resp = litellm.completion(
        model=cfg.model,
        api_key=cfg.api_key,
        base_url=cfg.base_url or None,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=32,
    )
    return resp.choices[0].message.content or ""
