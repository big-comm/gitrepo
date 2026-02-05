#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# main.py - Entry point for build_iso application
#

import sys
from rich.console import Console
from build_iso import BuildISO
from translation_utils import _

import traceback

def debug_hook(type, value, tb):
    print("\nERRO DETALHADO:")
    traceback.print_exception(type, value, tb)
    print("\n")

sys.excepthook = debug_hook

def main():
    """Main entry point of the application"""
    console = Console()
    
    try:
        # Initialize and run the BuildISO
        build_iso = BuildISO()
        build_iso.run()
    except KeyboardInterrupt:
        console.print(_("Operation cancelled by user."), style="yellow")
        sys.exit(1)
    except Exception as e:
        console.print(_("Unhandled error: {0}").format(str(e)), style="red", markup=False)
        sys.exit(1)

if __name__ == "__main__":
    main()