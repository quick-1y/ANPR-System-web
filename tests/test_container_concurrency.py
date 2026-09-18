"""Tests for AppContainer's concurrency hardening (app/api/container.py):

- restart_processor_for_settings() serializes its stop->create->start swap
  behind a lock, so two concurrent settings-driven restarts (e.g. a settings
  save racing a settings restore) can't interleave and orphan a processor
  or double-start a channel (finding #6).
- publish_event_sync() tolerates the main event loop stopping between its
  is_running() check and call_soon_threadsafe() (finding #7).

Uses hand-written stub objects rather than a mocking library, per project
convention (AGENTS.md). AppContainer is constructed directly with stub/None
values for fields the methods under test don't touch — dataclasses don't
validate field types at construction time, so this is safe.
"""
from __future__ import annotations

import threading
import time

from app.api.container import AppContainer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeProcessor:
    def __init__(self):
        self.stopped: list[int] = []
        self.ensured: list[dict] = []
        self.started: list[int] = []
        self.shutdown_called = False

    def stop(self, channel_id):
        self.stopped.append(channel_id)

    def shutdown_io_pool(self):
        self.shutdown_called = True

    def ensure_channel(self, channel):
        self.ensured.append(channel)

    def start(self, channel_id):
        self.started.append(channel_id)

    def list_states(self):
        return {}


class _FakeChannelDb:
    def __init__(self, channels):
        self._channels = channels

    def list_channels(self):
        return self._channels


def _make_container(channels=(), processor=None):
    return AppContainer(
        settings=None,
        events_db=None,
        lists_db=None,
        clients_db=None,
        user_db=None,
        channel_db=_FakeChannelDb(list(channels)),
        controller_db=None,
        zone_db=None,
        controller_service=None,
        controller_automation=None,
        event_bus=None,
        debug_registry=None,
        debug_log_bus=None,
        processor=processor or _FakeProcessor(),
        lifecycle=None,
        main_loop=None,
        stream_shutdown=None,
    )


# ---------------------------------------------------------------------------
# restart_processor_for_settings — finding #6
# ---------------------------------------------------------------------------

class TestRestartProcessorForSettings:
    def test_stops_old_and_starts_only_enabled_channels(self):
        channels = [{"id": 1, "enabled": True}, {"id": 2, "enabled": False}]
        old_processor = _FakeProcessor()
        container = _make_container(channels=channels, processor=old_processor)
        new_processor = _FakeProcessor()
        container._create_processor = lambda: new_processor

        container.restart_processor_for_settings()

        assert old_processor.stopped == [1, 2]
        assert old_processor.shutdown_called is True
        assert container.processor is new_processor
        assert new_processor.ensured == channels
        assert new_processor.started == [1]

    def test_concurrent_calls_never_overlap_inside_the_swap(self):
        """Two threads calling restart_processor_for_settings() at once must
        not run their stop->create->start critical sections concurrently —
        that's exactly the race finding #6 describes."""
        container = _make_container(channels=[{"id": 1, "enabled": True}])

        active = {"count": 0, "max": 0}
        counter_lock = threading.Lock()

        def slow_create_processor():
            with counter_lock:
                active["count"] += 1
                active["max"] = max(active["max"], active["count"])
            time.sleep(0.05)  # widen the race window
            proc = _FakeProcessor()
            with counter_lock:
                active["count"] -= 1
            return proc

        container._create_processor = slow_create_processor

        threads = [threading.Thread(target=container.restart_processor_for_settings) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert active["max"] == 1, "two restarts ran their critical section concurrently"

    def test_lock_is_released_after_normal_completion(self):
        """A prior successful call must not leave the lock held forever."""
        container = _make_container(channels=[])
        container._create_processor = lambda: _FakeProcessor()

        container.restart_processor_for_settings()

        assert container._processor_swap_lock.acquire(blocking=False)
        container._processor_swap_lock.release()


# ---------------------------------------------------------------------------
# publish_event_sync — finding #7
# ---------------------------------------------------------------------------

class _FakeLoop:
    def __init__(self, running=True, raise_on_call=False):
        self._running = running
        self._raise_on_call = raise_on_call
        self.calls: list[tuple] = []

    def is_running(self):
        return self._running

    def call_soon_threadsafe(self, *args):
        if self._raise_on_call:
            raise RuntimeError("Event loop is closed")
        self.calls.append(args)


class _FakeEventBus:
    def publish(self, event):
        return event


class _FakeControllerAutomation:
    def __init__(self):
        self.dispatched: list[dict] = []

    def dispatch_event(self, event):
        self.dispatched.append(event)


def _make_event_container(loop):
    container = _make_container()
    container.main_loop = loop
    container.event_bus = _FakeEventBus()
    container.controller_automation = _FakeControllerAutomation()
    return container


class TestPublishEventSync:
    def test_normal_path_publishes_and_dispatches(self):
        loop = _FakeLoop(running=True)
        container = _make_event_container(loop)

        container.publish_event_sync({"plate": "A123BC"})

        assert len(loop.calls) == 1
        assert container.controller_automation.dispatched == [{"plate": "A123BC"}]

    def test_loop_stopping_between_check_and_call_does_not_raise(self):
        """Regression test for finding #7: call_soon_threadsafe raising
        RuntimeError (loop closed mid-call) must not propagate out of
        publish_event_sync, since it's invoked from a background detection
        thread with no caller prepared to handle it."""
        loop = _FakeLoop(running=True, raise_on_call=True)
        container = _make_event_container(loop)

        container.publish_event_sync({"plate": "A123BC"})  # must not raise

        # Controller automation still runs even though the event-bus publish failed.
        assert container.controller_automation.dispatched == [{"plate": "A123BC"}]

    def test_no_loop_skips_publish_but_still_dispatches(self):
        container = _make_event_container(loop=None)

        container.publish_event_sync({"plate": "A123BC"})

        assert container.controller_automation.dispatched == [{"plate": "A123BC"}]

    def test_relay_blocked_event_skips_dispatch(self):
        loop = _FakeLoop(running=True)
        container = _make_event_container(loop)

        container.publish_event_sync({"plate": "A123BC", "relay_blocked": True})

        assert container.controller_automation.dispatched == []
