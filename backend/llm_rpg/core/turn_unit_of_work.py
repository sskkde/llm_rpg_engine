"""Session-scoped transaction ownership for authoritative turn writes."""

from sqlalchemy.orm import Session


_TURN_UOW_INFO_KEY = "turn_uow"


class TurnUnitOfWorkError(RuntimeError):
    """Raised when a Session cannot safely enter a turn unit of work."""


class TurnUnitOfWork:
    """Mark a Session as managed without committing on successful exit.

    Nested scopes on the same Session are rejected explicitly. The prior
    ``Session.info`` value is restored even if rollback itself fails.
    """

    def __init__(self, db: Session, *, guard_commits: bool = False):
        self.db = db
        self.guard_commits = guard_commits
        self._previous_marker = None
        self._original_commit = None
        self._entered = False

    def __enter__(self) -> "TurnUnitOfWork":
        if self._entered:
            raise TurnUnitOfWorkError("TurnUnitOfWork instance cannot be re-entered")
        if is_managed(self.db):
            raise TurnUnitOfWorkError("Session is already inside a managed turn unit of work")
        if self.db.new or self.db.dirty or self.db.deleted:
            raise TurnUnitOfWorkError(
                "Cannot enter turn unit of work with pending Session changes "
                f"(new={len(self.db.new)}, dirty={len(self.db.dirty)}, deleted={len(self.db.deleted)})"
            )

        self._previous_marker = self.db.info.get(_TURN_UOW_INFO_KEY, _MISSING)
        if self.guard_commits:
            self._original_commit = self.db.commit
            self.db.commit = self.db.flush
        self.db.info[_TURN_UOW_INFO_KEY] = True
        self._entered = True
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if not self._entered:
            return False
        try:
            if exc_type is not None:
                self.db.rollback()
        finally:
            if self._original_commit is not None:
                self.db.commit = self._original_commit
                self._original_commit = None
            if self._previous_marker is _MISSING:
                self.db.info.pop(_TURN_UOW_INFO_KEY, None)
            else:
                self.db.info[_TURN_UOW_INFO_KEY] = self._previous_marker
            self._entered = False
        return False

    def allow_commit(self) -> None:
        """Restore Session.commit for the UoW's explicit authoritative commit."""
        if not self._entered:
            raise TurnUnitOfWorkError("Cannot allow commit outside an active turn unit of work")
        if self._original_commit is not None:
            self.db.commit = self._original_commit
            self._original_commit = None


_MISSING = object()


def is_managed(db: Session) -> bool:
    """Return whether ``db`` is currently managed by a turn UoW."""
    return bool(db.info.get(_TURN_UOW_INFO_KEY, False))
