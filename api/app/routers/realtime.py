from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, HTTPException, WebSocket
from sqlalchemy import text
from starlette.websockets import WebSocketDisconnect

from app.auth_context import resolve_current_user_from_access_token
from app.db.session import SessionLocal
from app.services.auth import decode_access_token
from app.services.realtime import HEARTBEAT_INTERVAL_SECONDS, realtime_service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/realtime", tags=["realtime"])


# The close code the web client acts on (#364): refresh the login, then reconnect (or stop
# when the session has ended). Same code as a bad token at connect.
CLOSE_SIGN_IN_AGAIN = 4401


def _token_expiry(access_token: str | None) -> float | None:
    """The access token's exp (epoch seconds), or None when there is none to enforce (bypass)."""
    if not access_token:
        return None
    try:
        exp = decode_access_token(access_token).get("exp")
    except jwt.PyJWTError:
        return None
    return float(exp) if isinstance(exp, (int, float)) else None


def _still_signed_in(user_id: int) -> bool:
    """Whether the user is active and still has a live session (#364): signing out everywhere,
    a password change or a refresh-token replay ends them all, and the socket must follow."""
    db = SessionLocal()
    try:
        row = db.execute(
            text(
                """
                SELECT COALESCE(u.is_active, TRUE) AS is_active,
                       EXISTS (
                           SELECT 1 FROM auth_sessions s
                           WHERE s.user_id = u.id AND s.revoked_at IS NULL AND s.expires_at > :now
                       ) AS has_session
                FROM users u WHERE u.id = :user_id
                """
            ),
            {"user_id": user_id, "now": datetime.now(tz=timezone.utc)},
        ).mappings().one_or_none()
    finally:
        db.close()
    return row is not None and bool(row["is_active"]) and bool(row["has_session"])


def _parse_topics(raw_topics: str | None) -> list[str]:
    if not raw_topics:
        return []
    return [topic.strip() for topic in raw_topics.split(",") if topic.strip()]


@router.websocket("/ws")
async def websocket_updates(websocket: WebSocket) -> None:
    access_token = websocket.query_params.get("access_token")
    db = SessionLocal()
    try:
        current_user = resolve_current_user_from_access_token(db, access_token)
    except HTTPException as exc:
        await websocket.close(code=4401, reason=str(exc.detail))
        db.close()
        return
    db.close()
    # Bypass (tests/dev) has no token to expire and no sessions to check.
    expires_at = _token_expiry(access_token)

    connection = await realtime_service.connect(user_id=current_user.id, websocket=websocket)
    try:
        initial_topics = _parse_topics(websocket.query_params.get("topics"))
        if initial_topics:
            topics = await realtime_service.subscribe(connection, initial_topics)
            await websocket.send_json({"type": "subscribed", "topics": topics})

        while True:
            timeout = float(HEARTBEAT_INTERVAL_SECONDS)
            if expires_at is not None:
                timeout = max(min(timeout, expires_at - time.time()), 0.0)
            try:
                message = await asyncio.wait_for(websocket.receive_json(), timeout=timeout)
            except asyncio.TimeoutError:
                # #364: the login is re-checked on every tick, not only at connect.
                if expires_at is not None and time.time() >= expires_at:
                    await websocket.close(code=CLOSE_SIGN_IN_AGAIN, reason="access token expired")
                    return
                if expires_at is not None and not await asyncio.to_thread(_still_signed_in, current_user.id):
                    await websocket.close(code=CLOSE_SIGN_IN_AGAIN, reason="session ended")
                    return
                await realtime_service.send_heartbeat(connection)
                continue

            action = str(message.get("action", "")).strip().lower()
            if action == "subscribe":
                topics = await realtime_service.subscribe(connection, message.get("topics", []))
                await websocket.send_json({"type": "subscribed", "topics": topics})
                continue
            if action == "ping":
                await realtime_service.send_heartbeat(connection)
                continue

            await websocket.send_json(
                {
                    "type": "error",
                    "message": "Unsupported realtime action",
                }
            )
    except WebSocketDisconnect:
        log.info(
            "Realtime websocket disconnect received: user_id=%s connection_id=%s",
            current_user.id,
            connection.id,
        )
    finally:
        await realtime_service.disconnect(connection)
