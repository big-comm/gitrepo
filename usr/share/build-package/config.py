#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# config.py - Configuration file for build_package.py
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

# Repository settings
REPO_WORKFLOW = "big-comm/build-package"        # Repository containing workflows
DEFAULT_ORGANIZATION = "big-comm"               # Default organization
VALID_ORGANIZATIONS = ["big-comm", "biglinux"]  # Valid organizations

# File containing GitHub token
TOKEN_FILE = "~/.GITHUB_TOKEN"

# Branch settings
VALID_BRANCHES = ["testing", "stable", "extra"]

# Log directory
LOG_DIR_BASE = "/tmp/build-package"

# Colors for text formatting
COLORS = {
    "blue_dark": "\033[1;38;5;33m",    # Bold dark blue
    "medium_blue": "\033[1;38;5;32m",  # Bold medium blue
    "light_blue": "\033[1;38;5;39m",   # Bold light blue
    "cyan": "\033[1;38;5;45m",         # Bold cyan
    "white": "\033[1;97m",             # Bold white
    "red": "\033[1;31m",               # Bold red for errors
    "yellow": "\033[1;33m",            # Bold yellow for warnings
    "green": "\033[1;32m",             # Bold green for success
    "orange": "\033[38;5;208m",        # Orange
    "purple": "\033[1;35m",            # Purple
    "black": "\033[30m",               # Black
    "bold": "\033[1m",                 # Bold
    "reset": "\033[0m",                # Reset text formatting
}

# Script version
VERSION = "3.0.0"
APP_NAME = "BUILD PACKAGE"
APP_DESC = "A comprehensive tool for package building, testing, and deployment. Streamlines Git operations, automates builds and manages package workflows for BigCommunity repositories and AUR packages."