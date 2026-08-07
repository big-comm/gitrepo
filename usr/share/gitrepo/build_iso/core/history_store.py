"""Durable ownership of Build ISO history."""

from __future__ import annotations

from gitrepo.build_iso.core.config import HISTORY_FILE
from gitrepo.common.atomic_file import AtomicJsonStore, AtomicWriteError, CorruptJsonError


class BuildHistoryStore:
    """Load and atomically publish validated build-history entries."""

    def __init__(self, path: str = HISTORY_FILE):
        self._store = AtomicJsonStore(path, expected_type=list)
        self.last_error = ""

    def load(self) -> list[dict]:
        # Describe this read, not an older one: add() refuses while the flag is
        # set, so a single corrupt file used to silence history forever.
        self.last_error = ""
        try:
            entries = self._store.read()
        except FileNotFoundError:
            return []
        except (CorruptJsonError, OSError) as error:
            self.last_error = str(error)
            return []
        if not all(isinstance(entry, dict) for entry in entries):
            self.last_error = "history entries must be objects"
            return []
        return entries

    def add(self, entry: dict) -> bool:
        if not isinstance(entry, dict):
            raise TypeError("history entry must be an object")
        entries = self.load()
        if self.last_error:
            return False
        try:
            self._store.write((entries + [entry])[-100:])
            return True
        except (AtomicWriteError, OSError):
            return False

    def clear(self) -> bool:
        try:
            self._store.write([])
            self.last_error = ""
            return True
        except (AtomicWriteError, OSError):
            return False
