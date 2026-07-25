"""One NUL-record reader for every Git path list in Build Package.

Line-oriented porcelain quotes and escapes paths that contain newlines, quotes,
or non-UTF-8 bytes, so the same file reads back as a different name — and an
unusable pathspec. The ``-z`` forms below are the only ones this package uses.
"""

from __future__ import annotations

import os

# Ask Git for records, never for lines.
STATUS_COMMAND = ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all")
CONFLICT_COMMAND = ("git", "diff", "--name-only", "--diff-filter=U", "-z")


def decode_path(record: bytes) -> str:
    """Decode one path record without losing bytes Git considers valid."""
    return os.fsdecode(record)


def parse_status_records(stdout: bytes) -> tuple[tuple[str, str], ...]:
    """Return (status, path) for each record of ``git status --porcelain -z``."""
    entries: list[tuple[str, str]] = []
    records = stdout.split(b"\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        decoded = decode_path(record)
        status = decoded[:2].strip() or "?"
        entries.append((status, decoded[3:]))
        if "R" in status or "C" in status:
            # A rename or copy spends a second record on its origin path.
            index += 1
    return tuple(entries)


def parse_path_records(stdout: bytes) -> tuple[str, ...]:
    """Return each path of a NUL-separated Git path list."""
    return tuple(decode_path(record) for record in stdout.split(b"\0") if record)


def display_path(path: str) -> str:
    """Render a path for a confirmation without letting it rewrite the screen.

    A newline or escape sequence inside a filename must not be able to forge
    extra lines in a list the user is about to approve.
    """
    return "".join(character if character.isprintable() else repr(character)[1:-1] for character in path)
