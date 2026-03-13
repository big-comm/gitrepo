#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# main_gui.py - Entry point for Build ISO GUI application
#

import sys
import os

# Ensure the project root is in PATH
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from gui.main_gui import main

if __name__ == "__main__":
    sys.exit(main())
