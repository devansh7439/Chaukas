from __future__ import annotations

import logging
import threading

import pytest

from chaukas.core.errors import BusClosedError
from chaukas.core.events import SyncEventBus, ThreadedEventBus


class Base:
    def __init__(self, n: int = 0) -> None:
        self.n = n


class Child(Base):
    pass


class Other:
    pass


class TestSyncEventBus:
    def test_delivers_only_matching_types(self) -> None:
        bus = SyncEventBus()
        received: list[object] = []
        bus.subscribe(Other, received.append)
        bus.publish(Other())
        bus.publish(Base())
        assert len(received) == 1
        assert isinstance(received[0], Other)

    def test_subclass_events_reach_base_subscribers_most_specific_first(self) -> None:
        bus = SyncEventBus()
        order: list[str] = []
        bus.subscribe(object, lambda _: order.append("object"))
        bus.subscribe(Base, lambda _: order.append("base"))
        bus.subscribe(Child, lambda _: order.append("child"))
        bus.publish(Child())
        assert order == ["child", "base", "object"]

    def test_new_subscriptions_invalidate_the_dispatch_cache(self) -> None:
        bus = SyncEventBus()
        order: list[str] = []
        bus.subscribe(Base, lambda _: order.append("base"))
        bus.publish(Child())
        bus.subscribe(Child, lambda _: order.append("child"))
        bus.publish(Child())
        assert order == ["base", "child", "base"]

    def test_cancel_stops_delivery_and_is_idempotent(self) -> None:
        bus = SyncEventBus()
        received: list[Base] = []
        subscription = bus.subscribe(Base, received.append)
        bus.publish(Base(1))
        subscription.cancel()
        subscription.cancel()
        bus.publish(Base(2))
        assert [event.n for event in received] == [1]
        assert not subscription.active

    def test_subscription_as_context_manager(self) -> None:
        bus = SyncEventBus()
        received: list[Base] = []
        with bus.subscribe(Base, received.append):
            bus.publish(Base(1))
        bus.publish(Base(2))
        assert [event.n for event in received] == [1]

    def test_failing_handler_is_isolated_and_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        bus = SyncEventBus()
        received: list[Base] = []

        def boom(_: Base) -> None:
            raise RuntimeError("boom")

        bus.subscribe(Base, boom)
        bus.subscribe(Base, received.append)
        with caplog.at_level(logging.ERROR, logger="chaukas.core.events"):
            bus.publish(Base())
        assert len(received) == 1
        assert "failed on Base" in caplog.text

    def test_events_published_by_handlers_are_delivered_breadth_first(self) -> None:
        bus = SyncEventBus()
        log: list[str] = []

        def on_base(event: Base) -> None:
            log.append(f"start {event.n}")
            if event.n == 0:
                bus.publish(Base(1))
            log.append(f"end {event.n}")

        bus.subscribe(Base, on_base)
        bus.publish(Base(0))
        assert log == ["start 0", "end 0", "start 1", "end 1"]

    def test_publish_after_close_raises(self) -> None:
        with SyncEventBus() as bus:
            pass
        assert bus.closed
        with pytest.raises(BusClosedError):
            bus.publish(Base())


class TestThreadedEventBus:
    def test_delivers_in_publish_order_on_one_dispatcher_thread(self) -> None:
        received: list[int] = []
        threads: set[int] = set()

        def handler(event: Base) -> None:
            received.append(event.n)
            threads.add(threading.get_ident())

        with ThreadedEventBus() as bus:
            bus.subscribe(Base, handler)
            for n in range(500):
                bus.publish(Base(n))
            assert bus.flush(timeout=5)
        assert received == list(range(500))
        assert len(threads) == 1
        assert threading.get_ident() not in threads

    def test_concurrent_producers_keep_their_own_order(self) -> None:
        received: list[tuple[int, int]] = []
        with ThreadedEventBus() as bus:
            bus.subscribe(tuple, received.append)

            def produce(producer: int) -> None:
                for i in range(200):
                    bus.publish((producer, i))

            workers = [threading.Thread(target=produce, args=(p,)) for p in range(4)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
            assert bus.flush(timeout=5)
        assert len(received) == 800
        for producer in range(4):
            assert [i for p, i in received if p == producer] == list(range(200))

    def test_close_delivers_events_queued_before_start(self) -> None:
        bus = ThreadedEventBus()
        received: list[Base] = []
        bus.subscribe(Base, received.append)
        for n in range(100):
            bus.publish(Base(n))
        bus.start()
        bus.close(timeout=5)
        assert [event.n for event in received] == list(range(100))
        with pytest.raises(BusClosedError):
            bus.publish(Base())
        with pytest.raises(BusClosedError):
            bus.start()

    def test_full_queue_drops_and_counts(self, caplog: pytest.LogCaptureFixture) -> None:
        bus = ThreadedEventBus(maxsize=1, publish_timeout=0.0)
        with caplog.at_level(logging.WARNING, logger="chaukas.core.events"):
            bus.publish(Base(1))
            bus.publish(Base(2))
        assert bus.dropped == 1
        assert "dropped Base" in caplog.text
        bus.close()

    def test_flush_requires_a_started_bus(self) -> None:
        bus = ThreadedEventBus()
        with pytest.raises(RuntimeError, match="started"):
            bus.flush(timeout=1)
        bus.close()

    def test_flush_from_a_handler_is_refused(self) -> None:
        errors: list[RuntimeError] = []
        with ThreadedEventBus() as bus:

            def handler(_: Base) -> None:
                try:
                    bus.flush(timeout=1)
                except RuntimeError as exc:
                    errors.append(exc)

            bus.subscribe(Base, handler)
            bus.publish(Base())
            assert bus.flush(timeout=5)
        assert len(errors) == 1
        assert "deadlock" in str(errors[0])

    def test_rejects_invalid_parameters(self) -> None:
        with pytest.raises(ValueError, match="maxsize"):
            ThreadedEventBus(maxsize=0)
        with pytest.raises(ValueError, match="publish_timeout"):
            ThreadedEventBus(publish_timeout=-1.0)
