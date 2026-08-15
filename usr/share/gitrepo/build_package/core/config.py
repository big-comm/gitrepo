#
# core/config.py - Configuration file for build_package.py
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import os

# Import translation function
from gitrepo.common.translation import _

# Repository settings
DEFAULT_ORGANIZATION = "big-comm"  # Default organization
VALID_ORGANIZATIONS = ["big-comm", "biglinux"]  # Valid organizations

# File containing GitHub token (new location inside config dir)
TOKEN_FILE = "~/.config/gitrepo/github_token"
# Legacy location — kept only for one-time migration
TOKEN_FILE_LEGACY = "~/.GITHUB_TOKEN"

# Branch settings
VALID_BRANCHES = ["dev"]

# Log directory
LOG_DIR_BASE = os.path.join(
    os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "gitrepo", "build-package"
)

# Script version
APP_VERSION_OWNER = "gitrepo"
APP_VERSION = "4.1.13"
APP_NAME = _("BUILD PACKAGE")
APP_DESC = _(
    "A comprehensive tool for package building, testing, and deployment. Streamlines Git operations, automates builds and manages package workflows for BigCommunity repositories and AUR packages."
)
