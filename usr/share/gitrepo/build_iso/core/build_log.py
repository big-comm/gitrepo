"""Durable build logs for Build ISO runs."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import TextIO

from gitrepo.build_iso.core.config import LOG_DIR_BASE

# A finished build can only be diagnosed from its log, so the file survives the
# progress dialog. Keeping the newest runs is enough; older ones are noise.
RETAINED_LOGS = 20
# Profile names reach this from remote catalogs, so the file name keeps only
# characters that cannot build a path or hide a directory traversal.
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")


def _slug(value: str) -> str:
    return _SAFE_NAME.sub("-", value).strip("-") or "unknown"


class BuildLogFile:
    """Append one build's output to a private file under the state directory."""

    def __init__(self, distro: str, edition: str, *, directory: str = LOG_DIR_BASE, started_at: datetime | None = None):
        stamp = (started_at or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")
        self.directory = Path(directory)
        self.path = str(self.directory / f"{stamp}_{_slug(distro)}-{_slug(edition)}.log")
        self.error = ""
        self._handle: TextIO | None = None
        self._open()

    def _open(self) -> None:
        try:
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            self._handle = os.fdopen(descriptor, "a", encoding="utf-8")
        except OSError as error:
            self.error = str(error)
            self._handle = None

    def append(self, message: str) -> None:
        """Write one already-redacted log line, ignoring storage failures."""
        if self._handle is None:
            return
        try:
            self._handle.write(message + "\n")
            self._handle.flush()
        except OSError as error:
            self.error = str(error)
            self.close()

    def close(self) -> None:
        if self._handle is None:
            return
        try:
            self._handle.close()
        except OSError:
            pass
        self._handle = None

    def prune(self, *, keep: int = RETAINED_LOGS) -> None:
        """Delete the oldest logs beyond the retention count."""
        try:
            logs = sorted(self.directory.glob("*.log"), key=lambda entry: entry.name, reverse=True)
        except OSError as error:
            self.error = str(error)
            return
        for stale in logs[keep:]:
            try:
                stale.unlink()
            except OSError:
                continue
