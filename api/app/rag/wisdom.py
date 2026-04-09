"""
Author wisdom profile generation.

Generates and persists a compact, auditable author wisdom artifact from the
ingested corpus.  Two synthesis paths:

  1. LLM synthesis (OpenAI GPT) - when OPENAI_API_KEY is set.
  2. Template synthesis (deterministic fallback) - always available.

The artifact is stored in rag_author_profiles.
Citations are persisted in rag_author_profile_citations.
"""

from __future__ import annotations

import logging
import os
import textwrap
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.rag import RagAuthor, RagAuthorCard, RagAuthorProfile, RagAuthorProfileCitation
from app.rag.retrieval import retrieve_similar_chunks

log = logging.getLogger(__name__)

_MAX_PROFILE_CHUNKS = 20
_PROFILE_TOP_K = 30


def _llm_available() -> bool:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return False
    try:
        import openai  # noqa: F401
        return True
    except ImportError:
        return False


def _generate_profile_llm(
    author: RagAuthor,
    card: Optional[RagAuthorCard],
    chunk_texts: list[str],
) -> dict:
    """Use OpenAI GPT to synthesize the author wisdom profile from corpus chunks."""
    import json
    import openai

    sample_text = "\n\n---\n\n".join(chunk_texts[:_MAX_PROFILE_CHUNKS])
    focus_str = ", ".join(card.focus_areas) if card and card.focus_areas else "not specified"
    avoid_str = ", ".join(card.avoid_patterns) if card and card.avoid_patterns else "not specified"
    biases_str = ", ".join(card.biases) if card and card.biases else "not specified"

    prompt = textwrap.dedent(f"""
        You are analyzing the writings of {author.name} ({author.role_type or 'thinker'}).

        Known focus areas: {focus_str}
        Known avoid patterns: {avoid_str}
        Known biases: {biases_str}

        Below are representative passages from their corpus:
        ---
        {sample_text}
        ---

        Based on these passages, produce a structured wisdom profile with these exact fields:
        1. worldview: 2-3 sentence summary of their core mental model and philosophy
        2. key_maxims: list of 5-8 concise maxims or principles they hold (each <= 20 words)
        3. strengths: list of 3-5 areas where their framework excels
        4. weaknesses: list of 2-4 blind spots or limitations of their approach
        5. favored_decision_variables: list of 4-6 metrics or factors they prioritize in decisions
        6. anti_patterns: list of 3-5 behaviors or patterns they explicitly avoid or warn against

        Respond in JSON only with keys: worldview, key_maxims, strengths, weaknesses,
        favored_decision_variables, anti_patterns.
    """).strip()

    client = openai.OpenAI()
    response = client.chat.completions.create(
        model=os.getenv("RAG_LLM_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    raw = response.choices[0].message.content or "{}"
    return json.loads(raw)


def _generate_profile_template(
    author: RagAuthor,
    card: Optional[RagAuthorCard],
    chunk_texts: list[str],
) -> dict:
    """
    Deterministic template-based profile synthesis.

    Derives wisdom from the reasoning_lens config card + corpus signal.
    """
    focus = list(card.focus_areas) if card and card.focus_areas else []
    avoid = list(card.avoid_patterns) if card and card.avoid_patterns else []
    biases = list(card.biases) if card and card.biases else []
    expertise = list(author.expertise_tags or [])
    domains = list(author.domains or [])

    worldview_parts = []
    if focus:
        worldview_parts.append(f"{author.name} focuses on {', '.join(focus[:3])}.")
    if domains:
        worldview_parts.append(f"Operates primarily in {', '.join(domains)}.")
    if biases:
        worldview_parts.append(f"Key orientation: {biases[0]}.")
    worldview = (
        " ".join(worldview_parts)
        if worldview_parts
        else f"{author.name} is a {author.role_type or 'thinker'} with expertise in {', '.join(expertise[:4])}."
    )

    key_maxims = [f"Focus on {f}" for f in focus[:5]]
    if not key_maxims:
        key_maxims = [f"Apply {tag.replace('_', ' ')} principles" for tag in expertise[:5]]

    strengths = focus[:4] if focus else expertise[:4]
    weaknesses = (
        avoid[:3]
        if avoid
        else [f"May underweight factors outside {domains[0]}" if domains else "Scope limitations not documented"]
    )
    favored = expertise[:6]
    anti = [f"Avoid {a}" for a in avoid[:4]] if avoid else ["No explicit anti-patterns documented"]

    return {
        "worldview": worldview,
        "key_maxims": key_maxims,
        "strengths": [s for s in strengths],
        "weaknesses": [w for w in weaknesses],
        "favored_decision_variables": [v.replace("_", " ") for v in favored],
        "anti_patterns": anti,
    }


def refresh_author_profile(
    author_id: str,
    db: Session,
    *,
    force_template: bool = False,
) -> RagAuthorProfile:
    """
    Generate (or regenerate) the wisdom profile for a single author.

    Args:
        author_id:      ID of the author to profile.
        db:             Database session.
        force_template: If True, skip LLM and use template synthesis.

    Returns the persisted RagAuthorProfile.
    """
    author = db.get(RagAuthor, author_id)
    if not author:
        raise ValueError(f"Author '{author_id}' not found")
    if not author.enabled:
        raise ValueError(f"Author '{author_id}' is not enabled")

    card = db.get(RagAuthorCard, author_id)

    # Retrieve representative corpus chunks
    chunks = retrieve_similar_chunks(
        author.name,
        db,
        top_k=_PROFILE_TOP_K,
        author_id=author_id,
    )
    chunk_texts = [c.text for c in chunks]
    chunk_ids = [c.chunk_id for c in chunks]

    # Choose synthesis path
    use_llm = _llm_available() and not force_template
    generation_model = "mock"
    if use_llm:
        try:
            profile_data = _generate_profile_llm(author, card, chunk_texts)
            generation_model = os.getenv("RAG_LLM_MODEL", "gpt-4o-mini")
        except Exception as exc:
            log.warning("LLM synthesis failed for %s, falling back to template: %s", author_id, exc)
            profile_data = _generate_profile_template(author, card, chunk_texts)
    else:
        profile_data = _generate_profile_template(author, card, chunk_texts)

    now = datetime.now(timezone.utc)

    # Upsert profile
    existing = db.query(RagAuthorProfile).filter(RagAuthorProfile.author_id == author_id).first()
    if existing:
        profile = existing
        # Clear old citations
        db.query(RagAuthorProfileCitation).filter(
            RagAuthorProfileCitation.profile_id == str(existing.id)
        ).delete()
    else:
        profile = RagAuthorProfile(author_id=author_id)
        db.add(profile)
        db.flush()

    profile.worldview = profile_data.get("worldview", "")
    profile.key_maxims = profile_data.get("key_maxims", [])
    profile.strengths = profile_data.get("strengths", [])
    profile.weaknesses = profile_data.get("weaknesses", [])
    profile.favored_decision_variables = profile_data.get("favored_decision_variables", [])
    profile.anti_patterns = profile_data.get("anti_patterns", [])
    profile.generation_model = generation_model
    profile.corpus_chunk_count = len(chunks)
    profile.generated_at = now

    db.flush()

    # Store citations
    for chunk_id in chunk_ids[:10]:
        citation = RagAuthorProfileCitation(
            profile_id=str(profile.id),
            chunk_id=chunk_id,
            citation_context="representative corpus sample",
        )
        db.add(citation)

    db.flush()
    return profile


def refresh_all_profiles(
    db: Session,
    *,
    force_template: bool = False,
) -> list[dict]:
    """
    Refresh wisdom profiles for all enabled authors.

    Returns a list of result dicts: {author_id, status, error}.
    """
    from app.models.rag import RagAuthor

    authors = db.query(RagAuthor).filter(RagAuthor.enabled == True).all()  # noqa: E712
    results = []
    for author in authors:
        try:
            profile = refresh_author_profile(author.id, db, force_template=force_template)
            db.commit()
            results.append({"author_id": author.id, "status": "ok", "chunk_count": profile.corpus_chunk_count})
        except Exception as exc:
            db.rollback()
            log.exception("Profile refresh failed for %s: %s", author.id, exc)
            results.append({"author_id": author.id, "status": "error", "error": str(exc)})
    return results
