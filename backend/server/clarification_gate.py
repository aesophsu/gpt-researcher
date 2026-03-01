import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass
class ClarificationWaiter:
    future: asyncio.Future
    created_at: float


class ClarificationGateManager:
    """Manages per-session clarification waiters for blocking research gates."""

    def __init__(self) -> None:
        self._waiters: dict[tuple[str, str], ClarificationWaiter] = {}
        self._lock = asyncio.Lock()

    async def register(self, session_id: str, request_id: str) -> asyncio.Future:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        key = (session_id, request_id)
        async with self._lock:
            self._waiters[key] = ClarificationWaiter(
                future=future,
                created_at=loop.time(),
            )
        return future

    async def resolve(self, session_id: str, request_id: str, payload: dict[str, Any]) -> bool:
        key = (session_id, request_id)
        async with self._lock:
            waiter = self._waiters.get(key)
            if waiter is None:
                return False
            if not waiter.future.done():
                waiter.future.set_result(payload)
            return True

    async def unregister(self, session_id: str, request_id: str) -> None:
        key = (session_id, request_id)
        async with self._lock:
            self._waiters.pop(key, None)

    async def cleanup_session(self, session_id: str) -> None:
        async with self._lock:
            keys = [key for key in self._waiters if key[0] == session_id]
            for key in keys:
                waiter = self._waiters.pop(key, None)
                if waiter and not waiter.future.done():
                    waiter.future.cancel()


clarification_gate_manager = ClarificationGateManager()
