"""Cross-process message bus for routing custom-block events.

In a multi-worker deployment, the WS connection for session X lives in one
uvicorn worker while the HTTP request that calls ``push_block`` may land on a
different worker. In-process registries don't span workers, so we publish on
a pub/sub bus and every worker subscribes; whichever worker holds the right
WS / handler picks the message up.

Topics
------

- ``atria:block:<session_id>`` — server→iframe (push / update / remove). Payload
  is the WS envelope the iframe expects: ``{"type": "...", "data": {...}}``.
- ``atria:event:<block_id>`` — iframe→Python ``on_event``. Payload is
  ``{"name": str, "data": Any}``.

Implementations
---------------

- :class:`InMemoryBus`: single-process default; ``publish`` synchronously
  dispatches to the registered handler. Zero-dep, ideal for dev.
- :class:`RedisBus`: ``psubscribe("atria:*")``; the canonical
  ``get_message`` loop from the redis-py asyncio examples.
"""

from __future__ import annotations

import abc
import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

Handler = Callable[[str, Dict[str, Any]], Awaitable[None]]


class MessageBus(abc.ABC):
    """A topic-keyed pub/sub channel."""

    @abc.abstractmethod
    async def start(self) -> None: ...

    @abc.abstractmethod
    async def stop(self) -> None: ...

    @abc.abstractmethod
    async def publish(self, topic: str, payload: Dict[str, Any]) -> None: ...

    @abc.abstractmethod
    def subscribe(self, handler: Handler) -> None:
        """Register a handler called for every received message on ``atria:*``.

        Only one handler is supported; subsequent calls replace.
        """


class InMemoryBus(MessageBus):
    """Single-process fallback: publish dispatches directly to the handler."""

    def __init__(self) -> None:
        self._handler: Optional[Handler] = None

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        self._handler = None

    async def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        if self._handler is None:
            return
        try:
            await self._handler(topic, payload)
        except Exception:  # noqa: BLE001 — never let a handler crash the publisher
            logger.exception("in_memory bus handler raised for topic %s", topic)

    def subscribe(self, handler: Handler) -> None:
        self._handler = handler


class RedisBus(MessageBus):
    """Redis-backed pub/sub using ``psubscribe('atria:*')``."""

    _PATTERN = "atria:*"

    def __init__(self, redis_url: str) -> None:
        self._url = redis_url
        self._handler: Optional[Handler] = None
        self._client: Any = None  # redis.asyncio.Redis — lazy import
        self._pubsub: Any = None
        self._task: Optional[asyncio.Task[None]] = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        try:
            import redis.asyncio as redis  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "redis package not installed; pip install redis>=5 to use RedisBus"
            ) from exc

        self._client = redis.from_url(self._url, decode_responses=True)
        # Probe connectivity early so a misconfigured URL fails loud at startup.
        try:
            await self._client.ping()
        except Exception:
            await self._client.close()
            self._client = None
            raise

        self._pubsub = self._client.pubsub()
        await self._pubsub.psubscribe(self._PATTERN)
        self._task = asyncio.create_task(self._reader_loop(), name="atria-bus-reader")
        logger.info("RedisBus started on %s pattern %s", self._url, self._PATTERN)

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        if self._pubsub is not None:
            try:
                await self._pubsub.punsubscribe(self._PATTERN)
                await self._pubsub.aclose()
            except Exception:  # noqa: BLE001
                logger.exception("RedisBus pubsub close failed")
            self._pubsub = None
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # noqa: BLE001
                logger.exception("RedisBus client close failed")
            self._client = None

    async def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        if self._client is None:
            logger.warning("RedisBus.publish before start(); dropping %s", topic)
            return
        try:
            await self._client.publish(topic, json.dumps(payload))
        except Exception:  # noqa: BLE001
            logger.exception("RedisBus.publish failed for topic %s", topic)

    def subscribe(self, handler: Handler) -> None:
        self._handler = handler

    async def _reader_loop(self) -> None:
        """Pump messages from the redis pubsub channel to the handler."""
        assert self._pubsub is not None
        while not self._stopping.is_set():
            try:
                msg = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("RedisBus reader get_message raised; retrying")
                await asyncio.sleep(1.0)
                continue
            if msg is None:
                continue
            topic = msg.get("channel")
            data = msg.get("data")
            if not topic or data is None:
                continue
            try:
                payload = json.loads(data)
            except (TypeError, ValueError):
                logger.warning("RedisBus dropped malformed payload on %s", topic)
                continue
            if self._handler is None:
                continue
            try:
                await self._handler(topic, payload)
            except Exception:  # noqa: BLE001
                logger.exception("RedisBus handler raised for topic %s", topic)


def make_bus(kind: str, redis_url: str) -> MessageBus:
    """Factory: returns the bus implementation matching ``kind``."""
    if kind == "redis":
        return RedisBus(redis_url)
    if kind == "in_memory":
        return InMemoryBus()
    raise ValueError(f"unknown bus.kind: {kind!r}")


# ── Process-global accessor ──────────────────────────────────────────────────

_BUS: Optional[MessageBus] = None


def set_bus(bus: Optional[MessageBus]) -> None:
    global _BUS
    _BUS = bus


def get_bus() -> Optional[MessageBus]:
    """Return the active bus, or ``None`` if not started yet."""
    return _BUS
