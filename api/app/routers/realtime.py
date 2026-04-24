from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, WebSocket
from starlette.websockets import WebSocketDisconnect

from app.auth_context import resolve_current_user_from_access_token
from app.db.session import SessionLocal
from app.services.realtime import HEARTBEAT_INTERVAL_SECONDS, realtime_service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/realtime", tags=["realtime"])


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

    connection = await realtime_service.connect(user_id=current_user.id, websocket=websocket)
    try:
        initial_topics = _parse_topics(websocket.query_params.get("topics"))
        if initial_topics:
            topics = await realtime_service.subscribe(connection, initial_topics)
            await websocket.send_json({"type": "subscribed", "topics": topics})

        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=HEARTBEAT_INTERVAL_SECONDS,
                )
            except asyncio.TimeoutError:
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
