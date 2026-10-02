# intentional-log: this CLI menu renders choices and validation feedback to stdout.
#
# cli/cli_menu.py - Interactive menu system for CLI interface
#

import sys
import termios
import tty
from typing import Optional, Tuple

from gitrepo.common import child_process as subprocess
from gitrepo.common.translation import _
from rich.box import ROUNDED
from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text

# Header, panel frame, counter and key help take about this many lines; the
# package list scrolls within what remains, two lines per package.
_PACKAGE_LIST_CHROME_LINES = 16


class MenuSystem:
    """Menu system using Rich"""

    def __init__(self, logger):
        self.logger = logger
        self.console = Console()

    @staticmethod
    def _option_markup(option: str, is_selected: bool) -> str:
        semantic_color = "cyan" if "AUR" in option or option == _("Back") else "red" if option == _("Exit") else "white"
        text_style = f"bold bright_{semantic_color}" if is_selected else f"dim {semantic_color}"
        bullet = "• " if is_selected else "  "
        bullet_style = "bold blue" if is_selected else "dim white"
        return f"[{bullet_style}]{bullet}[/][{text_style}]{option}[/]"

    def _draw_menu(self, title: str, options: list[str], selected_index: int, additional_content: str | None) -> None:
        subprocess.run(["clear"], check=False)
        self.logger.draw_app_header()
        if additional_content:
            self.console.print(additional_content)
            self.console.print()
        content = "\n".join(
            self._option_markup(option, index == selected_index) for index, option in enumerate(options)
        )
        self.console.print(Panel(content, title=title, border_style="blue", box=ROUNDED, padding=(1, 2), width=70))
        self.console.print(_("Use arrow keys to navigate, Enter to select, or Escape to return."))

    def _next_selection(self, current: int, option_count: int):
        key = self._getch()
        if key in (b"\r", b"\n"):
            return current, True
        if key != b"\x1b":
            return current, False
        if self._getch() != b"[":
            return None, True
        direction = self._getch()
        offset = -1 if direction == b"A" else 1 if direction == b"B" else 0
        return (current + offset) % option_count, False

    def show_menu(
        self, title: str, options: list, default_index: int = 0, additional_content: str = None
    ) -> Optional[Tuple[int, str]]:
        """Display an arrow-key menu and return the selected semantic option."""
        current = default_index
        while True:
            self._draw_menu(title, options, current, additional_content)
            current, is_done = self._next_selection(current, len(options))
            if is_done and current is None:
                return None
            if is_done:
                return current, options[current]

    def _read_package_key(self):
        """Return one of up, down, toggle, all, none, confirm, cancel -- or None."""
        key = self._getch()
        simple = {b" ": "toggle", b"a": "all", b"A": "all", b"n": "none", b"N": "none", b"q": "cancel"}
        if key in (b"\r", b"\n"):
            return "confirm"
        if key in simple:
            return simple[key]
        if key != b"\x1b":
            return None
        if self._getch() != b"[":
            return "cancel"
        return {b"A": "up", b"B": "down"}.get(self._getch())

    def _package_rows(self, selection, current: int) -> Group:
        visible = max(3, (self.console.size.height - _PACKAGE_LIST_CHROME_LINES) // 2)
        first = min(max(0, current - visible // 2), max(0, len(selection.choices) - visible))
        rows = []
        for index, choice in enumerate(selection.choices[first : first + visible], start=first):
            is_current = index == current
            mark = "[x]" if selection.is_selected(choice.directory) else "[ ]"
            # Text, not markup: a directory is shown exactly as it is named.
            line = Text("› " if is_current else "  ", style="bold blue")
            line.append(f"{mark} ", style="bold green" if selection.is_selected(choice.directory) else "dim")
            line.append(choice.directory, style="bold bright_white" if is_current else "white")
            rows.append(line)
            rows.append(Text(f"      {choice.description}", style="dim", no_wrap=True, overflow="ellipsis"))
        if first or first + visible < len(selection.choices):
            rows.append(Text(_("  … {0} packages in total").format(len(selection.choices)), style="dim"))
        rows.append(Text(""))
        rows.append(Text(selection.count_text(), style="bold cyan"))
        return Group(*rows)

    def _draw_package_selection(self, title: str, selection, current: int) -> None:
        subprocess.run(["clear"], check=False)
        self.logger.draw_app_header()
        self.console.print(
            Panel(self._package_rows(selection, current), title=title, border_style="blue", box=ROUNDED, padding=(1, 2))
        )
        self.console.print(
            _("Arrows move, Space marks, A marks all, N unmarks all, Enter builds the marked ones, Escape cancels.")
        )

    def _resolve_build_order(self, selection):
        """Ask before building the main package together with the ones that need it.

        Returns the directories to build, or None to go back to the list.
        """
        options = [selection.only_main_label(), _("Build all anyway"), _("Back")]
        warning = Text(selection.order_warning_text(), style="yellow")
        result = self.show_menu(_("Build order"), options, default_index=0, additional_content=warning)
        if not result or result[0] == 2:
            return None
        return [selection.main] if result[0] == 0 else selection.selected_directories()

    def choose_packages(self, selection) -> Optional[list]:
        """Let the user mark several packages; return their directories, or None if cancelled."""
        title = _("This repository holds several packages. Which ones should be built?")
        actions = {"all": selection.select_all, "none": selection.clear}
        current = 0
        while True:
            self._draw_package_selection(title, selection, current)
            action = self._read_package_key()
            count = len(selection.choices)
            if action == "cancel":
                return None
            if action in ("up", "down"):
                current = (current + (-1 if action == "up" else 1)) % count
            elif action == "toggle":
                selection.toggle(selection.choices[current].directory)
            elif action in actions:
                actions[action]()
            elif action == "confirm" and selection.can_confirm:
                if not selection.needs_order_warning:
                    return selection.selected_directories()
                directories = self._resolve_build_order(selection)
                if directories:
                    return directories

    def _getch(self):
        """Gets a single character from standard input without echo"""
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.buffer.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch

    def confirm(self, title: str, default_yes: bool = True) -> bool:
        """Displays a confirmation dialog"""
        return Confirm.ask(Text(str(title)), default=default_yes)
