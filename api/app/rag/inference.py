"""
Inference provider configuration for RAG answer generation and wisdom synthesis.

This externalizes the inference runtime choice so the application does not
silently assume a specific vendor/model in feature code.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

log = logging.getLogger(__name__)


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


def inference_timeout_seconds() -> float:
    raw = os.getenv("INFERENCE_LLM_TIMEOUT_SECONDS", "60").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 60.0
    return max(1.0, value)


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

        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "timeout": inference_timeout_seconds(),
        }
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


def logged_chat_completion(
    *,
    client: Any,
    model: str,
    messages: list[dict[str, str]],
    purpose: str,
    logger: Any | None = None,
    **kwargs: Any,
) -> Any:
    """Run a chat completion with timing/error logs."""
    active_log = logger or log
    started = time.perf_counter()
    provider = inference_provider()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            **kwargs,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        content = ""
        finish_reason = None
        try:
            choices = getattr(response, "choices", []) or []
            if choices:
                finish_reason = getattr(choices[0], "finish_reason", None)
                message = getattr(choices[0], "message", None)
                content = (getattr(message, "content", None) or "") if message else ""
        except Exception:
            content = ""
        active_log.info(
            "llm_call_ok purpose=%s provider=%s model=%s duration_ms=%s content_chars=%d finish_reason=%s",
            purpose,
            provider,
            model,
            elapsed_ms,
            len(content),
            finish_reason,
        )
        return response
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        active_log.warning(
            "llm_call_failed purpose=%s provider=%s model=%s duration_ms=%s error_type=%s error=%s",
            purpose,
            provider,
            model,
            elapsed_ms,
            type(exc).__name__,
            exc,
        )
        raise


# ── Routing / planning model (cheap, fast, independent) ───────────────────────


def routing_model() -> str:
    """
    Return the model to use for pre-retrieval intent routing and query planning.

    Controlled by ROUTING_LLM_MODEL independently from INFERENCE_LLM_MODEL.
    Defaults to a cheap/fast model (Qwen on OpenRouter, gpt-4o-mini elsewhere).
    """
    provider = inference_provider()
    if provider == "openrouter":
        default = "qwen/qwen-2.5-7b-instruct"
    else:
        default = inference_model()
    return os.getenv("ROUTING_LLM_MODEL", default).strip()


def routing_available() -> bool:
    """Return True if the routing model can be called (same criteria as inference)."""
    return inference_available()


def create_routing_client() -> Any:
    """
    Return an OpenAI-compatible client configured for the routing model.

    Uses the same provider / API key / base URL as the inference client so no
    separate credentials are needed.  Only the model name differs.
    """
    return create_inference_client()
