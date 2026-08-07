"""Crash-safe local file publication for GitRepo-owned data."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class AtomicWriteError(OSError):
    """Raised when a file cannot be published atomically."""


class CorruptJsonError(ValueError):
    """Raised when a JSON store exists but cannot be decoded."""


def atomic_write_text(path: str | Path, content: str, *, mode: int = 0o600) -> None:
    """Publish text by fsyncing a same-directory temporary file and renaming it."""
    target = Path(path)
    parent = target.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if target.is_symlink():
        raise AtomicWriteError(f"refusing to replace symlink: {target}")

    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=parent)
        temporary_path = Path(temporary_name)
        try:
            os.fchmod(descriptor, mode)
        except BaseException:
            # fdopen has not taken ownership yet, so nothing else will close it.
            os.close(descriptor)
            raise
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
        directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException as error:
        # BaseException, not Exception: Ctrl-C is how both CLI apps normally
        # exit, and it would otherwise leave .<name>.XXXXXXXX behind on every
        # interrupted write, with nothing to clean them up.
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
        if isinstance(error, AtomicWriteError) or not isinstance(error, Exception):
            raise
        # Callers format this message, so it has to name the cause: "could not
        # publish /path" on its own tells the user nothing they can act on.
        detail = getattr(error, "strerror", None) or str(error)
        raise AtomicWriteError(f"could not publish {target}: {detail}") from error


class AtomicJsonStore:
    """Read and atomically publish one JSON document."""

    def __init__(self, path: str | Path, *, expected_type: type = dict, mode: int = 0o600):
        self.path = Path(path)
        self.expected_type = expected_type
        self.mode = mode

    def read(self) -> Any:
        """Return the stored document, preserving corrupt input for recovery."""
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                value = json.load(stream)
        except FileNotFoundError:
            raise
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise CorruptJsonError(f"invalid JSON in {self.path}") from error
        if not isinstance(value, self.expected_type):
            raise CorruptJsonError(f"expected {self.expected_type.__name__} in {self.path}, got {type(value).__name__}")
        return value

    def write(self, value: Any) -> None:
        """Validate and publish one JSON document."""
        if not isinstance(value, self.expected_type):
            raise TypeError(f"expected {self.expected_type.__name__}, got {type(value).__name__}")
        content = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
        atomic_write_text(self.path, content, mode=self.mode)
