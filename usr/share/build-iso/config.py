#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# config.py - Configuration file for build_iso.py
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

# Import translation function
from translation_utils import _

# Repository settings
REPO_WORKFLOW = "big-comm/build-iso"        # Repository containing workflows
DEFAULT_ORGANIZATION = "big-comm"            # Default organization
VALID_ORGANIZATIONS = [
    "big-comm",                              # Former communitybig
    "biglinux",
    "talesam"
]

# Valid distros with display names
VALID_DISTROS = [
    "bigcommunity",                          # Actual distro name
    "biglinux"
]

# Display names for distros (for UI)
DISTRO_DISPLAY_NAMES = {
    "bigcommunity": "BigCommunity",
    "biglinux": "BigLinux"
}

# Organization to distro mapping
ORG_TO_DISTRO_MAP = {
    "big-comm": "bigcommunity",
    "biglinux": "biglinux",
    "talesam": "bigcommunity"  # Talesam builds BigCommunity
}

# File containing GitHub token
TOKEN_FILE = "~/.GITHUB_TOKEN"

# Branch settings
VALID_BRANCHES = ["stable", "testing", "unstable"]

# Kernel options
VALID_KERNELS = ["latest", "lts", "oldlts", "xanmod"]

# Log directory
LOG_DIR_BASE = "/tmp/build-iso"

# ISO Profiles repositories
ISO_PROFILES = [
    "https://github.com/big-comm/iso-profiles",
    "https://github.com/biglinux/iso-profiles",
    # "https://github.com/talesam/iso-profiles"
]

# Default ISO profiles by organization
DEFAULT_ISO_PROFILES = {
    "big-comm": "https://github.com/big-comm/iso-profiles",
    "biglinux": "https://github.com/biglinux/iso-profiles",
    # "talesam": "https://github.com/big-comm/iso-profiles"
}

# API URLs for repositories
API_PROFILES = {
    "https://github.com/big-comm/iso-profiles": "https://api.github.com/repos/big-comm/iso-profiles/contents/",
    "https://github.com/biglinux/iso-profiles": "https://api.github.com/repos/biglinux/iso-profiles/contents/",
    # "https://github.com/talesam/iso-profiles": "https://api.github.com/repos/talesam/iso-profiles/contents/"
}

# Organization mapping
ORGANIZATION_MAP = {
    "big-comm": "big-comm",       # Former bigcommunity
    "biglinux": "biglinux",
    "talesam": "talesam"
}

# Edition options for different distros
BIGCOMM_EDITIONS = ["cinnamon", "cosmic", "deepin", "gnome", "kde", "xfce", "wmaker"]
BIGLINUX_EDITIONS = ["base", "FalaQueEuTeEscuto", "flisol", "kde", "small", "xivastudio"]
TALESAM_EDITIONS = ["cinnamon", "cosmic", "deepin", "gnome", "kde", "xfce", "wmaker"]

# Build dirs for different distros
BIGCOMM_BUILD_DIRS = ["bigcommunity"]
BIGLINUX_BUILD_DIRS = ["biglinux", "biglinux-make-iso-profiles"]
TALESAM_BUILD_DIRS = ["bigcommunity"]

# Script version
VERSION = "3.0.0"
APP_NAME = _("BUILD ISO")
APP_DESC = _("Wrapper for ISO building using GitHub Actions. Streamlines the process of creating custom Linux distribution ISO images through automation.")