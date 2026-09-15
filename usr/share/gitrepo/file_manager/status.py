"""Read repository-root status without network access or index writes."""

from __future__ import annotations

import os
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Literal

from gitrepo.common.child_process import run_git


State = Literal["clean", "modified", "unpushed", "conflict"]
EMBLEMS = {state: f"gitrepo-{state}" for state in ("clean", "modified", "unpushed", "conflict")}


def repository_state(path: str | Path) -> State | None:
    """Return one emblem state; ordinary folders and failed probes have none.

    Only working-tree roots qualify, including linked worktrees and submodules.
    Remote-tracking refs are local snapshots; this never fetches from a remote.
    """
    path = Path(path)
    if not (path / ".git").exists():
        return None

    # The file manager may inherit Git's process-local repository overrides.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", LC_ALL="C")

    def git(*args: str):
        return run_git(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(path), *args],
            intent="ordinary",
            env=env,
            capture_output=True,
            timeout=10,
            check=False,
        )

    try:
        result = git(
            "status", "--porcelain=v2", "--branch", "-z", "--untracked-files=normal", "--ignore-submodules=none"
        )
        if result.returncode:
            return None

        headers: dict[bytes, bytes] = {}
        modified = False
        records = iter(result.stdout.split(b"\0"))
        for record in records:
            if record.startswith(b"# "):
                key, _, value = record[2:].partition(b" ")
                headers[key] = value
            elif record.startswith(b"u "):
                return "conflict"
            elif record.startswith((b"1 ", b"2 ", b"? ")):
                modified = True
                if record.startswith(b"2 "):
                    next(records, None)  # Rename source paths are separate NUL records.
        if modified:
            return "modified"

        ahead = headers.get(b"branch.ab", b"+0 -0").split()[0]
        if int(ahead) > 0:
            return "unpushed"
        branch = headers.get(b"branch.head", b"(detached)")
        if b"branch.ab" not in headers and branch != b"(detached)" and headers.get(b"branch.oid") != b"(initial)":
            if b"branch.upstream" in headers:
                return "unpushed"  # The configured upstream ref disappeared.
            # GitRepo also publishes same-name origin branches without an upstream.
            remote_ref = "refs/remotes/origin/" + os.fsdecode(branch)
            remote = git("show-ref", "--verify", "--quiet", remote_ref)
            if remote.returncode == 1:
                return "unpushed"
            if remote.returncode:
                return None
            pending = git("rev-list", "--max-count=1", "HEAD", "--not", remote_ref, "--")
            if pending.returncode:
                return None
            if pending.stdout.strip():
                return "unpushed"
        return "clean"
    except (OSError, TimeoutExpired, ValueError):
        return None
