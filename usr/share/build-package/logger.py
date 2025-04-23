#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# logger.py - Logging management for build_package
#

import os
import sys
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from translation_utils import _

from rich.box import ROUNDED

from config import APP_NAME, APP_DESC, VERSION, LOG_DIR_BASE
# from translation_utils import _

class RichLogger:
    """Manages logs and formatted messages using the Rich library"""
    
    def __init__(self, use_colors: bool = True):
        self.use_colors = use_colors
        self.log_file = None
        self.console = Console()
    
    def setup_log_file(self, get_repo_name_func):
        """Sets up the log file"""
        repo_name = get_repo_name_func()
        if repo_name:
            log_dir = os.path.join(LOG_DIR_BASE, repo_name)
            os.makedirs(log_dir, exist_ok=True)
            self.log_file = os.path.join(log_dir, f"{APP_NAME}.log")
    
    def log(self, style: str, message: str):
        """Displays formatted message and saves to log"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Format message for display
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
            "bold": "bold"
        }
        
        rich_style = color_map.get(style, "white")
        
        # Display formatted message in console
        self.console.print(message, style=rich_style)
        
        # Save to log file (without colors)
        if self.log_file:
            with open(self.log_file, 'a') as f:
                f.write(f"[{timestamp}] {message}\n")
    
    def die(self, style: str, message: str, exit_code: int = 1):
        """Displays error message and exits the program"""
        self.log(style, f"{_('ERROR')}: {message}")
        sys.exit(exit_code)
    
    def draw_app_header(self):
        """Draws the stylized application header"""
        panel_width = 70  # Fixed width for the panel
        
        # Create title with centered text and blue background that extends edge-to-edge
        title_text = f"{APP_NAME.upper()} v{VERSION}"
        
        # Calculate inner width (panel width minus padding and borders)
        inner_width = panel_width - 4  # 2 chars on each side for borders and padding
        
        # Create a full-width blue background
        header_content = Text()
        header_content.append("\n")
        
        # Blue background with title text
        bg_text = " " * inner_width  # Full width background
        centered_text_pos = (inner_width - len(title_text)) // 2
        
        # Construct the line with centered text on blue background
        line = list(bg_text)
        for i, char in enumerate(title_text):
            if 0 <= centered_text_pos + i < len(line):
                line[centered_text_pos + i] = char
        
        # Create the text line with full blue background
        blue_bg_line = Text("".join(line), style="white on blue bold")
        header_content.append(blue_bg_line)
        
        # Add description on next line
        header_content.append("\n")
        desc_text = Text(f"{APP_DESC}", style="bright_cyan")
        # Center description
        header_content.append(" " * ((inner_width - len(APP_DESC)) // 2))
        header_content.append(desc_text)
        
        panel = Panel(
            header_content,
            box=ROUNDED,
            border_style="blue",
            padding=(0, 1),  # Reduced padding
            width=panel_width,
            title="BigCommunity"
        )
        
        self.console.print(panel)
    
    def display_summary(self, title: str, data: list):
        """Displays a formatted summary in a Rich table"""
        table = Table(show_header=False, box=ROUNDED, border_style="blue", padding=(0, 1))
        table.add_column(_("Field"), style="white")
        table.add_column(_("Value"), style="bright_cyan")
        
        for key, value in data:
            table.add_row(key, value)
        
        panel = Panel(
            table,
            title=title,
            box=ROUNDED,
            border_style="blue",
            padding=(1, 1),
            width=70  # Fixed width for consistency
        )
        
        self.console.print(panel)
        
    def format_branch_name(self, branch_name: str) -> str:
        """Formats branch names with consistent styling"""
        if branch_name.startswith('dev-'):
            branch_prefix = "dev-"
            timestamp = branch_name.replace('dev-', '')
            return f"[green bold]{branch_prefix}[/green bold][cyan bold]{timestamp}[/cyan bold]"
        else:
            return f"[cyan bold]{branch_name}[/cyan bold]"