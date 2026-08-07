# intentional-log: this CLI menu renders choices and validation feedback to stdout.
#
# menu_system.py - Interactive menu system for build_iso
#

import os
from gitrepo.common import child_process as subprocess
import sys
import termios
import tty
from typing import Optional, Tuple

from rich.box import ROUNDED
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from gitrepo.common.translation import _


class MenuSystem:
    """Menu system using Rich"""

    def __init__(self, logger):
        self.logger = logger
        self.console = Console()

    @staticmethod
    def _option_markup(option: str, is_selected: bool) -> str:
        semantic_color = "red" if option == _("Exit") else "cyan" if option == _("Back") or "ISO" in option else "white"
        text_style = f"bold bright_{semantic_color}" if is_selected else f"dim {semantic_color}"
        bullet = "• " if is_selected else "  "
        bullet_style = "bold blue" if is_selected else "dim white"
        return f"[{bullet_style}]{bullet}[/][{text_style}]{option}[/]"

    def _draw_menu(self, title: str, options: list[str], selected_index: int) -> None:
        if os.name == "posix":
            subprocess.run(["clear"], check=False)
        self.logger.draw_app_header()
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

    def show_menu(self, title: str, options: list, default_index: int = 0) -> Optional[Tuple[int, str]]:
        """Display an arrow-key menu and return the selected semantic option."""
        current = default_index
        while True:
            self._draw_menu(title, options, current)
            current, is_done = self._next_selection(current, len(options))
            if is_done and current is None:
                return None
            if is_done:
                return current, options[current]

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

    def confirm(self, title: str) -> bool:
        """Displays a confirmation dialog"""
        return Confirm.ask(title, default=True)
