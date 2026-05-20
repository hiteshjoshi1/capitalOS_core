from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import inspect, select
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.orm import Session, selectinload

from app.models.ai_sage_chat import AISageChat, AISageMessage, AISageTurnEvidence
from app.rag.company_thesis_mode import classify_query_as_thesis, execute_thesis_query
from app.rag.concept_mode import execute_concept_query
from app.schemas.ai_sage import ConceptQueryOut

AI_SAGE_CHAT_RETENTION_DAYS = 365
AI_SAGE_CONTEXT_MESSAGE_COUNT = 5
DEFAULT_CHAT_TITLE = "New chat"
_DISPLAY_SENTENCE_MAX_CHARS = 280
_DISPLAY_FALLBACK_MAX_CHARS = 240
_DISPLAY_EVIDENCE_LIMIT = 8
_DISPLAY_DUPLICATE_THRESHOLD = 0.86
_DISPLAY_DUPLICATE_MIN_CHARS = 48
_DISPLAY_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_DISPLAY_TOKEN_RE = re.compile(r"[a-z0-9]+")
_DISPLAY_WHITESPACE_RE = re.compile(r"\s+")
_DISPLAY_STOPWORDS = {
    "about",
    "after",
    "because",
    "business",
    "does",
    "emphasize",
    "emphasizes",
    "first",
    "from",
    "have",
    "into",
    "just",
    "made",
    "mistakes",
    "over",
    "said",
    "says",
    "that",
    "their",
    "there",
    "these",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
}


@dataclass
class AISageTurnExecution:
    mode: str
    assistant_text: str
    result: ConceptQueryOut
    metadata: dict[str, Any]
    evidence: list[dict[str, Any]]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _id_str(value: Any) -> str:
    return str(value)


def _orm_id_str(value: Any) -> str:
    try:
        state = inspect(value)
    except NoInspectionAvailable:
        return _id_str(value)
    if state.identity and len(state.identity) == 1:
        return _id_str(state.identity[0])
    return _id_str(getattr(value, "id"))


def prune_expired_ai_sage_chats(db: Session, owner_user_id: int | None = None) -> int:
    cutoff = utc_now() - timedelta(days=AI_SAGE_CHAT_RETENTION_DAYS)
    query = (
        select(AISageChat)
        .options(selectinload(AISageChat.messages).selectinload(AISageMessage.evidence))
        .where(AISageChat.last_activity_at < cutoff)
    )
    if owner_user_id is not None:
        query = query.where(AISageChat.owner_user_id == owner_user_id)
    chats = db.execute(query).scalars().unique().all()
    for chat in chats:
        db.delete(chat)
    if chats:
        db.commit()
    return len(chats)


def get_chat_or_404(db: Session, owner_user_id: int, chat_id: str) -> AISageChat:
    prune_expired_ai_sage_chats(db, owner_user_id=owner_user_id)
    chat = db.execute(
        select(AISageChat)
        .options(selectinload(AISageChat.messages).selectinload(AISageMessage.evidence))
        .where(AISageChat.id == chat_id, AISageChat.owner_user_id == owner_user_id)
    ).scalars().unique().one_or_none()
    if chat is None:
        raise HTTPException(status_code=404, detail="AI Sage chat not found")
    return chat


def list_chats(db: Session, owner_user_id: int, *, limit: int, offset: int) -> list[AISageChat]:
    prune_expired_ai_sage_chats(db, owner_user_id=owner_user_id)
    return (
        db.execute(
            select(AISageChat)
            .options(selectinload(AISageChat.messages))
            .where(AISageChat.owner_user_id == owner_user_id)
            .order_by(AISageChat.pinned_at.desc(), AISageChat.updated_at.desc(), AISageChat.id.desc())
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .unique()
        .all()
    )


def search_chats(db: Session, owner_user_id: int, query_text: str, *, limit: int) -> list[tuple[AISageChat, str | None]]:
    chats = (
        db.execute(
            select(AISageChat)
            .options(selectinload(AISageChat.messages))
            .where(AISageChat.owner_user_id == owner_user_id)
            .order_by(AISageChat.updated_at.desc(), AISageChat.id.desc())
        )
        .scalars()
        .unique()
        .all()
    )
    normalized = query_text.strip().lower()
    if not normalized:
        return []

    matches: list[tuple[AISageChat, str | None]] = []
    for chat in chats:
        if normalized in (chat.title or "").lower():
            matches.append((chat, _snippet_for_text(chat.title or "", normalized)))
            continue
        for message in _sorted_messages(chat.messages):
            if normalized in (message.content or "").lower():
                matches.append((chat, _snippet_for_text(message.content, normalized)))
                break
    return matches[:limit]


def create_chat(db: Session, owner_user_id: int, title: str | None = None) -> AISageChat:
    now = utc_now()
    chat = AISageChat(
        owner_user_id=owner_user_id,
        title=(title or DEFAULT_CHAT_TITLE).strip() or DEFAULT_CHAT_TITLE,
        last_activity_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return chat


def rename_chat(chat: AISageChat, *, title: str | None = None, pinned: bool | None = None) -> AISageChat:
    if title is not None:
        clean = title.strip()
        if not clean:
            raise HTTPException(status_code=422, detail="title: String should have at least 1 character")
        chat.title = clean
    if pinned is not None:
        chat.pinned_at = utc_now() if pinned else None
    chat.updated_at = utc_now()
    return chat


def delete_chat(db: Session, chat: AISageChat) -> None:
    db.delete(chat)
    db.commit()


def _sorted_messages(messages: list[AISageMessage]) -> list[AISageMessage]:
    return sorted(messages, key=lambda message: (_coerce_dt(message.created_at), message.id))


def build_context_messages(chat: AISageChat, *, before_message_id: str | None = None) -> list[AISageMessage]:
    collected: list[AISageMessage] = []
    for message in _sorted_messages(chat.messages):
        if before_message_id is not None and _id_str(message.id) == _id_str(before_message_id):
            break
        if message.role not in {"user", "assistant"} or message.status != "completed":
            continue
        collected.append(message)
    return collected[-AI_SAGE_CONTEXT_MESSAGE_COUNT:]


def create_user_message(db: Session, chat: AISageChat, content: str) -> AISageMessage:
    now = utc_now()
    message = AISageMessage(
        chat_id=_id_str(chat.id),
        role="user",
        content=content,
        status="completed",
        created_at=now,
        completed_at=now,
        metadata_json=None,
    )
    db.add(message)
    if chat.title == DEFAULT_CHAT_TITLE:
        chat.title = _title_from_prompt(content)
    chat.last_activity_at = now
    chat.updated_at = now
    db.commit()
    db.refresh(message)
    db.refresh(chat)
    return message


def create_assistant_placeholder(db: Session, chat: AISageChat, source_user_message_id: str) -> AISageMessage:
    now = utc_now()
    message = AISageMessage(
        chat_id=_id_str(chat.id),
        role="assistant",
        content="",
        status="in_progress",
        created_at=now,
        metadata_json={"source_user_message_id": _id_str(source_user_message_id)},
    )
    db.add(message)
    chat.updated_at = now
    db.commit()
    db.refresh(message)
    return message


def _load_persistent_chat_and_message(
    db: Session,
    *,
    chat_id: str,
    assistant_message_id: str,
) -> tuple[AISageChat, AISageMessage]:
    persistent_chat = db.execute(
        select(AISageChat).where(AISageChat.id == _id_str(chat_id))
    ).scalar_one()
    persistent_message = (
        db.execute(
            select(AISageMessage)
            .options(selectinload(AISageMessage.evidence))
            .where(AISageMessage.id == _id_str(assistant_message_id))
        )
        .scalars()
        .unique()
        .one()
    )
    return persistent_chat, persistent_message


def execute_turn(
    db: Session,
    *,
    chat: AISageChat,
    user_message: AISageMessage,
    context_messages: list[AISageMessage],
) -> AISageTurnExecution:
    engine_query = _contextualize_query(chat.title, user_message.content, context_messages)
    prior_assistant = next((msg for msg in reversed(context_messages) if msg.role == "assistant"), None)
    prior_mode = None
    if prior_assistant and isinstance(prior_assistant.metadata_json, dict):
        prior_mode = prior_assistant.metadata_json.get("mode")

    mode = "thesis" if classify_query_as_thesis(user_message.content) or prior_mode == "thesis" else "concept"
    if mode == "thesis":
        raw_result = execute_thesis_query(engine_query, db)
    else:
        raw_result = execute_concept_query(engine_query, db)

    result = ConceptQueryOut(**raw_result.as_dict())
    assistant_text = _assistant_text_for_result(result)
    metadata = {
        "mode": result.mode or mode,
        "engine_query": engine_query,
        "context_policy": "chat title plus the last 5 completed user/assistant messages ordered by created_at then id",
        "context_message_ids": [_id_str(message.id) for message in context_messages],
        "evidence_sufficient": result.evidence_sufficient,
        "weak_evidence_note": result.weak_evidence_note,
        "follow_up_questions": result.follow_up_questions,
        "thesis_question": result.thesis_question,
        "pushback_questions": result.pushback_questions,
        "missing_information": result.missing_information,
        "key_facts": result.key_facts,
        "updated_thesis_view": result.updated_thesis_view.model_dump() if result.updated_thesis_view else None,
        "live_sources": [source.model_dump() for source in result.live_sources],
        "intent": result.intent,
        "constraints_relaxed": result.constraints_relaxed,
        "constraint_relaxation_reason": result.constraint_relaxation_reason,
    }
    return AISageTurnExecution(
        mode=result.mode or mode,
        assistant_text=assistant_text,
        result=result,
        metadata=metadata,
        evidence=_evidence_payload_for_result(result),
    )


def finalize_assistant_message(
    db: Session,
    *,
    chat: AISageChat,
    assistant_message: AISageMessage,
    turn: AISageTurnExecution,
) -> AISageMessage:
    chat, assistant_message = _load_persistent_chat_and_message(
        db,
        chat_id=_orm_id_str(chat),
        assistant_message_id=_orm_id_str(assistant_message),
    )
    now = utc_now()
    assistant_message.content = turn.assistant_text
    assistant_message.status = "completed"
    assistant_message.completed_at = now
    assistant_message.error_message = None
    base_metadata = dict(assistant_message.metadata_json or {})
    base_metadata.update(turn.metadata)
    assistant_message.metadata_json = base_metadata
    for evidence_row in list(assistant_message.evidence):
        db.delete(evidence_row)
    for payload in turn.evidence:
        assistant_message.evidence.append(AISageTurnEvidence(**payload))
    chat.updated_at = now
    db.commit()
    db.refresh(assistant_message)
    return assistant_message


def fail_assistant_message(
    db: Session,
    *,
    chat: AISageChat,
    assistant_message: AISageMessage,
    error_message: str,
) -> AISageMessage:
    chat, assistant_message = _load_persistent_chat_and_message(
        db,
        chat_id=_orm_id_str(chat),
        assistant_message_id=_orm_id_str(assistant_message),
    )
    now = utc_now()
    assistant_message.status = "failed"
    assistant_message.content = ""
    assistant_message.completed_at = now
    assistant_message.error_message = error_message
    metadata = dict(assistant_message.metadata_json or {})
    metadata["failed_at"] = now.isoformat()
    assistant_message.metadata_json = metadata
    chat.updated_at = now
    db.commit()
    db.refresh(assistant_message)
    return assistant_message


def retry_failed_message(db: Session, *, chat: AISageChat, assistant_message: AISageMessage) -> AISageMessage:
    if assistant_message.role != "assistant":
        raise HTTPException(status_code=400, detail="Only assistant messages can be retried")
    if assistant_message.status != "failed":
        raise HTTPException(status_code=400, detail="Only failed assistant messages can be retried")
    metadata = assistant_message.metadata_json or {}
    source_user_message_id = metadata.get("source_user_message_id")
    if source_user_message_id is None:
        raise HTTPException(status_code=400, detail="Retry source user message missing")
    source_user_message_id = _id_str(source_user_message_id)
    source_user = next(
        (
            message
            for message in chat.messages
            if _id_str(message.id) == source_user_message_id and message.role == "user"
        ),
        None,
    )
    if source_user is None:
        raise HTTPException(status_code=404, detail="Retry source user message not found")
    context_messages = build_context_messages(chat, before_message_id=_id_str(source_user.id))
    turn = execute_turn(db, chat=chat, user_message=source_user, context_messages=context_messages)
    return finalize_assistant_message(db, chat=chat, assistant_message=assistant_message, turn=turn)


def _assistant_text_for_result(result: ConceptQueryOut) -> str:
    if result.weak_evidence_note:
        return result.weak_evidence_note
    if result.mode == "thesis":
        lines: list[str] = []
        if result.thesis_question:
            lines.append(f"Pressure test focus: {result.thesis_question}")
        if result.critique:
            lines.append(result.critique)
        if result.updated_thesis_view and result.updated_thesis_view.weaker:
            lines.append(f"Most pressured area: {result.updated_thesis_view.weaker[0]}")
        elif result.pushback_questions:
            lines.append(f"Key pressure point: {result.pushback_questions[0]}")
        return "\n\n".join(line.strip() for line in lines if line.strip()) or "Pressure test completed."

    passages = _top_passages_for_display(
        result.best_passages,
        query=result.query,
        limit=3,
        topic_entities=_display_topic_entities(result.intent),
        ignored_terms=_display_source_author_terms(result.intent),
        prefer_focused_only=True,
    )
    if not passages:
        return "I could not ground a strong answer in the author corpus for this question."

    snippets: list[str] = []
    seen_snippets: list[str] = []
    ignored_terms = _display_source_author_terms(result.intent)
    topic_entities = _display_topic_entities(result.intent)
    for passage in passages:
        summary = _summarize_passage_for_display(
            passage,
            query=result.query,
            ignored_terms=ignored_terms,
            topic_entities=topic_entities,
        )
        if not summary:
            continue
        normalized_summary = _display_duplicate_fingerprint(summary)
        if _is_duplicate_display_text(normalized_summary, seen_snippets):
            continue
        if normalized_summary:
            seen_snippets.append(normalized_summary)
        snippets.append(summary)
    if not snippets:
        return "I could not ground a strong answer in the author corpus for this question."

    intro = _display_answer_intro(
        passages,
        query=result.query,
        topic_entities=_display_topic_entities(result.intent),
    )

    lines: list[str] = []
    if intro:
        lines.append(intro)
    lines.extend(f"- {snippet}" for snippet in snippets)
    if result.critique:
        lines.extend(["", f"Pushback: {result.critique}"])
    return "\n".join(lines).strip() or "I could not ground a strong answer in the author corpus for this question."


def _top_passages_for_display(
    passages: list[Any],
    *,
    query: str,
    limit: int,
    topic_entities: list[str] | None = None,
    ignored_terms: set[str] | None = None,
    prefer_focused_only: bool = False,
) -> list[Any]:
    ranked = sorted(
        passages,
        key=lambda passage: _display_passage_rank(
            passage,
            query=query,
            topic_entities=topic_entities,
            ignored_terms=ignored_terms,
        ),
    )
    focused = _focused_display_passages(
        ranked,
        query=query,
        topic_entities=topic_entities,
        ignored_terms=ignored_terms,
    )
    if focused:
        if prefer_focused_only:
            return _dedupe_display_passages(
                focused,
                query=query,
                limit=limit,
                topic_entities=topic_entities,
                ignored_terms=ignored_terms,
            )
        ranked = focused + [passage for passage in ranked if passage not in focused]
    return _dedupe_display_passages(
        ranked,
        query=query,
        limit=limit,
        topic_entities=topic_entities,
        ignored_terms=ignored_terms,
    )


def _dedupe_display_passages(
    passages: list[Any],
    *,
    query: str,
    limit: int,
    topic_entities: list[str] | None = None,
    ignored_terms: set[str] | None = None,
) -> list[Any]:
    selected: list[Any] = []
    seen_chunk_ids: set[str] = set()
    seen_fingerprints: list[str] = []

    for passage in passages:
        chunk_id = str(getattr(passage, "chunk_id", "") or "")
        if chunk_id and chunk_id in seen_chunk_ids:
            continue
        summary = _summarize_passage_for_display(
            passage,
            query=query,
            ignored_terms=ignored_terms,
            topic_entities=topic_entities,
        )
        fingerprint = _display_duplicate_fingerprint(summary or _display_passage_text(passage))
        if _is_duplicate_display_text(fingerprint, seen_fingerprints):
            continue
        selected.append(passage)
        if chunk_id:
            seen_chunk_ids.add(chunk_id)
        if fingerprint:
            seen_fingerprints.append(fingerprint)
        if len(selected) >= limit:
            break

    return selected


def _focused_display_passages(
    passages: list[Any],
    *,
    query: str,
    topic_entities: list[str] | None = None,
    ignored_terms: set[str] | None = None,
) -> list[Any]:
    if not passages:
        return []

    focused: list[Any] = []
    query_terms = _display_query_terms(query, ignored_terms=ignored_terms)
    for passage in passages:
        metadata = passage.metadata if isinstance(getattr(passage, "metadata", None), dict) else {}
        context_text = metadata.get("context_text") if isinstance(metadata.get("context_text"), str) else None
        normalized_text = _normalize_display_text(context_text or passage.text).lower()
        phrase_hits, token_hits = _display_topic_entity_match_counts(normalized_text, topic_entities=topic_entities)
        overlap = sum(1 for token in query_terms if token in normalized_text)
        if topic_entities:
            if phrase_hits > 0 or token_hits > 0:
                focused.append(passage)
        elif overlap > 0:
            focused.append(passage)
    if not focused:
        return []
    return focused


def _display_passage_rank(
    passage: Any,
    *,
    query: str,
    topic_entities: list[str] | None = None,
    ignored_terms: set[str] | None = None,
) -> tuple[int, int, float, float]:
    metadata = passage.metadata if isinstance(getattr(passage, "metadata", None), dict) else {}
    context_text = metadata.get("context_text") if isinstance(metadata.get("context_text"), str) else None
    normalized_text = _normalize_display_text(context_text or passage.text)
    query_terms = _display_query_terms(query, ignored_terms=ignored_terms)
    overlap = sum(1 for token in query_terms if token in normalized_text.lower())
    phrase_hits, token_hits = _display_topic_entity_match_counts(normalized_text, topic_entities=topic_entities)
    ranking_score = float(getattr(passage, "ranking_score", 0.0) or 0.0)
    similarity = float(getattr(passage, "similarity", 0.0) or 0.0)
    topic_bias = 0
    if topic_entities:
        if phrase_hits > 0:
            topic_bias += 200 + (phrase_hits * 80)
        elif token_hits > 0:
            topic_bias += 80 + (token_hits * 20)
        else:
            topic_bias -= 120
    return (-topic_bias, -overlap, -ranking_score, -similarity)


def _display_answer_intro(
    passages: list[Any],
    *,
    query: str,
    topic_entities: list[str] | None = None,
) -> str:
    author_names = [
        str(getattr(passage, "author_name", "") or "").strip()
        for passage in passages
        if str(getattr(passage, "author_name", "") or "").strip()
    ]
    author_label = author_names[0] if author_names and len(set(author_names)) == 1 else "the corpus"
    if topic_entities:
        topic_label = ", ".join(topic_entities[:2])
        return f"Grounded passages on {topic_label} from {author_label}:"
    return f"Grounded passages from {author_label}:"


def _summarize_passage_for_display(
    passage: Any,
    *,
    query: str,
    ignored_terms: set[str] | None = None,
    topic_entities: list[str] | None = None,
) -> str:
    metadata = passage.metadata if isinstance(getattr(passage, "metadata", None), dict) else {}
    context_text = metadata.get("context_text") if isinstance(metadata.get("context_text"), str) else None
    anchor_text = metadata.get("anchor_text") if isinstance(metadata.get("anchor_text"), str) else None

    normalized_context = _normalize_display_text(context_text or passage.text)
    if not normalized_context:
        return ""

    normalized_anchor = _normalize_display_text(anchor_text or passage.text)
    focused = _focused_sentence_window(
        normalized_context,
        normalized_anchor,
        query=query,
        ignored_terms=ignored_terms,
        topic_entities=topic_entities,
        max_chars=_DISPLAY_SENTENCE_MAX_CHARS,
    )
    if focused:
        return focused
    return _soft_truncate_text(normalized_context, max_chars=_DISPLAY_FALLBACK_MAX_CHARS)


def _focused_sentence_window(
    text: str,
    anchor: str,
    *,
    query: str,
    ignored_terms: set[str] | None = None,
    topic_entities: list[str] | None = None,
    max_chars: int,
) -> str:
    sentences = _split_display_sentences(text)
    if not sentences:
        return _soft_truncate_text(text, max_chars=max_chars)

    anchor_index = _find_anchor_sentence_index(
        sentences,
        anchor,
        query=query,
        ignored_terms=ignored_terms,
        topic_entities=topic_entities,
    )
    if anchor_index is None:
        return _compose_sentence_window(sentences, 0, max_chars=max_chars)
    return _compose_sentence_window(sentences, anchor_index, max_chars=max_chars)


def _split_display_sentences(text: str) -> list[str]:
    normalized = _normalize_display_text(text)
    if not normalized:
        return []
    sentences = [segment.strip() for segment in _DISPLAY_SENTENCE_SPLIT_RE.split(normalized) if segment.strip()]
    if sentences:
        return sentences
    return [normalized]


def _find_anchor_sentence_index(
    sentences: list[str],
    anchor: str,
    *,
    query: str,
    ignored_terms: set[str] | None = None,
    topic_entities: list[str] | None = None,
) -> int | None:
    normalized_anchor = _normalize_display_text(anchor)
    anchor_lower = normalized_anchor.lower()
    query_terms = _display_query_terms(query, ignored_terms=ignored_terms)
    anchor_terms = {
        token
        for token in _DISPLAY_TOKEN_RE.findall(anchor_lower)
        if len(token) >= 4 and token not in _DISPLAY_STOPWORDS
    }

    best_index: int | None = None
    best_score = -1
    for index, sentence in enumerate(sentences):
        sentence_lower = sentence.lower()
        score = 0
        phrase_hits, token_hits = _display_topic_entity_match_counts(sentence_lower, topic_entities=topic_entities)
        if topic_entities:
            score += (phrase_hits * 220) + (token_hits * 40)
        if anchor_lower and anchor_lower in sentence_lower:
            score += 30 if topic_entities else 100
        score += 5 * sum(1 for token in query_terms if token in sentence_lower)
        score += 2 * sum(1 for token in anchor_terms if token in sentence_lower)
        if score > best_score:
            best_score = score
            best_index = index

    return best_index if best_score > 0 else None


def _compose_sentence_window(sentences: list[str], anchor_index: int, *, max_chars: int) -> str:
    selected = sentences[anchor_index].strip()
    if not selected:
        return ""

    if not _looks_sentence_complete(selected) and anchor_index + 1 < len(sentences):
        combined = f"{selected} {sentences[anchor_index + 1].strip()}".strip()
        if len(combined) <= max_chars:
            selected = combined

    if anchor_index + 1 < len(sentences):
        next_sentence = sentences[anchor_index + 1].strip()
        candidate = f"{selected} {next_sentence}".strip()
        if next_sentence and len(selected) < max_chars * 0.6 and len(candidate) <= max_chars:
            selected = candidate

    if len(selected) > max_chars:
        return _soft_truncate_text(selected, max_chars=max_chars)
    return selected


def _normalize_display_text(text: str | None) -> str:
    if not text:
        return ""
    cleaned = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return _DISPLAY_WHITESPACE_RE.sub(" ", cleaned).strip()


def _display_passage_text(passage: Any) -> str:
    metadata = passage.metadata if isinstance(getattr(passage, "metadata", None), dict) else {}
    context_text = metadata.get("context_text") if isinstance(metadata.get("context_text"), str) else None
    return _normalize_display_text(context_text or getattr(passage, "text", "") or "")


def _display_duplicate_fingerprint(text: str | None) -> str:
    normalized = _normalize_display_text(text).lower()
    if not normalized:
        return ""
    return re.sub(r"[^a-z0-9\s]", " ", normalized).strip()


def _is_duplicate_display_text(candidate: str, existing_values: list[str]) -> bool:
    if not candidate:
        return False
    for existing in existing_values:
        if not existing:
            continue
        if candidate == existing:
            return True
        shorter, longer = sorted((candidate, existing), key=len)
        if len(shorter) >= _DISPLAY_DUPLICATE_MIN_CHARS and shorter in longer:
            return True
        if min(len(candidate), len(existing)) >= _DISPLAY_DUPLICATE_MIN_CHARS:
            similarity = difflib.SequenceMatcher(a=candidate, b=existing).ratio()
            if similarity >= _DISPLAY_DUPLICATE_THRESHOLD:
                return True
    return False


def _display_query_terms(query: str, *, ignored_terms: set[str] | None = None) -> set[str]:
    ignored = {token for token in (ignored_terms or set()) if token}
    return {
        token
        for token in _DISPLAY_TOKEN_RE.findall(query.lower())
        if len(token) >= 4 and token not in _DISPLAY_STOPWORDS and token not in ignored
    }


def _display_topic_entities(intent: dict[str, Any] | None) -> list[str]:
    if not isinstance(intent, dict):
        return []
    raw = intent.get("topic_entities")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _display_source_author_terms(intent: dict[str, Any] | None) -> set[str]:
    if not isinstance(intent, dict) or intent.get("query_type") != "single_author":
        return set()
    raw_names = intent.get("author_names") if isinstance(intent.get("author_names"), list) else []
    raw_ids = intent.get("author_ids") if isinstance(intent.get("author_ids"), list) else []
    terms: set[str] = set()
    for author_name in raw_names:
        for token in _DISPLAY_TOKEN_RE.findall(str(author_name).lower()):
            if len(token) >= 3:
                terms.add(token)
    for author_id in raw_ids:
        for token in _DISPLAY_TOKEN_RE.findall(str(author_id).replace("_", " ").lower()):
            if len(token) >= 3:
                terms.add(token)
    return terms


def _display_topic_entity_match_counts(text: str, *, topic_entities: list[str] | None = None) -> tuple[int, int]:
    normalized_text = _normalize_display_text(text).lower()
    phrases = [
        phrase.strip().lower()
        for phrase in (topic_entities or [])
        if isinstance(phrase, str) and phrase.strip()
    ]
    phrase_hits = sum(1 for phrase in phrases if phrase in normalized_text)
    tokens = {
        token
        for phrase in phrases
        for token in _DISPLAY_TOKEN_RE.findall(phrase)
        if len(token) >= 2
    }
    token_hits = sum(1 for token in tokens if token in normalized_text)
    return phrase_hits, token_hits


def _soft_truncate_text(text: str, *, max_chars: int) -> str:
    normalized = _normalize_display_text(text)
    if len(normalized) <= max_chars:
        return normalized

    window = normalized[: max_chars + 1]
    last_sentence_break = max(window.rfind("."), window.rfind("!"), window.rfind("?"))
    if last_sentence_break >= max_chars // 2:
        return window[: last_sentence_break + 1].strip()

    cut = window.rfind(" ")
    if cut < max_chars // 2:
        cut = max_chars
    return f"{window[:cut].rstrip()}..."


def _looks_sentence_complete(text: str) -> bool:
    stripped = text.rstrip()
    return bool(stripped) and stripped[-1] in ".!?"


def _evidence_payload_for_result(result: ConceptQueryOut) -> list[dict[str, Any]]:
    evidence_rows: list[dict[str, Any]] = []
    ignored_terms = _display_source_author_terms(result.intent)
    topic_entities = _display_topic_entities(result.intent)
    ordered_passages = _top_passages_for_display(
        result.best_passages,
        query=result.query,
        limit=min(len(result.best_passages), _DISPLAY_EVIDENCE_LIMIT),
        topic_entities=topic_entities,
        ignored_terms=ignored_terms,
    )
    for passage in ordered_passages:
        title = passage.metadata.get("title") if isinstance(passage.metadata, dict) else None
        source_url = passage.metadata.get("source_url") if isinstance(passage.metadata, dict) else None
        document_id = passage.document_id
        if document_id is None and isinstance(passage.metadata, dict):
            raw_document_id = passage.metadata.get("document_id")
            document_id = str(raw_document_id) if raw_document_id is not None else None
        snippet = _summarize_passage_for_display(
            passage,
            query=result.query,
            ignored_terms=ignored_terms,
            topic_entities=topic_entities,
        )
        if not snippet:
            snippet = (
                str(passage.metadata.get("context_text"))
                if isinstance(passage.metadata, dict) and isinstance(passage.metadata.get("context_text"), str)
                else passage.text
            )
        evidence_rows.append(
            {
                "chunk_id": passage.chunk_id,
                "document_id": document_id,
                "author_id": passage.author_id,
                "author_name": passage.author_name,
                "source_url": str(source_url) if source_url is not None else None,
                "title": str(title) if title is not None else None,
                "snippet": snippet,
                "similarity": passage.similarity,
                "ranking_score": passage.ranking_score,
                "score_type": passage.score_type,
                "metadata_json": passage.metadata,
            }
        )
    for source in result.live_sources:
        evidence_rows.append(
            {
                "chunk_id": None,
                "document_id": None,
                "author_id": None,
                "author_name": None,
                "source_url": source.url,
                "title": source.title,
                "snippet": source.snippet,
                "similarity": None,
                "ranking_score": None,
                "score_type": source.source_type,
                "metadata_json": {"source_type": source.source_type, "kind": "live_source"},
            }
        )
    return _dedupe_evidence_payloads(evidence_rows)


def _dedupe_evidence_payloads(evidence_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen_chunk_ids: set[str] = set()
    seen_live_sources: set[str] = set()
    seen_snippets: list[str] = []

    for row in evidence_rows:
        chunk_id = str(row.get("chunk_id") or "")
        if chunk_id:
            if chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk_id)

        source_url = str(row.get("source_url") or "").strip().lower()
        if not chunk_id and source_url:
            if source_url in seen_live_sources:
                continue
            seen_live_sources.add(source_url)

        snippet = str(row.get("snippet") or "")
        fingerprint = _display_duplicate_fingerprint(snippet)
        if _is_duplicate_display_text(fingerprint, seen_snippets):
            continue
        if fingerprint:
            seen_snippets.append(fingerprint)
        deduped.append(row)

    return deduped


def _title_from_prompt(prompt: str) -> str:
    compact = " ".join(prompt.split())
    if len(compact) <= 72:
        return compact
    return f"{compact[:69].rstrip()}..."


def _snippet_for_text(text: str, query_text: str) -> str:
    lowered = text.lower()
    index = lowered.find(query_text)
    if index < 0:
        return text[:140]
    start = max(0, index - 30)
    end = min(len(text), index + len(query_text) + 90)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = f"...{snippet}"
    if end < len(text):
        snippet = f"{snippet}..."
    return snippet


def _contextualize_query(chat_title: str, query: str, context_messages: list[AISageMessage]) -> str:
    if not context_messages:
        return query
    context_lines = [f"Chat title: {chat_title}"]
    for message in context_messages:
        context_lines.append(f"{message.role.title()}: {message.content}")
    context_block = "\n".join(context_lines)
    return f"{query}\n\nRecent conversation context:\n{context_block}"


def _coerce_dt(value: datetime | None) -> datetime:
    if value is None:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
