"""One repository journey at a time, across windows and across processes.

Git's own index lock protects a single command. It does not protect a journey
that spans stash, checkout, commit and push: a second action can land between
two of those steps and leave the repository in a state neither one intended.
"""

from __future__ import annotations

import errno
import fcntl
import functools
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from gitrepo.common.translation import _

from .git_utils import GitUtils

LOCK_FILE_NAME = "gitrepo-operation.lock"

# A journey may call another one — publishing a package commits first — so the
# owning thread re-enters freely while any other thread is refused outright.
_owner = threading.local()
_in_process = threading.Lock()


class RepositoryBusy(RuntimeError):
    """Raised when another GitRepo journey already owns this repository."""


def _lock_path() -> str:
    root = GitUtils.get_repo_root_path()
    git_dir = os.path.join(root, ".git")
    # A worktree or submodule has a .git file pointing elsewhere; the lock then
    # lives beside it in the working tree, which is still one per checkout.
    directory = git_dir if os.path.isdir(git_dir) else root
    return os.path.join(directory, LOCK_FILE_NAME)


def current_holder() -> str:
    """Return what the lock file says is running, or an empty string."""
    try:
        with open(_lock_path(), "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


@contextmanager
def repository_operation(name: str) -> Iterator[None]:
    """Own the repository for one complete journey, or refuse immediately."""
    if getattr(_owner, "depth", 0):
        # This thread already owns the journey this one is part of.
        _owner.depth += 1
        try:
            yield
        finally:
            _owner.depth -= 1
        return

    if not _in_process.acquire(blocking=False):
        raise RepositoryBusy(current_holder() or name)

    descriptor = None
    try:
        try:
            descriptor = os.open(_lock_path(), os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if descriptor is not None and error.errno in (errno.EACCES, errno.EAGAIN):
                raise RepositoryBusy(current_holder() or name) from error
            if descriptor is not None:
                os.close(descriptor)
                descriptor = None
            # Without a usable lock file there is nothing to serialize against;
            # refusing every operation would be worse than the race it prevents.

        if descriptor is not None:
            os.ftruncate(descriptor, 0)
            os.write(descriptor, f"{name} (pid {os.getpid()})\n".encode())
            os.fsync(descriptor)

        _owner.depth = 1
        try:
            yield
        finally:
            _owner.depth = 0
    finally:
        if descriptor is not None:
            os.close(descriptor)
        _in_process.release()


def journey(name: str, busy_result):
    """Run one decorated repository journey under the repository lock."""

    def decorate(function):
        @functools.wraps(function)
        def wrapper(bp, *args, **kwargs):
            try:
                with repository_operation(name):
                    return function(bp, *args, **kwargs)
            except RepositoryBusy as busy:
                logger = getattr(bp, "logger", None)
                if logger:
                    logger.log("red", _("This repository is busy with: {0}").format(busy))
                    logger.log("cyan", _("Wait for that operation to finish, then try again."))
                return busy_result() if callable(busy_result) else busy_result

        return wrapper

    return decorate
