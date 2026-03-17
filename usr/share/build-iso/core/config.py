#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# core/config.py - Configuration constants for Build ISO GUI
#

import os

# Application info
APP_ID = "org.bigcommunity.buildiso"
APP_NAME = "Build ISO"
APP_VERSION = "3.1.5"
APP_DESCRIPTION = "Build BigCommunity and BigLinux ISO images"

# Valid options
VALID_DISTROS = {
    "bigcommunity": "BigCommunity",
    "biglinux": "BigLinux",
}

VALID_KERNELS = {
    "lts": "LTS (Recommended)",
    "latest": "Latest",
    "oldlts": "Old LTS",
    "xanmod": "XanMod",
}

VALID_BRANCHES = ["stable", "testing", "unstable"]

# ISO Profiles repositories
ISO_PROFILES_REPOS = {
    "bigcommunity": "https://github.com/big-comm/iso-profiles",
    "biglinux": "https://github.com/biglinux/iso-profiles",
}

# API URLs for fetching editions dynamically
API_PROFILES = {
    "bigcommunity": "https://api.github.com/repos/big-comm/iso-profiles/contents/bigcommunity",
    "biglinux": "https://api.github.com/repos/biglinux/iso-profiles/contents/biglinux",
}

# Container settings
CONTAINER_IMAGE = "talesam/community-build:latest"
BUILD_ISO_REPO = "https://github.com/talesam/build-iso.git"

# Paths
DEFAULT_OUTPUT_DIR = os.path.expanduser("~/ISO")
CONFIG_DIR = os.path.expanduser("~/.config/build-iso-gui")
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")
HISTORY_FILE = os.path.join(CONFIG_DIR, "history.json")

# Build directory mapping
DISTRO_BUILD_DIR = {
    "bigcommunity": "bigcommunity",
    "biglinux": "biglinux",
}

# Default editions per distro (fallback if API unavailable)
DEFAULT_EDITIONS = {
    "bigcommunity": ["gnome", "kde", "xfce", "cinnamon", "cosmic", "deepin"],
    "biglinux": ["kde", "gnome", "xfce", "cinnamon"],
}

# Editions excluded from build selection (development/incomplete profiles)
EXCLUDED_EDITIONS = ["hyprland", "core", "minimal"]
