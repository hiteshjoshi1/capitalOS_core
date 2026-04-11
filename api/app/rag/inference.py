"""
Inference provider configuration for RAG answer generation and wisdom synthesis.

This externalizes the inference runtime choice so the application does not
silently assume a specific vendor/model in feature code.
"""

from __future__ import annotations

import os
from typing import Any


def inference_provider() -> str:
    return os.getenv("INFERENCE_LLM_PROVIDER", "openrouter").strip().lower()


def inference_model() -> str:
    provider = inference_provider()
    default_model = "openai/gpt-4o-mini" if provider == "openrouter" else "gpt-4o-mini"
    return os.getenv("INFERENCE_LLM_MODEL", os.getenv("RAG_LLM_MODEL", default_model)).strip()


def inference_api_key() -> str:
    return os.getenv("INFERENCE_LLM_API_KEY", "").strip()


def inference_base_url() -> str | None:
    provider = inference_provider()
    configured = os.getenv("INFERENCE_LLM_BASE_URL", "").strip()
    if configured:
        return configured
    if provider == "openrouter":
        return "https://openrouter.ai/api/v1"
    return None


def inference_available() -> bool:
    provider = inference_provider()
    api_key = inference_api_key()
    if not api_key:
        return False
    if provider in {"openai", "openrouter"}:
        try:
            import openai  # noqa: F401
            return True
        except ImportError:
            return False
    return False


def create_inference_client() -> Any:
    provider = inference_provider()
    api_key = inference_api_key()
    if provider in {"openai", "openrouter"}:
        import openai

        kwargs: dict[str, Any] = {"api_key": api_key}
        base_url = inference_base_url()
        if base_url:
            kwargs["base_url"] = base_url
        if provider == "openrouter":
            headers: dict[str, str] = {}
            referer = os.getenv("INFERENCE_LLM_HTTP_REFERER", "").strip()
            title = os.getenv("INFERENCE_LLM_APP_NAME", "CapitalOS").strip()
            if referer:
                headers["HTTP-Referer"] = referer
            if title:
                headers["X-Title"] = title
            if headers:
                kwargs["default_headers"] = headers
        return openai.OpenAI(**kwargs)
    raise RuntimeError(f"Unsupported inference provider: {provider}")
