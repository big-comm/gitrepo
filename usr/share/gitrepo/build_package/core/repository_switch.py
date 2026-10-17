"""Move the open window to the repository GitRepo was launched in again.

GitRepo runs one window. Launching it a second time, from another repository,
hands that directory to the running window instead of starting a new one; this
module decides whether the window should move there.
"""

from __future__ import annotations

import os

from gitrepo.common import child_process as subprocess

STAY = "stay"  # the launch directory is not inside a repository
SAME = "same"  # already showing that repository
BUSY = "busy"  # an operation is running here; moving now would split it
SWITCH = "switch"


def repository_root(path: str) -> str:
    """Return the top of the working tree that contains *path*, or an empty string."""
    if not path or not os.path.isdir(path):
        return ""
    result = subprocess.run_git(
        ["git", "-C", path, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
        intent="ordinary",
    )
    return os.path.realpath(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else ""


def switch_decision(current_root: str, target_root: str, busy: bool) -> str:
    """Say what the window does when GitRepo is launched again in *target_root*."""
    if not target_root:
        return STAY
    if current_root and os.path.realpath(current_root) == os.path.realpath(target_root):
        return SAME
    if busy:
        return BUSY
    return SWITCH
