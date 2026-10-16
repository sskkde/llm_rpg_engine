"""Runtime supervision for turn claims: lease heartbeats and the service turn budget.

A worker sits inside model calls for seconds to minutes, while the claim lease is
short by design. The heartbeat therefore renews the lease from its **own thread and
its own short-lived Session**, so the worker Session never carries a database
transaction across the model-wait window.

The contract with the turn service is deliberately strict: renewals must be stopped
and joined before the authoritative commit, and a worker that cannot stop them (or
that is told the claim is gone) must not commit its facts.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Optional

from sqlalchemy.orm import Session

from .turn_claim import (
    HEARTBEAT_INTERVAL_SECONDS,
    ClaimRejected,
    ClaimToken,
    heartbeat_claim,
)

logger = logging.getLogger(__name__)

DEFAULT_TURN_BUDGET_SECONDS = float(os.getenv("TURN_TOTAL_BUDGET_SECONDS", "600"))
DEFAULT_HEARTBEAT_STOP_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_CONSECUTIVE_FAILURES = 3


class TurnBudget:
    """Monotonic, wall-clock-independent service budget for one turn.

    ``remaining()`` never goes negative so callers can use it directly as a model
    call or join timeout without re-clamping.
    """

    def __init__(
        self,
        total_seconds: float = DEFAULT_TURN_BUDGET_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.total_seconds = float(total_seconds)
        self._clock = clock
        self._started_at = clock()

    def expired(self) -> bool:
        """Return whether the budget has been consumed."""
        return self._clock() - self._started_at >= self.total_seconds

    def remaining(self) -> float:
        """Return the seconds left in the budget (0.0 once expired)."""
        return max(0.0, self.total_seconds - (self._clock() - self._started_at))


class ClaimHeartbeat:
    """Renew one turn claim lease from an independent Session until told to stop.

    Lifecycle: ``start()`` spawns the renewing thread, ``stop()`` shuts it down
    within a bounded join. Renewals never touch the worker Session, and the very
    first loop action is waiting out the interval, so a short turn performs no
    renewal tick at all.
    """

    def __init__(
        self,
        session_factory: Callable[[], Session],
        token: ClaimToken,
        *,
        interval: float = HEARTBEAT_INTERVAL_SECONDS,
        budget: Optional[TurnBudget] = None,
        max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
    ) -> None:
        self._session_factory = session_factory
        self._token = token
        self._interval = float(interval)
        self._budget = budget
        self._max_consecutive_failures = int(max_consecutive_failures)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lost = False
        self._consecutive_failures = 0
        self._state_lock = threading.Lock()

    @property
    def lost(self) -> bool:
        """Whether this worker is known to have lost the right to commit."""
        with self._state_lock:
            return self._lost

    def _mark_lost(self) -> None:
        with self._state_lock:
            self._lost = True

    def start(self) -> None:
        """Start renewals; never raises, failures surface through ``lost``."""
        with self._state_lock:
            if self._thread is not None:
                return
            try:
                thread = threading.Thread(
                    target=self._run, name="turn-claim-heartbeat", daemon=True
                )
                thread.start()
            except Exception:
                # A worker that cannot renew must not believe it still holds the claim.
                self._lost = True
                logger.warning(
                    "Turn claim heartbeat could not start for %s",
                    self._token.transaction_id,
                    exc_info=True,
                )
                return
            self._thread = thread

    def stop(self, timeout: float = DEFAULT_HEARTBEAT_STOP_TIMEOUT_SECONDS) -> bool:
        """Request shutdown and wait, bounded, for renewals to end.

        Idempotent and safe from any path, including the heartbeat thread itself.
        Returns True only when the renewing thread has actually exited; a False
        result means the caller must not treat the lease as quiesced.
        """
        self._stop_event.set()
        thread = self._thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return False
        thread.join(timeout)
        return not thread.is_alive()

    def _run(self) -> None:
        # Waiting first keeps short turns tick-free and makes stop() prompt.
        while not self._stop_event.wait(self._interval):
            if self._budget is not None and self._budget.expired():
                logger.warning(
                    "Turn budget expired; stopping claim renewals for %s",
                    self._token.transaction_id,
                )
                return
            try:
                self._renew_once()
            except ClaimRejected:
                # The claim was fenced, taken over or already committed: this worker
                # no longer owns the row and must stop renewing immediately.
                self._mark_lost()
                return
            except Exception:
                self._consecutive_failures += 1
                logger.warning(
                    "Turn claim heartbeat renewal failed (%s/%s) for %s",
                    self._consecutive_failures,
                    self._max_consecutive_failures,
                    self._token.transaction_id,
                    exc_info=True,
                )
                if self._consecutive_failures > self._max_consecutive_failures:
                    self._mark_lost()
                    return
            else:
                self._consecutive_failures = 0

    def _renew_once(self) -> None:
        db = self._session_factory()
        try:
            heartbeat_claim(db, self._token)
            db.commit()
        finally:
            db.close()
