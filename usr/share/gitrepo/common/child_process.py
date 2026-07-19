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


def _git_command_parts(command: object) -> tuple[str, list[str], list[str]] | None:
    if not isinstance(command, Sequence) or isinstance(command, (str, bytes)):
        return None
    argv = [str(part) for part in command]
    if len(argv) < 2 or Path(argv[0]).name != "git":
        return None

    configurations = []
    index = 1
    while index < len(argv):
        argument = argv[index]
        if argument == "--":
            index += 1
            break
        if not argument.startswith("-"):
            break
        if argument in {"-C", "-c"}:
            if argument == "-c" and index + 1 < len(argv):
                configurations.append(argv[index + 1])
            index += 2
        else:
            index += 1

    if index >= len(argv):
        return None
    return argv[index], argv[index + 1 :], configurations


def _git_operands(arguments: list[str], options_with_values: set[str]) -> list[str]:
    operands = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            operands.extend(arguments[index + 1 :])
            break
        option = argument.split("=", 1)[0]
        if option in options_with_values:
            index += 1 if "=" in argument else 2
        elif argument.startswith("-"):
            index += 1
        else:
            operands.append(argument)
            index += 1
    return operands


def _git_push_refspecs(arguments: list[str]) -> list[str]:
    repository_is_option = any(argument == "--repo" or argument.startswith("--repo=") for argument in arguments)
    operands = _git_operands(
        arguments,
        {"--repo", "--receive-pack", "--exec", "--recurse-submodules", "-o", "--push-option"},
    )
    return operands if repository_is_option else operands[1:]


def is_destructive_git_command(command: object) -> bool:
    """Return whether argv can discard local data or rewrite remote history."""
    parts = _git_command_parts(command)
    if parts is None:
        return False

    verb, arguments, configurations = parts
    options = set(arguments)
    has_force_flag = any(
        argument == "-f"
        or argument.startswith("--force")
        or (argument.startswith("-") and not argument.startswith("--") and "f" in argument[1:])
        for argument in arguments
    )
    clean_options = arguments[: arguments.index("--")] if "--" in arguments else arguments
    clean_has_force = any(
        argument == "-f"
        or argument.startswith("--force")
        or (argument.startswith("-") and not argument.startswith("--") and "f" in argument[1:])
        for argument in clean_options
    )
    clean_has_dry_run = "--dry-run" in clean_options or any(
        argument.startswith("-") and not argument.startswith("--") and "n" in argument[1:] for argument in clean_options
    )
    clean_has_interactive = "--interactive" in clean_options or any(
        argument.startswith("-") and not argument.startswith("--") and "i" in argument[1:] for argument in clean_options
    )
    clean_force_disabled = False
    for configuration in configurations:
        name, separator, value = configuration.partition("=")
        if name.casefold() == "clean.requireforce":
            clean_force_disabled = bool(separator) and value.casefold() in {"false", "no", "off", "0"}
    push_refspecs = _git_push_refspecs(arguments) if verb == "push" else []
    has_destructive_refspec = any(refspec.startswith(("+", ":")) for refspec in push_refspecs)
    checkout_operands = _git_operands(
        arguments,
        {"-b", "-B", "--conflict", "--orphan", "-U", "--unified", "--inter-hunk-context", "--pathspec-from-file"},
    )
    return any(
        (
            verb == "reset" and "--hard" in options,
            verb == "clean"
            and (clean_has_force or clean_force_disabled)
            and not (clean_has_dry_run or clean_has_interactive),
            verb == "branch" and bool(options.intersection({"-D", "--delete", "--force"})),
            verb == "push" and (has_force_flag or "--delete" in options or has_destructive_refspec),
            verb == "stash" and bool(options.intersection({"drop", "clear"})),
            verb == "checkout" and (has_force_flag or "--" in options or len(checkout_operands) > 1),
            verb == "restore" and ("--staged" not in options or "--worktree" in options),
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
