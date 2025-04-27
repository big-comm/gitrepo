#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# menu_system.py - Interactive menu system for build_iso
#

import os
import sys
import termios
import tty
from typing import Optional, Tuple
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from translation_utils import _
from rich.box import ROUNDED

class MenuSystem:
    """Menu system using Rich"""
    
    def __init__(self, logger):
        self.logger = logger
        self.console = Console()
    
    def show_menu(self, title: str, options: list, default_index: int = 0) -> Optional[Tuple[int, str]]:
        """Displays an interactive menu using Rich"""
        import sys
        
        # Function to draw the menu
        def draw_menu(selected_index):
            # Clear screen
            os.system('clear' if os.name == 'posix' else 'cls')
            
            # Display header
            self.logger.draw_app_header()
            
            # Build menu content
            content = ""
            for i, option in enumerate(options):
                # Determine text style based on selection state
                if i == selected_index:
                    # Selected item - make it brighter without background
                    if "ISO" in option:
                        text_style = "bold bright_cyan"
                    elif option == _("Exit"):
                        text_style = "bold red"
                    elif option == _("Back"):
                        text_style = "bold bright_cyan"
                    else:
                        text_style = "bold bright_white"
                    
                    # Bullet for selected item
                    bullet = "• "
                    bullet_style = "bold blue"
                else:
                    # Unselected item - dimmer
                    if "ISO" in option:
                        text_style = "dim cyan"
                    elif option == _("Exit"):
                        text_style = "dim red"
                    elif option == _("Back"):
                        text_style = "dim cyan"
                    else:
                        text_style = "dim white"
                    
                    # No bullet for unselected
                    bullet = "  "
                    bullet_style = "dim white"
                
                # Add to content
                content += f"[{bullet_style}]{bullet}[/][{text_style}]{option}[/]\n"
            
            # Remove last line break
            if content.endswith("\n"):
                content = content[:-1]
            
            # Create panel for menu
            menu_panel = Panel(
                content,
                title=title,
                border_style="blue",
                box=ROUNDED,
                padding=(1, 2),
                width=70  # Fixed panel width
            )
            
            # Draw menu
            self.console.print(menu_panel)
            
            # Navigation hint with purple color but white arrows
            nav_text = _("Use [white]arrow keys ↑↓[/] to navigate, [white]Enter[/] to select, [white]ESC[/] to exit")
            self.console.print(f"\n[#9966cc]{nav_text}[/]")
            
        # Initial menu draw
        current = default_index
        draw_menu(current)
        
        # Direct key input without terminal manipulation
        while True:
            key = self._getch()
            
            # Process keys
            if key == b'\x1b':  # ESC key
                # Check for arrow key sequences
                key2 = self._getch()
                if key2 == b'[':
                    key3 = self._getch()
                    if key3 == b'A':  # Up arrow
                        current = (current - 1) % len(options)
                        draw_menu(current)
                    elif key3 == b'B':  # Down arrow
                        current = (current + 1) % len(options)
                        draw_menu(current)
                else:
                    return None  # ESC pressed
            elif key in (b'\r', b'\n'):  # Enter key
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