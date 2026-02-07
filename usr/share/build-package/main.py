#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# main.py - Entry point dispatcher for build_package application
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

"""
Main entry point for build_package application.
Automatically detects whether to run CLI or GUI interface based on:
- Command line arguments (CLI if present)
- Display environment (CLI if no DISPLAY)
- GTK availability (CLI fallback if GTK not available)
"""

import sys
import os
from typing import Literal
from core.translation_utils import _

def detect_interface_mode() -> Literal['cli', 'gui']:
    """
    Detects which interface mode to use based on environment and arguments.
    
    Returns:
        'cli' for command line interface
        'gui' for graphical interface
    """
    # Check for --cli or --no-gui flag FIRST (highest priority)
    if '--cli' in sys.argv or '--no-gui' in sys.argv:
        # Remove the flag so it doesn't interfere with argparse
        if '--cli' in sys.argv:
            sys.argv.remove('--cli')
        if '--no-gui' in sys.argv:
            sys.argv.remove('--no-gui')
        return 'cli'
    
    # Check for --gui flag to force GUI mode
    if '--gui' in sys.argv:
        sys.argv.remove('--gui')
        return 'gui'
    
    # If other command line arguments are provided, use CLI
    if len(sys.argv) > 1:
        return 'cli'
    
    # If no display environment, force CLI
    if not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):
        return 'cli'
    
    # Check if running in terminal-only environment
    if os.environ.get('TERM') and not os.environ.get('DESKTOP_SESSION'):
        return 'cli'
    
    # Default to GUI if environment supports it
    return 'gui'

def run_cli_interface():
    """Run the command line interface."""
    try:
        from cli.main_cli import main as cli_main
        cli_main()
    except ImportError as e:
        print(_("Error: Failed to import CLI components: {0}").format(e))
        sys.exit(1)
    except Exception as e:
        print(_("Error: CLI interface failed: {0}").format(e))
        sys.exit(1)

def run_gui_interface():
    """Run the graphical interface with fallback to CLI."""
    try:
        from gui.main_gui import main as gui_main
        gui_main()
    except ImportError as e:
        print(_("Warning: GTK4/Libadwaita not available: {0}").format(e))
        print(_("Falling back to CLI interface..."))
        run_cli_interface()
    except Exception as e:
        print(_("Error: GUI interface failed: {0}").format(e))
        print(_("Falling back to CLI interface..."))
        run_cli_interface()

def main():
    """Main application entry point."""
    interface_mode = detect_interface_mode()
    
    if interface_mode == 'cli':
        run_cli_interface()
    else:
        run_gui_interface()

if __name__ == "__main__":
    main()