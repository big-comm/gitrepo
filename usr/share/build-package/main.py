#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# main.py - Entry point for build_package application
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import sys
from rich.console import Console
from build_package import BuildPackage

def main():
    """Main entry point of the application"""
    console = Console()
    
    try:
        # Initialize and run the BuildPackage
        build_package = BuildPackage()
        build_package.run()
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user.[/]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Unhandled error: {e}[/]")
        sys.exit(1)

if __name__ == "__main__":
    main()