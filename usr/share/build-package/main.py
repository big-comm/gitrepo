#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# main.py - Entry point for build_package application
#

import sys
from rich.console import Console
from build_package import BuildPackage
from translation_utils import _

def main():
    """Main entry point of the application"""
    console = Console()
    
    try:
        # Initialize and run the BuildPackage
        build_package = BuildPackage()
        build_package.run()
    except KeyboardInterrupt:
        console.print("\n[yellow]" + _("Operation cancelled by user.") + "[/]")
        sys.exit(1)
    except Exception as e:
        console.print("[red]" + _("Unhandled error: {0}").format(e) + "[/]")
        sys.exit(1)

if __name__ == "__main__":
    main()