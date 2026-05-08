"""
AI Sage API router — legacy query endpoint plus persistent chat resources.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, require_current_user
from app.db.session import SessionLocal, get_db
from app.models.ai_sage_chat import AISageChat, AISageMessage
from app.rag.company_thesis_mode import ThesisQueryResult, classify_query_as_thesis, execute_thesis_query
from app.rag.concept_mode import ConceptQueryResult, execute_concept_query
from app.schemas.ai_sage import (
    AISageChatCreateIn,
    AISageChatDetailOut,
    AISageChatListOut,
    AISageChatMessageCreateIn,
    AISageChatMessageEvidenceOut,
    AISageChatMessageOut,
    AISageChatSearchOut,
    AISageChatSearchResultOut,
    AISageChatSummaryOut,
    AISageChatTurnOut,
    AISageChatUpdateIn,
    ConceptQueryIn,
    ConceptQueryOut,
    UpdatedThesisViewOut,
)
from app.services.ai_sage import (
    create_assistant_placeholder,
    create_chat,
    create_user_message,
    delete_chat,
    execute_turn,
    fail_assistant_message,
    finalize_assistant_message,
    get_chat_or_404,
    list_chats,
    prune_expired_ai_sage_chats,
    rename_chat,
    retry_failed_message,
    search_chats,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/ai-sage", tags=["ai-sage"])


def _id_str(value: Any) -> str:
    return str(value)


@router.post("/query", response_model=ConceptQueryOut)
def concept_query(
    body: ConceptQueryIn,
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(require_current_user),
) -> ConceptQueryOut:
    if classify_query_as_thesis(body.query):
        result: ThesisQueryResult = execute_thesis_query(
            body.query,
            db,
            top_k_chunks=body.top_k,
        )
        payload = result.as_dict()
        if payload.get("updated_thesis_view"):
            payload["updated_thesis_view"] = UpdatedThesisViewOut(**payload["updated_thesis_view"])
        return ConceptQueryOut(**payload)

    concept_result: ConceptQueryResult = execute_concept_query(
        body.query,
        db,
        top_k_chunks=body.top_k,
    )
    return ConceptQueryOut(**concept_result.as_dict())


@router.get("/chats", response_model=AISageChatListOut)
def get_chats(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
) -> AISageChatListOut:
    items = list_chats(db, current_user.id, limit=limit, offset=offset)
    total = db.execute(select(AISageChat).where(AISageChat.owner_user_id == current_user.id)).scalars().unique().all()
    return AISageChatListOut(
        items=[_chat_summary(chat) for chat in items],
        total=len(total),
        limit=limit,
        offset=offset,
    )


@router.get("/chats/search", response_model=AISageChatSearchOut)
def search_chat_history(
    query: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
) -> AISageChatSearchOut:
    prune_expired_ai_sage_chats(db, owner_user_id=current_user.id)
    results = search_chats(db, current_user.id, query, limit=limit)
    return AISageChatSearchOut(
        items=[
            AISageChatSearchResultOut(
                chat_id=_id_str(chat.id),
                title=chat.title,
                snippet=snippet,
                updated_at=chat.updated_at,
            )
            for chat, snippet in results
        ],
        total=len(results),
    )


@router.post("/chats", response_model=AISageChatDetailOut)
def create_chat_endpoint(
    body: AISageChatCreateIn,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
) -> AISageChatDetailOut:
    prune_expired_ai_sage_chats(db, owner_user_id=current_user.id)
    chat = create_chat(db, current_user.id, body.title)
    return _chat_detail(get_chat_or_404(db, current_user.id, _id_str(chat.id)))


@router.get("/chats/{chat_id}", response_model=AISageChatDetailOut)
def get_chat_detail(
    chat_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
) -> AISageChatDetailOut:
    return _chat_detail(get_chat_or_404(db, current_user.id, chat_id))


@router.patch("/chats/{chat_id}", response_model=AISageChatDetailOut)
def update_chat(
    chat_id: str,
    body: AISageChatUpdateIn,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
) -> AISageChatDetailOut:
    chat = get_chat_or_404(db, current_user.id, chat_id)
    rename_chat(chat, title=body.title, pinned=body.pinned)
    db.commit()
    db.refresh(chat)
    return _chat_detail(get_chat_or_404(db, current_user.id, _id_str(chat.id)))


@router.delete("/chats/{chat_id}")
def remove_chat(
    chat_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
) -> dict[str, str]:
    chat = get_chat_or_404(db, current_user.id, chat_id)
    delete_chat(db, chat)
    return {"status": "deleted"}


@router.post("/chats/{chat_id}/messages", response_model=AISageChatTurnOut)
def add_chat_message(
    chat_id: str,
    body: AISageChatMessageCreateIn,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
) -> AISageChatTurnOut:
    chat = get_chat_or_404(db, current_user.id, chat_id)
    user_message = create_user_message(db, chat, body.content.strip())
    assistant_message = create_assistant_placeholder(db, chat, _id_str(user_message.id))

    try:
        turn = execute_turn(db, chat=chat, user_message=user_message, context_messages=_context_messages(chat, before_id=_id_str(user_message.id)))
        assistant_message = finalize_assistant_message(db, chat=chat, assistant_message=assistant_message, turn=turn)
    except Exception as exc:
        log.exception("AI Sage turn failed for chat_id=%s", chat.id)
        assistant_message = fail_assistant_message(db, chat=chat, assistant_message=assistant_message, error_message=str(exc))

    fresh_chat = get_chat_or_404(db, current_user.id, _id_str(chat.id))
    user_message = _find_message(fresh_chat, _id_str(user_message.id))
    assistant_message = _find_message(fresh_chat, _id_str(assistant_message.id))
    return AISageChatTurnOut(
        chat=_chat_detail(fresh_chat),
        user_message=_message_out(user_message),
        assistant_message=_message_out(assistant_message),
    )


@router.post("/chats/{chat_id}/messages/stream")
def stream_chat_message(
    chat_id: str,
    body: AISageChatMessageCreateIn,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
) -> StreamingResponse:
    chat = get_chat_or_404(db, current_user.id, chat_id)
    user_message = create_user_message(db, chat, body.content.strip())
    assistant_message = create_assistant_placeholder(db, chat, _id_str(user_message.id))
    chat_id_str = _id_str(chat.id)
    current_user_id = current_user.id
    user_message_id = _id_str(user_message.id)
    assistant_message_id = _id_str(assistant_message.id)
    ack_user_message = _message_out(user_message, include_evidence=False).model_dump()

    def event_stream():
        yield _sse(
            "ack",
            {
                "chat_id": chat_id_str,
                "user_message": ack_user_message,
                "assistant_message_id": assistant_message_id,
            },
        )
        stream_db = SessionLocal()
        try:
            stream_chat = get_chat_or_404(stream_db, current_user_id, chat_id_str)
            stream_user_message = _find_message(stream_chat, user_message_id)
            stream_assistant_message = _find_message(stream_chat, assistant_message_id)
            stream_context_messages = _context_messages(stream_chat, before_id=user_message_id)
            turn = execute_turn(
                stream_db,
                chat=stream_chat,
                user_message=stream_user_message,
                context_messages=stream_context_messages,
            )
            for delta in _chunk_text(turn.assistant_text):
                yield _sse("delta", {"assistant_message_id": assistant_message_id, "delta": delta})
                time.sleep(0.002)
            finalize_assistant_message(
                stream_db,
                chat=stream_chat,
                assistant_message=stream_assistant_message,
                turn=turn,
            )
            fresh_chat = get_chat_or_404(stream_db, current_user_id, chat_id_str)
            yield _sse(
                "done",
                {
                    "chat": _chat_detail(fresh_chat).model_dump(),
                    "user_message": _message_out(_find_message(fresh_chat, user_message_id)).model_dump(),
                    "assistant_message": _message_out(_find_message(fresh_chat, assistant_message_id)).model_dump(),
                },
            )
        except Exception as exc:
            log.exception("AI Sage streaming turn failed for chat_id=%s", chat.id)
            stream_chat = get_chat_or_404(stream_db, current_user_id, chat_id_str)
            stream_assistant_message = _find_message(stream_chat, assistant_message_id)
            fail_assistant_message(
                stream_db,
                chat=stream_chat,
                assistant_message=stream_assistant_message,
                error_message=str(exc),
            )
            fresh_chat = get_chat_or_404(stream_db, current_user_id, chat_id_str)
            yield _sse(
                "error",
                {
                    "assistant_message": _message_out(_find_message(fresh_chat, assistant_message_id)).model_dump(),
                    "error": str(exc),
                },
            )
        finally:
            stream_db.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/chats/{chat_id}/messages/{message_id}/retry", response_model=AISageChatTurnOut)
def retry_message(
    chat_id: str,
    message_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
) -> AISageChatTurnOut:
    chat = get_chat_or_404(db, current_user.id, chat_id)
    assistant_message = _find_message(chat, message_id)
    assistant_message = retry_failed_message(db, chat=chat, assistant_message=assistant_message)
    fresh_chat = get_chat_or_404(db, current_user.id, _id_str(chat.id))
    final_assistant = _find_message(fresh_chat, _id_str(assistant_message.id))
    source_user_message_id = (final_assistant.metadata_json or {}).get("source_user_message_id")
    if source_user_message_id is None:
        raise ValueError("Missing retry source user message id after retry")
    user_message = _find_message(fresh_chat, _id_str(source_user_message_id))
    return AISageChatTurnOut(
        chat=_chat_detail(fresh_chat),
        user_message=_message_out(user_message),
        assistant_message=_message_out(final_assistant),
    )


def _chat_summary(chat: AISageChat) -> AISageChatSummaryOut:
    messages = _sorted_messages(chat)
    latest = messages[-1] if messages else None
    return AISageChatSummaryOut(
        id=_id_str(chat.id),
        title=chat.title,
        preview=(latest.content[:140] if latest and latest.content else None),
        status=_chat_status(messages),
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        last_activity_at=chat.last_activity_at,
        pinned_at=chat.pinned_at,
    )


def _chat_detail(chat: AISageChat) -> AISageChatDetailOut:
    return AISageChatDetailOut(
        id=_id_str(chat.id),
        title=chat.title,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        last_activity_at=chat.last_activity_at,
        pinned_at=chat.pinned_at,
        metadata_json=chat.metadata_json,
        messages=[_message_out(message) for message in _sorted_messages(chat)],
    )


def _message_out(message: AISageMessage, *, include_evidence: bool = True) -> AISageChatMessageOut:
    return AISageChatMessageOut(
        id=_id_str(message.id),
        role=message.role,
        content=message.content,
        status=message.status,
        created_at=message.created_at,
        completed_at=message.completed_at,
        error_message=message.error_message,
        metadata_json=message.metadata_json,
        evidence=[] if not include_evidence else [
            AISageChatMessageEvidenceOut(
                id=_id_str(evidence.id),
                chunk_id=evidence.chunk_id,
                document_id=evidence.document_id,
                author_id=evidence.author_id,
                author_name=evidence.author_name,
                source_url=evidence.source_url,
                title=evidence.title,
                snippet=evidence.snippet,
                similarity=evidence.similarity,
                ranking_score=evidence.ranking_score,
                score_type=evidence.score_type,
                metadata_json=evidence.metadata_json,
            )
            for evidence in sorted(message.evidence, key=lambda row: row.id)
        ],
    )


def _chat_status(messages: list[AISageMessage]) -> str:
    if not messages:
        return "draft"
    latest = messages[-1]
    if latest.status == "failed":
        return "failed"
    if latest.role == "assistant" and latest.status == "completed":
        return "answered"
    return "draft"


def _sorted_messages(chat: AISageChat) -> list[AISageMessage]:
    return sorted(chat.messages, key=lambda message: (message.created_at, message.id))


def _context_messages(chat: AISageChat, *, before_id: str) -> list[AISageMessage]:
    messages: list[AISageMessage] = []
    for message in _sorted_messages(chat):
        if _id_str(message.id) == _id_str(before_id):
            break
        if message.role not in {"user", "assistant"} or message.status != "completed":
            continue
        messages.append(message)
    return messages[-5:]


def _find_message(chat: AISageChat, message_id: str) -> AISageMessage:
    for message in chat.messages:
        if _id_str(message.id) == _id_str(message_id):
            return message
    raise KeyError(f"AI Sage message not found: {message_id}")


def _chunk_text(text: str) -> list[str]:
    if not text:
        return [""]
    size = 48
    return [text[index : index + size] for index in range(0, len(text), size)]


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
