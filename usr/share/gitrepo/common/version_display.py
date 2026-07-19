"""Render the version and license notice shared by the terminal applications."""

# intentional-log: rendering the requested version information is this module's public contract.

from rich.box import ROUNDED
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .translation import _


def print_version_panel(
    console: Console,
    *,
    app_name: str,
    app_version: str,
    app_description: str,
) -> None:
    """Print one localized version panel without whitespace-sensitive fragments."""
    version_text = Text()
    version_text.append(f"{app_name} v{app_version}\n", style="bold cyan")
    version_text.append(f"{app_description}\n\n", style="white")
    version_text.append(_("Copyright (C) 2024-2025 BigCommunity Team\n\n"), style="blue")
    version_text.append(
        _("This is free software: you are free to modify and redistribute it."),
        style="white",
    )
    version_text.append("\n", style="white")
    version_text.append(
        _(
            "{0} is provided to you under the MIT License and includes open source software under a variety of "
            "other licenses.\nYou can read instructions about how to download and build for yourself\n"
            "the specific source code used to create this copy."
        ).format(app_name),
        style="white",
    )
    version_text.append("\n", style="white")
    version_text.append(_("This program comes with absolutely NO warranty."), style="red")

    console.print(Panel(version_text, box=ROUNDED, border_style="blue", padding=(1, 2)))
