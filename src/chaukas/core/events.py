"""Typed publish/subscribe event bus.

Producers (audio capture, ASR worker, LLM worker, context monitor) publish immutable
events; consumers subscribe by type. A handler subscribed to a class also receives
instances of its subclasses. Handlers are resolved along the MRO once per concrete event
type and cached, so dispatch is a dictionary lookup after the first event of each type.
Within one delivery, handlers for the most specific class run first, each class's
handlers in subscription order.

Two implementations share the subscription logic:

* ``SyncEventBus`` delivers on the publisher's thread, deterministically. Replay,
  evaluation and tests use it.
* ``ThreadedEventBus`` accepts events from any thread and delivers them on a single
  dispatcher thread, in publish order. Every subscriber runs on that one thread, so
  engine state needs no locks (actor style). The queue is bounded: a producer that
  outruns the consumer waits briefly, then the event is dropped and counted instead of
  stalling real-time audio indefinitely.

A handler that raises is logged and isolated; the other handlers still get the event.
"""

from __future__ import annotations

import logging
import queue
import threading
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable
from typing import Any, Final, Self, TypeVar

from chaukas.core.errors import BusClosedError

E = TypeVar("E")
Handler = Callable[[Any], None]

logger = logging.getLogger(__name__)


class Subscription:
    """Returned by ``EventBus.subscribe``. Call ``cancel()`` or use it as a context manager."""

    __slots__ = ("_active", "_bus", "_event_type", "_handler")

    def __init__(self, bus: EventBus, event_type: type[Any], handler: Handler) -> None:
        self._bus = bus
        self._event_type = event_type
        self._handler = handler
        self._active = True

    @property
    def active(self) -> bool:
        return self._active

    def cancel(self) -> None:
        """Stop receiving events. Calling it twice is harmless."""
        if self._active:
            self._active = False
            self._bus._remove(self._event_type, self._handler)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.cancel()


class EventBus(ABC):
    """Subscription registry and dispatch shared by both bus implementations."""

    def __init__(self) -> None:
        self._registry_lock = threading.Lock()
        self._handlers: dict[type[Any], list[Handler]] = {}
        self._resolved: dict[type[Any], tuple[Handler, ...]] = {}
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> Subscription:
        """Deliver events of ``event_type`` (and its subclasses) to ``handler``."""
        with self._registry_lock:
            self._handlers.setdefault(event_type, []).append(handler)
            self._resolved.clear()
        return Subscription(self, event_type, handler)

    @abstractmethod
    def publish(self, event: object) -> None:
        """Send ``event`` to every matching subscriber."""

    @abstractmethod
    def close(self) -> None:
        """Stop accepting events."""

    def _remove(self, event_type: type[Any], handler: Handler) -> None:
        with self._registry_lock:
            handlers = self._handlers.get(event_type)
            if handlers is None or handler not in handlers:
                return
            handlers.remove(handler)
            if not handlers:
                del self._handlers[event_type]
            self._resolved.clear()

    def _handlers_for(self, event_type: type[Any]) -> tuple[Handler, ...]:
        with self._registry_lock:
            handlers = self._resolved.get(event_type)
            if handlers is None:
                handlers = tuple(
                    handler for cls in event_type.__mro__ for handler in self._handlers.get(cls, ())
                )
                self._resolved[event_type] = handlers
            return handlers

    def _deliver(self, event: object) -> None:
        for handler in self._handlers_for(type(event)):
            try:
                handler(event)
            except Exception:
                logger.exception("event handler %r failed on %s", handler, type(event).__name__)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class SyncEventBus(EventBus):
    """Delivers events on the publisher's thread. Deterministic; use from one thread only.

    An event published from inside a handler is queued and delivered after the current
    event's handlers finish (breadth-first). Handlers never re-enter one another, and
    delivery order always equals publish order.
    """

    def __init__(self) -> None:
        super().__init__()
        self._pending: deque[object] = deque()
        self._delivering = False

    def publish(self, event: object) -> None:
        if self._closed:
            raise BusClosedError("publish on a closed bus")
        self._pending.append(event)
        if self._delivering:
            return
        self._delivering = True
        try:
            while self._pending:
                self._deliver(self._pending.popleft())
        finally:
            self._delivering = False

    def close(self) -> None:
        self._closed = True


_STOP: Final = object()


class _FlushMarker:
    __slots__ = ("done",)

    def __init__(self) -> None:
        self.done = threading.Event()


class ThreadedEventBus(EventBus):
    """Queues events from any thread; one dispatcher thread delivers them in publish order.

    Events published before ``start()`` wait in the queue. Events published concurrently
    with ``close()`` may be rejected.
    """

    def __init__(
        self,
        *,
        maxsize: int = 10_000,
        publish_timeout: float = 1.0,
        name: str = "chaukas-event-bus",
    ) -> None:
        super().__init__()
        if maxsize <= 0:
            raise ValueError(f"maxsize must be positive, got {maxsize}")
        if publish_timeout < 0:
            raise ValueError(f"publish_timeout must be non-negative, got {publish_timeout}")
        self._queue: queue.Queue[object] = queue.Queue(maxsize=maxsize)
        self._publish_timeout = publish_timeout
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._state_lock = threading.Lock()
        self._started = False
        self._dropped = 0

    @property
    def dropped(self) -> int:
        """Events discarded because the queue stayed full for ``publish_timeout``."""
        return self._dropped

    def start(self) -> None:
        """Start the dispatcher thread. Calling it again is harmless."""
        with self._state_lock:
            if self._closed:
                raise BusClosedError("cannot start a closed bus")
            if not self._started:
                self._thread.start()
                self._started = True

    def publish(self, event: object) -> None:
        if self._closed:
            raise BusClosedError("publish on a closed bus")
        try:
            self._queue.put(event, timeout=self._publish_timeout)
        except queue.Full:
            with self._state_lock:
                self._dropped += 1
            logger.warning("event bus full; dropped %s", type(event).__name__)

    def flush(self, timeout: float | None = None) -> bool:
        """Wait until every event published before this call has been delivered.

        Returns False on timeout. Must not be called from a handler (it would deadlock).
        """
        if not self._started:
            raise RuntimeError("flush() needs a started bus")
        if threading.current_thread() is self._thread:
            raise RuntimeError("flush() called from a handler would deadlock")
        marker = _FlushMarker()
        try:
            self._queue.put(marker, timeout=timeout)
        except queue.Full:
            return False
        return marker.done.wait(timeout)

    def close(self, timeout: float | None = 5.0) -> None:
        """Stop accepting events, deliver everything already queued, then stop the thread."""
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            started = self._started
        if not started:
            return
        self._queue.put(_STOP)
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout)

    def __enter__(self) -> Self:
        self.start()
        return self

    def _run(self) -> None:
        while True:
            event = self._queue.get()
            if event is _STOP:
                return
            if isinstance(event, _FlushMarker):
                event.done.set()
                continue
            self._deliver(event)
