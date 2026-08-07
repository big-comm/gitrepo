"""GTK renderer choice and child-environment isolation."""

from __future__ import annotations

import os
from collections.abc import Mapping


GSK_RENDERER_MARKER = "_GITREPO_GSK_RENDERER_INJECTED"


def configure_gtk_renderer(environment: dict[str, str] | None = None) -> bool:
    """Select Cairo only when no renderer was chosen outside GitRepo."""
    target = os.environ if environment is None else environment
    if "GSK_RENDERER" in target:
        return False
    target["GSK_RENDERER"] = "cairo"
    target[GSK_RENDERER_MARKER] = "1"
    return True


def child_process_environment(environment: Mapping[str, str] | None = None) -> dict[str, str]:
    """Copy an environment while removing only GitRepo's renderer injection.

    Credential prompts are also disabled: a child that asks for a password on a
    terminal nobody can see makes the whole interface hang with no cause, no
    timeout, and no way to answer. Failing is the recoverable outcome.
    """
    child = dict(os.environ if environment is None else environment)
    if child.get(GSK_RENDERER_MARKER) == "1":
        child.pop("GSK_RENDERER", None)
    child.pop(GSK_RENDERER_MARKER, None)
    # Only Git's own terminal prompt is suppressed. Credential helpers, SSH
    # agents, and a graphical askpass still answer normally, so this removes
    # the hang without removing any way the user already authenticates.
    child.setdefault("GIT_TERMINAL_PROMPT", "0")
    return child
