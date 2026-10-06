# Copyright (c) 2023 Carter Lasalle
"""In-process scheduled-send registry for the Messages MCP server.

Scheduled sends live only in memory, for the lifetime of the server
process. Nothing is persisted to disk: restarting the server discards every
pending job, and a job scheduled in one process is invisible to any other
process. This is deliberate -- a scheduler that survives restarts would need
durable storage, catch-up semantics, and deduplication, none of which this
module provides.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

__all__ = ["ScheduledMessage", "MessageScheduler"]

# Ceiling on simultaneously pending jobs. Scheduling past this raises
# ValueError so an unbounded caller cannot grow memory without limit.
_MAX_PENDING_JOBS = 1000

# Longest single Condition.wait slice. The worker re-checks its stop flag at
# least this often, so stop() returns promptly even when the next job is far
# in the future.
_MAX_WAIT_SLICE_SECONDS = 0.25


@dataclass
class ScheduledMessage:
    """One scheduled send.

    Records are created by :meth:`MessageScheduler.schedule` and exist only
    for the lifetime of the server process; they are never persisted.
    """

    id: str
    recipient: str
    message: str
    send_at: float
    group_chat: bool = False
    attachment_paths: tuple[str, ...] = ()
    status: str = "pending"  # "pending" | "running" | "sent" | "failed"
    result: str | None = None


class MessageScheduler:
    """Registry of in-memory scheduled sends.

    The scheduler is process-local by design: jobs exist only while the
    server process is alive and are never written to disk, so a restart loses
    every pending job. All public methods are safe to call from any thread and
    are guarded by a single condition variable over ``_jobs``.
    """

    def __init__(
        self,
        send: Callable[[ScheduledMessage], str],
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._send = send
        self._clock = clock
        self._condition = threading.Condition(threading.RLock())
        self._jobs: dict[str, ScheduledMessage] = {}
        self._counter = 0
        self._thread: threading.Thread | None = None
        self._stopping = False

    def schedule(
        self,
        recipient: str,
        message: str,
        send_at: float,
        *,
        group_chat: bool = False,
        attachment_paths: Iterable[str] = (),
    ) -> ScheduledMessage:
        """Register a send and return its job record.

        Ids are assigned from a monotonically increasing counter (``msg-1``,
        ``msg-2``, ...). A job needs a non-empty recipient, a finite positive
        ``send_at``, and either a non-empty message or at least one attachment
        path; otherwise ValueError is raised. More than
        ``_MAX_PENDING_JOBS`` pending jobs also raises ValueError.

        The returned job lives only in this process -- nothing is persisted.
        """
        attachments = tuple(attachment_paths)
        if not recipient:
            raise ValueError("recipient must be non-empty")
        if not message and not attachments:
            raise ValueError("message or at least one attachment path is required")
        if (
            not isinstance(send_at, (int, float))
            or not math.isfinite(send_at)
            or send_at <= 0
        ):
            raise ValueError("send_at must be a finite unix timestamp greater than 0")

        with self._condition:
            pending = sum(1 for job in self._jobs.values() if job.status == "pending")
            if pending >= _MAX_PENDING_JOBS:
                raise ValueError(
                    f"cannot schedule more than {_MAX_PENDING_JOBS} pending jobs"
                )
            self._counter += 1
            job = ScheduledMessage(
                id=f"msg-{self._counter}",
                recipient=recipient,
                message=message,
                send_at=float(send_at),
                group_chat=group_chat,
                attachment_paths=attachments,
            )
            self._jobs[job.id] = job
            self._condition.notify_all()
            return job

    def list(self) -> list[ScheduledMessage]:
        """Return every known job in stable order by ``send_at`` then ``id``.

        Jobs that already ran stay listed with their terminal status; cancelled
        jobs are removed. The order is deterministic.
        """
        with self._condition:
            return sorted(self._jobs.values(), key=lambda job: (job.send_at, job.id))

    def cancel(self, job_id: str) -> bool:
        """Cancel a pending job and return whether one was removed.

        Unknown ids and jobs that already executed return False and leave the
        registry unchanged.
        """
        with self._condition:
            job = self._jobs.get(job_id)
            if job is None or job.status != "pending":
                return False
            del self._jobs[job_id]
            self._condition.notify_all()
            return True

    def run_due(self, now: float | None = None) -> list[tuple[ScheduledMessage, str]]:
        """Execute every pending job whose ``send_at`` is at or before ``now``.

        ``now`` defaults to the scheduler clock. Each executed job is marked
        ``"sent"`` with the callback's return value, or ``"failed"`` with the
        exception text when the callback raises; exceptions never propagate to
        the caller. Jobs that already ran are never executed again. Returns
        ``(job, outcome)`` pairs in ``send_at``/``id`` order.
        """
        moment = self._clock() if now is None else now
        return self._execute(self._claim_due(moment))

    def _claim_due(self, now: float) -> list[ScheduledMessage]:
        """Mark every pending job due at ``now`` as running and return them.

        Jobs are claimed under the lock and run outside it: a real send shells
        out to AppleScript and can take seconds, which must not block
        ``schedule``, ``cancel``, ``list``, or ``stop``.
        """
        with self._condition:
            due = [
                job
                for job in self._jobs.values()
                if job.status == "pending" and job.send_at <= now
            ]
            due.sort(key=lambda job: (job.send_at, job.id))
            for job in due:
                job.status = "running"
            self._condition.notify_all()
            return due

    def _execute(
        self,
        jobs: list[ScheduledMessage],
    ) -> list[tuple[ScheduledMessage, str]]:
        """Run claimed jobs and record their outcomes; never raises."""
        executed: list[tuple[ScheduledMessage, str]] = []
        for job in jobs:
            try:
                outcome = self._send(job)
            except Exception as exc:  # record failures; never let a send escape
                outcome = str(exc)
                failed = True
            else:
                failed = False
            with self._condition:
                job.status = "failed" if failed else "sent"
                job.result = outcome
                self._condition.notify_all()
            executed.append((job, outcome))
        return executed

    def start(self) -> None:
        """Start the background worker thread.

        The worker is a daemon so it cannot keep the process alive, and start()
        is idempotent: calling it while the worker runs is a no-op.
        """
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopping = False
            thread = threading.Thread(
                target=self._run_loop,
                name="mac-messages-scheduler",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the worker thread, blocking at most ``timeout`` seconds.

        Idempotent and bounded: the worker wakes from its longest wait slice
        and exits, so this returns promptly even when the next job is far in
        the future.
        """
        with self._condition:
            self._stopping = True
            thread = self._thread
            self._condition.notify_all()
        if thread is None:
            return
        thread.join(timeout)
        if not thread.is_alive():
            with self._condition:
                if self._thread is thread:
                    self._thread = None

    def _next_due_locked(self) -> float | None:
        """Earliest pending ``send_at``, or None; caller holds the condition."""
        send_times = [
            job.send_at for job in self._jobs.values() if job.status == "pending"
        ]
        return min(send_times) if send_times else None

    def _run_loop(self) -> None:
        """Worker body: wait for the next due time, then execute it."""
        while True:
            with self._condition:
                if self._stopping:
                    return
                next_due = self._next_due_locked()
                if next_due is None:
                    self._condition.wait(_MAX_WAIT_SLICE_SECONDS)
                    continue
                now = self._clock()
                if next_due > now:
                    self._condition.wait(min(next_due - now, _MAX_WAIT_SLICE_SECONDS))
                    continue
            # Due: claim under the lock, then send outside it.
            self._execute(self._claim_due(self._clock()))
