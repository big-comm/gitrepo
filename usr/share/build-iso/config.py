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
    "talesam",
    "leoberbert"
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
    "https://github.com/leoberbert/iso-profiles"
]

# Default ISO profiles by organization
DEFAULT_ISO_PROFILES = {
    "big-comm": "https://github.com/big-comm/iso-profiles",
    "biglinux": "https://github.com/biglinux/iso-profiles",
    "leoberbert": "https://github.com/leoberbert/iso-profiles"
}

# API URLs for repositories
API_PROFILES = {
    "https://github.com/big-comm/iso-profiles": "https://api.github.com/repos/big-comm/iso-profiles/contents/",
    "https://github.com/biglinux/iso-profiles": "https://api.github.com/repos/biglinux/iso-profiles/contents/",
    "https://github.com/leoberbert/iso-profiles": "https://api.github.com/repos/leoberbert/iso-profiles/contents/"
}

# Organization mapping
ORGANIZATION_MAP = {
    "big-comm": "big-comm",       # Former bigcommunity
    "biglinux": "biglinux",
    "talesam": "talesam",
    "leoberbert": "leoberbert"
}

# =======================================================================================
# DEFAULT CONFIGURATIONS FOR AUTOMATIC MODE
# =======================================================================================
# To add a new organization, simply add an entry here following the same format
# as the existing ones. No need to modify the main code!
# 
# NOTE: Build directories and editions are now fetched dynamically from the 
# iso-profiles repository API, so no need for hardcoded lists anymore!
# =======================================================================================

ORG_DEFAULT_CONFIGS = {
    "big-comm": {
        "distroname": "bigcommunity",
        "iso_profiles_repo": "https://github.com/big-comm/iso-profiles",
        "branches": {
            "manjaro": "stable",
            "community": "stable", 
            "biglinux": "stable"
        },
        "kernel": "latest",
        "build_dir": "bigcommunity",
        "edition": "xfce"
    },
    
    "biglinux": {
        "distroname": "biglinux",
        "iso_profiles_repo": "https://github.com/biglinux/iso-profiles",
        "branches": {
            "manjaro": "stable",
            "community": "",
            "biglinux": "stable"
        },
        "kernel": "latest", 
        "build_dir": "biglinux",
        "edition": "kde"
    },
    
    "talesam": {
        "distroname": "bigcommunity",  # talesam builds BigCommunity
        "iso_profiles_repo": "https://github.com/big-comm/iso-profiles",
        "branches": {
            "manjaro": "stable",
            "community": "stable",
            "biglinux": "stable"
        },
        "kernel": "latest",
        "build_dir": "bigcommunity", 
        "edition": "xfce"
    },
    
    "leoberbert": {
        "distroname": "bigcommunity",  # leoberbert builds BigCommunity
        "iso_profiles_repo": "https://github.com/leoberbert/iso-profiles",
        "branches": {
            "manjaro": "stable",
            "community": "stable",
            "biglinux": "stable"
        },
        "kernel": "latest",
        "build_dir": "bigcommunity",
        "edition": "gnome"
    }
    
    # =======================================================================================
    # EXAMPLE: To add a new organization, uncomment and configure:
    # =======================================================================================
    # "your-organization": {
    #     "distroname": "bigcommunity",  # or "biglinux" or your own distro
    #     "iso_profiles_repo": "https://github.com/your-organization/iso-profiles", 
    #     "branches": {
    #         "manjaro": "stable",     # stable, testing, unstable
    #         "community": "stable",   # stable, testing, unstable (leave "" if not used)
    #         "biglinux": "stable"     # stable, testing, unstable (leave "" if not used)
    #     },
    #     "kernel": "latest",          # latest, lts, oldlts, xanmod
    #     "build_dir": "bigcommunity", # directory name in iso-profiles (will be validated via API)
    #     "edition": "xfce"            # xfce, kde, gnome, etc. (will be validated via API)
    # }
}

# Script version
VERSION = "3.0.3"
APP_NAME = _("BUILD ISO")
APP_DESC = _("Wrapper for ISO building using GitHub Actions. Streamlines the process of creating custom Linux distribution ISO images through automation.")