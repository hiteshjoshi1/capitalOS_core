from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = max(int(os.getenv("REALTIME_HEARTBEAT_INTERVAL_SECONDS", "20")), 5)


@dataclass
class RealtimeConnection:
    id: str
    user_id: int
    websocket: WebSocket
    topics: set[str] = field(default_factory=set)


class RealtimeService:
    def __init__(self) -> None:
        self._connections: dict[str, RealtimeConnection] = {}
        self._user_connections: dict[int, set[str]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, *, user_id: int, websocket: WebSocket) -> RealtimeConnection:
        await websocket.accept()
        connection = RealtimeConnection(id=str(uuid.uuid4()), user_id=user_id, websocket=websocket)
        async with self._lock:
            self._connections[connection.id] = connection
            self._user_connections[user_id].add(connection.id)
        log.info("Realtime websocket connected: user_id=%s connection_id=%s", user_id, connection.id)
        return connection

    async def disconnect(self, connection: RealtimeConnection) -> None:
        async with self._lock:
            self._connections.pop(connection.id, None)
            user_connections = self._user_connections.get(connection.user_id)
            if user_connections is not None:
                user_connections.discard(connection.id)
                if not user_connections:
                    self._user_connections.pop(connection.user_id, None)
        log.info("Realtime websocket disconnected: user_id=%s connection_id=%s", connection.user_id, connection.id)

    async def subscribe(self, connection: RealtimeConnection, topics: list[str]) -> list[str]:
        normalized = {topic.strip() for topic in topics if topic and topic.strip()}
        connection.topics.update(normalized)
        sorted_topics = sorted(connection.topics)
        log.info(
            "Realtime websocket subscribed: user_id=%s connection_id=%s topics=%s",
            connection.user_id,
            connection.id,
            ",".join(sorted_topics),
        )
        return sorted_topics

    async def send_heartbeat(self, connection: RealtimeConnection) -> None:
        await connection.websocket.send_json(
            {
                "type": "heartbeat",
                "interval_seconds": HEARTBEAT_INTERVAL_SECONDS,
            }
        )

    async def publish(self, *, user_id: int, topic: str, event: dict[str, Any]) -> None:
        async with self._lock:
            recipients = [
                connection
                for connection_id in self._user_connections.get(user_id, set())
                if (connection := self._connections.get(connection_id)) is not None
                and topic in connection.topics
            ]

        if not recipients:
            log.info("Realtime publish skipped: user_id=%s topic=%s recipients=0", user_id, topic)
            return

        log.info("Realtime publish: user_id=%s topic=%s recipients=%s", user_id, topic, len(recipients))
        failed_connections: list[RealtimeConnection] = []
        for connection in recipients:
            try:
                await connection.websocket.send_json({"type": "event", **event})
            except (WebSocketDisconnect, RuntimeError):
                failed_connections.append(connection)
                log.exception(
                    "Realtime delivery failed: user_id=%s topic=%s connection_id=%s",
                    user_id,
                    topic,
                    connection.id,
                )

        for connection in failed_connections:
            await self.disconnect(connection)

    def publish_sync(self, *, user_id: int, topic: str, event: dict[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.publish(user_id=user_id, topic=topic, event=event))
            return
        loop.create_task(self.publish(user_id=user_id, topic=topic, event=event))


realtime_service = RealtimeService()
