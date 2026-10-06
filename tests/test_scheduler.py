# Copyright (c) 2023 Carter Lasalle
"""Tests for the in-memory scheduled-send registry."""

import time

import pytest

from mac_messages_mcp.scheduler import (
    _MAX_PENDING_JOBS,
    MessageScheduler,
    ScheduledMessage,
)


class FakeClock:
    """Deterministic clock advanced by hand instead of by wall time."""

    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RecordingSend:
    """Fake send callback that records calls and can be told to fail."""

    def __init__(self) -> None:
        self.calls: list[ScheduledMessage] = []
        self.failures: dict[str, Exception] = {}

    def __call__(self, job: ScheduledMessage) -> str:
        self.calls.append(job)
        failure = self.failures.get(job.id)
        if failure is not None:
            raise failure
        return f"sent {job.id}"


def make_scheduler() -> tuple[MessageScheduler, RecordingSend, FakeClock]:
    send = RecordingSend()
    clock = FakeClock()
    return MessageScheduler(send, clock=clock), send, clock


def test_past_due_job_runs_and_records_result():
    scheduler, send, _ = make_scheduler()
    job = scheduler.schedule("+15551234567", "hello", 500.0)

    executed = scheduler.run_due(now=1_000.0)

    assert executed == [(job, "sent msg-1")]
    assert job.status == "sent"
    assert job.result == "sent msg-1"
    assert [call.id for call in send.calls] == ["msg-1"]
    assert scheduler.list() == [job]


def test_future_job_is_not_executed():
    scheduler, send, _ = make_scheduler()
    job = scheduler.schedule("+15551234567", "later", 2_000.0)

    assert scheduler.run_due(now=1_000.0) == []
    assert job.status == "pending"
    assert job.result is None
    assert send.calls == []


def test_run_due_defaults_to_injected_clock():
    scheduler, _, clock = make_scheduler()
    scheduler.schedule("+15551234567", "hello", 900.0)

    clock.now = 1_000.0

    assert [job.id for job, _ in scheduler.run_due()] == ["msg-1"]


def test_executed_job_is_never_run_again():
    scheduler, send, _ = make_scheduler()
    scheduler.schedule("+15551234567", "hello", 500.0)
    scheduler.run_due(now=1_000.0)

    assert scheduler.run_due(now=2_000.0) == []
    assert len(send.calls) == 1


def test_cancel_returns_true_then_false_and_job_never_runs():
    scheduler, send, _ = make_scheduler()
    job = scheduler.schedule("+15551234567", "hello", 500.0)

    assert scheduler.cancel(job.id) is True
    assert scheduler.cancel(job.id) is False
    assert scheduler.run_due(now=1_000.0) == []
    assert send.calls == []
    assert scheduler.list() == []


def test_cancel_unknown_id_returns_false():
    scheduler, _, _ = make_scheduler()

    assert scheduler.cancel("msg-404") is False


def test_cancel_after_execution_returns_false_and_job_stays_listed():
    scheduler, _, _ = make_scheduler()
    job = scheduler.schedule("+15551234567", "hello", 500.0)
    scheduler.run_due(now=1_000.0)

    assert scheduler.cancel(job.id) is False
    assert [entry.id for entry in scheduler.list()] == [job.id]
    assert job.status == "sent"


def test_send_failure_marks_failed_without_propagating():
    scheduler, send, _ = make_scheduler()
    job = scheduler.schedule("+15551234567", "hello", 500.0)
    send.failures[job.id] = ValueError("boom")

    executed = scheduler.run_due(now=1_000.0)

    assert executed == [(job, "boom")]
    assert job.status == "failed"
    assert job.result == "boom"
    assert scheduler.cancel(job.id) is False


def test_list_orders_by_send_at_then_id():
    scheduler, _, _ = make_scheduler()
    late = scheduler.schedule("+15551234567", "late", 300.0)
    early = scheduler.schedule("+15551234567", "early", 100.0)
    tie = scheduler.schedule("+15551234567", "tie", 100.0)

    assert [job.id for job in scheduler.list()] == [early.id, tie.id, late.id]


def test_run_due_orders_execution_by_send_at():
    scheduler, send, _ = make_scheduler()
    later = scheduler.schedule("+15551234567", "later", 300.0)
    earlier = scheduler.schedule("+15551234567", "earlier", 100.0)

    executed = scheduler.run_due(now=1_000.0)

    assert [job.id for job, _ in executed] == [earlier.id, later.id]
    assert [call.id for call in send.calls] == [earlier.id, later.id]


def test_ids_are_monotonic():
    scheduler, _, _ = make_scheduler()

    first = scheduler.schedule("+15551234567", "one", 500.0)
    second = scheduler.schedule("+15551234567", "two", 600.0)

    assert (first.id, second.id) == ("msg-1", "msg-2")


def test_schedule_records_fields():
    scheduler, _, _ = make_scheduler()

    job = scheduler.schedule(
        "chat-1",
        "hi",
        500.0,
        group_chat=True,
        attachment_paths=("/a.png", "/b.png"),
    )

    assert job.id == "msg-1"
    assert job.recipient == "chat-1"
    assert job.message == "hi"
    assert job.send_at == 500.0
    assert job.group_chat is True
    assert job.attachment_paths == ("/a.png", "/b.png")
    assert job.status == "pending"
    assert job.result is None


def test_schedule_rejects_empty_recipient():
    scheduler, _, _ = make_scheduler()

    with pytest.raises(ValueError):
        scheduler.schedule("", "hello", 500.0)


def test_schedule_rejects_message_without_content_or_attachment():
    scheduler, _, _ = make_scheduler()

    with pytest.raises(ValueError):
        scheduler.schedule("+15551234567", "", 500.0)


def test_schedule_accepts_attachment_only_message():
    scheduler, _, _ = make_scheduler()

    job = scheduler.schedule(
        "+15551234567", "", 500.0, attachment_paths=["/tmp/pic.png"]
    )

    assert job.message == ""
    assert job.attachment_paths == ("/tmp/pic.png",)


@pytest.mark.parametrize("send_at", [0.0, -1.0, float("nan"), float("inf")])
def test_schedule_rejects_invalid_send_at(send_at):
    scheduler, _, _ = make_scheduler()

    with pytest.raises(ValueError):
        scheduler.schedule("+15551234567", "hello", send_at)


def test_schedule_enforces_pending_cap():
    scheduler, _, _ = make_scheduler()
    for _ in range(_MAX_PENDING_JOBS):
        scheduler.schedule("+15551234567", "hello", 500.0)

    with pytest.raises(ValueError):
        scheduler.schedule("+15551234567", "hello", 500.0)


def test_cap_ignores_executed_jobs():
    scheduler, _, _ = make_scheduler()
    for _ in range(_MAX_PENDING_JOBS):
        scheduler.schedule("+15551234567", "hello", 500.0)
    scheduler.run_due(now=1_000.0)

    # Terminal jobs no longer occupy the pending cap.
    scheduler.schedule("+15551234567", "hello again", 600.0)


def test_stop_before_start_is_noop():
    scheduler, _, _ = make_scheduler()

    scheduler.stop()


def test_start_stop_without_jobs_terminates_promptly():
    scheduler, _, _ = make_scheduler()

    scheduler.start()
    thread = scheduler._thread
    assert thread is not None
    assert thread.is_alive()
    assert thread.daemon is True

    started = time.monotonic()
    scheduler.stop(timeout=5.0)
    elapsed = time.monotonic() - started

    assert not thread.is_alive()
    assert elapsed < 5.0

    # Idempotent: a second stop returns without error.
    scheduler.stop(timeout=5.0)


def test_start_is_idempotent():
    scheduler, _, _ = make_scheduler()

    scheduler.start()
    first = scheduler._thread
    scheduler.start()

    try:
        assert scheduler._thread is first
    finally:
        scheduler.stop(timeout=5.0)


def test_stop_is_bounded_with_far_future_job():
    scheduler, _, _ = make_scheduler()
    scheduler.schedule("+15551234567", "far", 10_000_000.0)
    scheduler.start()

    started = time.monotonic()
    scheduler.stop(timeout=5.0)
    elapsed = time.monotonic() - started

    assert elapsed < 5.0


def test_start_executes_due_job_with_injected_clock():
    scheduler, send, clock = make_scheduler()
    clock.now = 1_000.0
    scheduler.schedule("+15551234567", "hello", 999.0)

    scheduler.start()
    try:
        deadline = time.monotonic() + 5.0
        while not send.calls and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        scheduler.stop(timeout=5.0)

    assert [call.id for call in send.calls] == ["msg-1"]
