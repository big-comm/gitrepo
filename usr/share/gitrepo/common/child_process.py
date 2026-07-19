"""Explicit subprocess boundary with GitRepo-private environment removed."""

from __future__ import annotations

import subprocess as _subprocess
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from .render_environment import child_process_environment


CalledProcessError = _subprocess.CalledProcessError
SubprocessError = _subprocess.SubprocessError
DEVNULL = _subprocess.DEVNULL
PIPE = _subprocess.PIPE
STDOUT = _subprocess.STDOUT

_destructive_git_authorized: ContextVar[bool] = ContextVar("destructive_git_authorized", default=False)


class DestructiveGitCommandError(PermissionError):
    """Raised when destructive Git argv reaches the process boundary unconfirmed."""


def _git_command_parts(command: object) -> tuple[str, list[str]] | None:
    if not isinstance(command, Sequence) or isinstance(command, (str, bytes)):
        return None
    argv = [str(part) for part in command]
    if len(argv) < 2 or Path(argv[0]).name != "git":
        return None

    index = 1
    while index < len(argv):
        argument = argv[index]
        if argument == "--":
            index += 1
            break
        if not argument.startswith("-"):
            break
        if argument in {"-C", "-c"}:
            index += 2
        else:
            index += 1

    if index >= len(argv):
        return None
    return argv[index], argv[index + 1 :]


def is_destructive_git_command(command: object) -> bool:
    """Return whether argv can discard local data or rewrite remote history."""
    parts = _git_command_parts(command)
    if parts is None:
        return False

    verb, arguments = parts
    options = set(arguments)
    has_force_flag = any(
        argument == "-f"
        or argument.startswith("--force")
        or (argument.startswith("-") and not argument.startswith("--") and "f" in argument[1:])
        for argument in arguments
    )
    has_destructive_refspec = any(argument.startswith(("+", ":")) for argument in arguments)
    return any(
        (
            verb == "reset" and "--hard" in options,
            verb == "clean" and has_force_flag,
            verb == "branch" and bool(options.intersection({"-D", "--delete", "--force"})),
            verb == "push" and (has_force_flag or "--delete" in options or has_destructive_refspec),
            verb == "stash" and bool(options.intersection({"drop", "clear"})),
            verb == "checkout" and "--" in options,
            verb == "restore" and "--staged" not in options,
            verb == "rm" and has_force_flag,
        )
    )


@contextmanager
def authorize_destructive_git() -> Iterator[None]:
    """Authorize one synchronous, already-confirmed destructive Git scope."""
    token = _destructive_git_authorized.set(True)
    try:
        yield
    finally:
        _destructive_git_authorized.reset(token)


def _guard_destructive_git(popenargs: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    command = popenargs[0] if popenargs else kwargs.get("args")
    if is_destructive_git_command(command) and not _destructive_git_authorized.get():
        raise DestructiveGitCommandError("destructive Git command requires an explicit confirmed authorization scope")


def run(*popenargs: Any, **kwargs: Any) -> _subprocess.CompletedProcess[Any]:
    """Run a child with an explicit sanitized environment."""
    _guard_destructive_git(popenargs, kwargs)
    kwargs["env"] = child_process_environment(kwargs.get("env"))
    return _subprocess.run(*popenargs, **kwargs)


def Popen(*popenargs: Any, **kwargs: Any) -> _subprocess.Popen[Any]:
    """Start a child with an explicit sanitized environment."""
    _guard_destructive_git(popenargs, kwargs)
    kwargs["env"] = child_process_environment(kwargs.get("env"))
    return _subprocess.Popen(*popenargs, **kwargs)
