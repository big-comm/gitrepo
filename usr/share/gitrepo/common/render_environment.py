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
    """Copy an environment while removing only GitRepo's renderer injection."""
    child = dict(os.environ if environment is None else environment)
    if child.get(GSK_RENDERER_MARKER) == "1":
        child.pop("GSK_RENDERER", None)
    child.pop(GSK_RENDERER_MARKER, None)
    return child
