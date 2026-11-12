"""Real-time WebSocket streamer for Task execution turns (Task 2.3 / F01.4 / F03.2)."""

from __future__ import annotations

import asyncio
import secrets
from typing import Any, Iterable, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.config import get_settings
from app.db.models import TurnLog
from app.db.session import init_db
from app.orchestrator.dispatcher import mask_secrets

router = APIRouter(tags=["websocket"])


class TaskWebSocketManager:
    """Manages active per-task WebSocket connections and broadcasts turn events safely."""

    def __init__(self, extra_secrets: Optional[Iterable[str]] = None) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._extra_secrets = [str(s) for s in (extra_secrets or ()) if s]

    async def register(self, task_id: str, websocket: WebSocket) -> None:
        """Register an already-accepted WebSocket connection for task_id."""
        async with self._lock:
            self._connections.setdefault(task_id, set()).add(websocket)

    async def connect(self, task_id: str, websocket: WebSocket) -> None:
        """Accept and register a WebSocket connection for task_id."""
        await websocket.accept()
        await self.register(task_id, websocket)

    async def disconnect(self, task_id: str, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from task_id safely."""
        async with self._lock:
            conns = self._connections.get(task_id)
            if not conns:
                return
            conns.discard(websocket)
            if not conns:
                self._connections.pop(task_id, None)

    def active_count(self, task_id: Optional[str] = None) -> int:
        """Return number of active connections globally or for a specific task_id."""
        if task_id is not None:
            return len(self._connections.get(task_id, set()))
        return sum(len(conns) for conns in self._connections.values())

    async def broadcast(self, task_id: str, event: dict[str, Any]) -> None:
        """Broadcast a secret-masked JSON event to all clients subscribed to task_id."""
        async with self._lock:
            targets = list(self._connections.get(task_id, set()))

        if not targets:
            return

        safe_event = mask_secrets(event, extra_secrets=self._extra_secrets)
        dead_sockets: list[WebSocket] = []

        for ws in targets:
            try:
                await ws.send_json(safe_event)
            except Exception:
                dead_sockets.append(ws)

        if dead_sockets:
            async with self._lock:
                conns = self._connections.get(task_id)
                if conns:
                    for dead in dead_sockets:
                        conns.discard(dead)
                    if not conns:
                        self._connections.pop(task_id, None)


# Fallback module-level manager if app.state.ws_manager is not configured
ws_manager = TaskWebSocketManager()


def _get_manager(websocket: WebSocket) -> TaskWebSocketManager:
    manager = getattr(websocket.app.state, "ws_manager", None)
    return manager if manager is not None else ws_manager


def _extract_ws_token(websocket: WebSocket) -> Optional[str]:
    header_token = websocket.headers.get("X-Local-Auth-Token")
    if header_token:
        return header_token
    query_token = websocket.query_params.get("token")
    if query_token:
        return query_token
    return None


def _is_valid_token(provided: Optional[str], expected: str) -> bool:
    if not provided or not expected:
        return False
    return secrets.compare_digest(
        provided.encode("utf-8"),
        expected.encode("utf-8"),
    )


def _load_recent_turns(
    websocket: WebSocket,
    task_id: str,
    limit: int = 20,
    extra_secrets: Optional[Iterable[str]] = None,
) -> list[dict[str, Any]]:
    factory = getattr(websocket.app.state, "session_factory", None)
    if factory is None:
        settings = getattr(websocket.app.state, "settings", None) or get_settings()
        factory = init_db(settings.resolved_db_path, cache=True)

    try:
        with factory() as session:
            rows = (
                session.query(TurnLog)
                .filter(TurnLog.task_id == task_id)
                .order_by(TurnLog.turn_number.desc(), TurnLog.created_at.desc())
                .limit(limit)
                .all()
            )
            rows = list(reversed(rows))
            return [
                mask_secrets(
                    {
                        "id": r.id,
                        "task_id": r.task_id,
                        "subtask_id": r.subtask_id,
                        "agent_id": r.agent_id,
                        "turn_number": r.turn_number,
                        "action": r.action,
                        "tool": r.tool,
                        "input_payload": r.input_payload,
                        "output_payload": r.output_payload,
                        "duration_ms": r.duration_ms,
                        "tokens": r.tokens,
                        "status": r.status,
                        "error_message": r.error_message,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    },
                    extra_secrets=extra_secrets,
                )
                for r in rows
            ]
    except Exception:
        return []


@router.websocket("/ws/tasks/{task_id}")
async def task_events_websocket(websocket: WebSocket, task_id: str) -> None:
    """Stream real-time turn and task status events for task_id over WebSocket."""
    settings = getattr(websocket.app.state, "settings", None) or get_settings()
    provided_token = _extract_ws_token(websocket)

    if not _is_valid_token(provided_token, settings.local_auth_token):
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Invalid or missing local auth token",
        )
        return

    manager = _get_manager(websocket)
    await websocket.accept()

    try:
        recent_turns = _load_recent_turns(
            websocket,
            task_id,
            extra_secrets=[settings.local_auth_token],
        )
        await websocket.send_json(
            {
                "event": "connected",
                "task_id": task_id,
                "recent_turns": recent_turns,
            }
        )
        # Register after sending the initial 'connected' frame so live broadcasts
        # cannot race ahead of it.
        await manager.register(task_id, websocket)

        while True:
            msg = await websocket.receive_text()
            if msg.strip().lower() == "ping":
                await websocket.send_json({"event": "pong", "task_id": task_id})
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(task_id, websocket)
