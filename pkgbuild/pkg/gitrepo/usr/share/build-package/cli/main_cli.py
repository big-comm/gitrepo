#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# cli/main_cli.py - Entry point for CLI interface
#

import sys
import os
import traceback
from rich.console import Console

# Add the project root directory to the Python path
# This allows importing modules like 'core' from anywhere in the project
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from cli.logger import RichLogger
from cli.menu_system import MenuSystem
from core.build_package import BuildPackage
from core.translation_utils import _

def main():
    """Main entry point of the CLI application"""
    
    console = Console()
    
    try:
        # Create CLI-specific logger and menu system
        logger = RichLogger(use_colors=True)  # CLI always uses colors by default
        menu = MenuSystem(logger)
        
        # Initialize and run the BuildPackage with CLI dependencies
        build_package = BuildPackage(logger=logger, menu_system=menu)
        build_package.run()
        
    except KeyboardInterrupt:
        console.print("\n[yellow]" + _("Operation cancelled by user.") + "[/]")
        sys.exit(1)
    except Exception as e:
        console.print("[red]" + _("Unhandled error: {0}").format(e) + "[/]")
        traceback.print_exc() # Added for better debugging
        sys.exit(1)

if __name__ == "__main__":
    main()