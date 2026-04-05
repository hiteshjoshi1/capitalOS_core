"""
Embedding generator for RAG ingestion.

Primary: OpenAI text-embedding-3-small (1536 dims) via the openai SDK.
Fallback: deterministic mock embedding used when OPENAI_API_KEY is not set
          or the openai package is not installed. The mock returns a unit
          vector derived from the text hash — useful for integration tests
          that need a valid vector without a real API call.

Set RAG_EMBEDDING_MODEL env var to override the model name.
Set RAG_EMBEDDING_MOCK=1 to force the mock regardless of API key presence.
"""

import hashlib
import math
import os
from typing import Sequence

EMBEDDING_DIM = 1536
_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "text-embedding-3-small")
_FORCE_MOCK = os.getenv("RAG_EMBEDDING_MOCK", "0") == "1"

try:
    import openai as _openai  # type: ignore

    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False


def _mock_embedding(text: str) -> list[float]:
    """Deterministic unit-vector mock derived from SHA-256 of text."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # Expand digest to EMBEDDING_DIM floats by cycling through bytes.
    raw = []
    for i in range(EMBEDDING_DIM):
        raw.append(digest[i % len(digest)] / 255.0 - 0.5)
    # Normalise to unit vector.
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]


def _openai_embedding(text: str, model: str) -> list[float]:
    client = _openai.OpenAI()  # reads OPENAI_API_KEY from environment
    response = client.embeddings.create(input=[text], model=model)
    return response.data[0].embedding


def embed_text(text: str) -> list[float]:
    """
    Return a 1536-dimensional embedding for the given text.

    Uses OpenAI if available and OPENAI_API_KEY is set; otherwise uses
    the deterministic mock.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    use_mock = _FORCE_MOCK or not _OPENAI_AVAILABLE or not api_key

    if use_mock:
        return _mock_embedding(text)
    return _openai_embedding(text, _MODEL)


def embed_batch(texts: Sequence[str]) -> list[list[float]]:
    """Embed multiple texts. Returns one embedding per input text."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    use_mock = _FORCE_MOCK or not _OPENAI_AVAILABLE or not api_key

    if use_mock:
        return [_mock_embedding(t) for t in texts]

    client = _openai.OpenAI()
    response = client.embeddings.create(input=list(texts), model=_MODEL)
    ordered = sorted(response.data, key=lambda d: d.index)
    return [d.embedding for d in ordered]


def embedding_model_name() -> str:
    """Return the name of the currently active embedding model."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    use_mock = _FORCE_MOCK or not _OPENAI_AVAILABLE or not api_key
    return "mock" if use_mock else _MODEL
