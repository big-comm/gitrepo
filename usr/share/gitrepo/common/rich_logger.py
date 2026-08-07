"""Rich console and file logger shared by both command-line applications."""

# intentional-log: terminal output and the optional repository log are this class's public contract.

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from rich.box import ROUNDED
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .diagnostic_redaction import redact_diagnostic
from .translation import _


class RichLogger:
    """Render CLI messages and optionally append them to a repository log."""

    def __init__(self, app_name: str, app_description: str, log_dir: str, *, use_colors: bool = True) -> None:
        self.app_name = app_name
        self.app_description = app_description
        self.log_dir = Path(log_dir)
        self.log_file: Path | None = None
        self.console = Console(no_color=not use_colors)

    def setup_log_file(self, get_repo_name: Callable[[], str]) -> None:
        repo_name = get_repo_name()
        if not repo_name:
            return
        directory = self.log_dir / repo_name
        directory.mkdir(parents=True, exist_ok=True)
        self.log_file = directory / f"{self.app_name}.log"

    def log(self, style: str, message: str) -> None:
        color_map = {
            "cyan": "bright_cyan",
            "blue_dark": "blue",
            "medium_blue": "blue",
            "light_blue": "cyan",
            "white": "white",
            "red": "red",
            "yellow": "yellow",
            "green": "green",
            "orange": "yellow",
            "purple": "magenta",
            "black": "black",
            "bold": "bold",
        }
        safe_message = redact_diagnostic(message)
        self.console.print(
            safe_message,
            style=color_map.get(style, "white"),
            # Child output reaches this logger, and '[new branch]' is not
            # markup; interpreting it silently drops text or raises.
            markup=False,
        )
        if self.log_file:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self.log_file.open("a", encoding="utf-8") as stream:
                stream.write(f"[{timestamp}] {safe_message}\n")

    def die(self, style: str, message: str, exit_code: int = 1) -> None:
        self.log(style, f"{_('ERROR')}: {message}")
        raise SystemExit(exit_code)

    def draw_app_header(self) -> None:
        panel_width = 70
        inner_width = panel_width - 4
        title = self.app_name.upper()
        line = list(" " * inner_width)
        title_start = (inner_width - len(title)) // 2
        line[title_start : title_start + len(title)] = title

        content = Text("\n")
        content.append(Text("".join(line), style="white on blue bold"))
        content.append("\n")
        content.append(" " * max(0, (inner_width - len(self.app_description)) // 2))
        content.append(Text(self.app_description, style="bright_cyan"))
        self.console.print(
            Panel(content, box=ROUNDED, border_style="blue", padding=(0, 1), width=panel_width, title="BigCommunity")
        )

    def display_summary(self, title: str, data: Sequence[tuple[str, str]]) -> None:
        table = Table(show_header=False, box=ROUNDED, border_style="blue", padding=(0, 1))
        table.add_column(_("Field"), style="white")
        table.add_column(_("Value"), style="bright_cyan")
        for key, value in data:
            table.add_row(key, value)
        self.console.print(Panel(table, title=title, box=ROUNDED, border_style="blue", padding=(1, 1), width=70))

    @staticmethod
    def format_branch_name(branch_name: str) -> str:
        if branch_name.startswith("dev-"):
            suffix = branch_name.removeprefix("dev-")
            return f"[green bold]dev-[/green bold][cyan bold]{suffix}[/cyan bold]"
        return f"[cyan bold]{branch_name}[/cyan bold]"
