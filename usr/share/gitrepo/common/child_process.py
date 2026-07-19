"""Explicit subprocess boundary with GitRepo-private environment removed."""

from __future__ import annotations

import subprocess as _subprocess
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, Literal

from .render_environment import child_process_environment


CalledProcessError = _subprocess.CalledProcessError
SubprocessError = _subprocess.SubprocessError
DEVNULL = _subprocess.DEVNULL
PIPE = _subprocess.PIPE
STDOUT = _subprocess.STDOUT

_destructive_git_authorized: ContextVar[bool] = ContextVar("destructive_git_authorized", default=False)


class DestructiveGitCommandError(PermissionError):
    """Raised when destructive Git argv reaches the process boundary unconfirmed."""


class GitIntentRequiredError(ValueError):
    """Raised when Git argv crosses a process API without explicit intent."""


def _command_from(popenargs: tuple[Any, ...], kwargs: dict[str, Any]) -> object:
    return popenargs[0] if popenargs else kwargs.get("args")


def _is_git_argv(command: object) -> bool:
    return (
        isinstance(command, Sequence)
        and not isinstance(command, (str, bytes))
        and bool(command)
        and Path(str(command[0])).name == "git"
    )


@contextmanager
def authorize_destructive_git() -> Iterator[None]:
    """Authorize one synchronous, already-confirmed destructive Git scope."""
    token = _destructive_git_authorized.set(True)
    try:
        yield
    finally:
        _destructive_git_authorized.reset(token)


def _reject_git_without_intent(popenargs: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    if _is_git_argv(_command_from(popenargs, kwargs)):
        raise GitIntentRequiredError("Git argv requires run_git() with an explicit intent")


def run(*popenargs: Any, **kwargs: Any) -> _subprocess.CompletedProcess[Any]:
    """Run a child with an explicit sanitized environment."""
    _reject_git_without_intent(popenargs, kwargs)
    kwargs["env"] = child_process_environment(kwargs.get("env"))
    return _subprocess.run(*popenargs, **kwargs)


def run_git(
    *popenargs: Any,
    intent: Literal["ordinary", "destructive"],
    **kwargs: Any,
) -> _subprocess.CompletedProcess[Any]:
    """Run Git with caller-declared intent and a sanitized environment."""
    if intent not in {"ordinary", "destructive"}:
        raise ValueError("Git intent must be 'ordinary' or 'destructive'")
    if not _is_git_argv(_command_from(popenargs, kwargs)):
        raise GitIntentRequiredError("run_git() requires Git argv")
    if intent == "destructive" and not _destructive_git_authorized.get():
        raise DestructiveGitCommandError("destructive Git command requires an explicit confirmed authorization scope")
    kwargs["env"] = child_process_environment(kwargs.get("env"))
    return _subprocess.run(*popenargs, **kwargs)


def Popen(*popenargs: Any, **kwargs: Any) -> _subprocess.Popen[Any]:
    """Start a child with an explicit sanitized environment."""
    _reject_git_without_intent(popenargs, kwargs)
    kwargs["env"] = child_process_environment(kwargs.get("env"))
    return _subprocess.Popen(*popenargs, **kwargs)
