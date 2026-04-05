"""
Embedding generator for RAG ingestion.

Primary provider: Voyage via the `voyageai` SDK.
Fallback provider: OpenAI, when explicitly selected.
Development fallback: deterministic mock embedding used when the requested
provider is unavailable or credentials are absent.

The mock returns a unit vector derived from the text hash so tests can store
valid vectors without making live API calls.
"""

import hashlib
import math
import os
from typing import Sequence

EMBEDDING_DIM = 1024
_DEFAULT_PROVIDER = "voyage"
_DEFAULT_MODEL = "voyage-4"

try:
    import openai as _openai  # type: ignore

    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False
    _openai = None  # type: ignore

try:
    import voyageai as _voyageai  # type: ignore

    _VOYAGE_AVAILABLE = True
except ImportError:
    _VOYAGE_AVAILABLE = False
    _voyageai = None  # type: ignore


def _force_mock() -> bool:
    return os.getenv("RAG_EMBEDDING_MOCK", "0") == "1"


def _provider() -> str:
    return os.getenv("RAG_EMBEDDING_PROVIDER", _DEFAULT_PROVIDER).strip().lower()


def _model() -> str:
    return os.getenv("RAG_EMBEDDING_MODEL", _DEFAULT_MODEL).strip()


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


def _voyage_embed_batch(texts: Sequence[str], model: str, *, input_type: str) -> list[list[float]]:
    client = _voyageai.Client(api_key=os.getenv("VOYAGE_API_KEY", ""))
    response = client.embed(
        list(texts),
        model=model,
        input_type=input_type,
        output_dimension=EMBEDDING_DIM,
    )
    return [list(vec) for vec in response.embeddings]


def _use_mock(provider: str) -> bool:
    if _force_mock() or provider == "mock":
        return True
    if provider == "voyage":
        return not _VOYAGE_AVAILABLE or not os.getenv("VOYAGE_API_KEY", "").strip()
    if provider == "openai":
        return not _OPENAI_AVAILABLE or not os.getenv("OPENAI_API_KEY", "").strip()
    raise ValueError(f"Unsupported embedding provider: {provider}")


def embed_text(text: str) -> list[float]:
    """Return a document embedding for the given text."""
    return embed_batch([text])[0]


def embed_query(text: str) -> list[float]:
    """Return a query embedding for retrieval."""
    provider = _provider()
    if _use_mock(provider):
        return _mock_embedding(text)
    model = _model()
    if provider == "voyage":
        return _voyage_embed_batch([text], model, input_type="query")[0]
    return _openai_embedding(text, model)


def embed_batch(texts: Sequence[str]) -> list[list[float]]:
    """Embed multiple document texts. Returns one embedding per input text."""
    provider = _provider()
    if _use_mock(provider):
        return [_mock_embedding(t) for t in texts]
    model = _model()
    if provider == "voyage":
        return _voyage_embed_batch(texts, model, input_type="document")
    client = _openai.OpenAI()
    response = client.embeddings.create(input=list(texts), model=model)
    ordered = sorted(response.data, key=lambda d: d.index)
    return [d.embedding for d in ordered]


def embedding_model_name() -> str:
    """Return the name of the currently active embedding model."""
    provider = _provider()
    return "mock" if _use_mock(provider) else _model()
