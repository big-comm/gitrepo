#
# config.py - Configuration file for build_iso.py
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import os

# Import translation function
from gitrepo.common.translation import _

# Repository settings
APP_ID = "org.bigcommunity.buildiso"
DEFAULT_ORGANIZATION = "talesam"  # Default organization
VALID_ORGANIZATIONS = [
    # "big-comm",                              # Former communitybig
    "talesam",
    "bigbruno",
]

# Valid distros with display names
VALID_DISTROS = [
    "bigcommunity",  # Actual distro name
    "biglinux",
]

# Display names for distros (for UI)
DISTRO_DISPLAY_NAMES = {"bigcommunity": "BigCommunity", "biglinux": "BigLinux"}

# Branch settings
VALID_BRANCHES = ["stable", "testing", "unstable"]
BRANCH_DISPLAY_NAMES = {
    "stable": _("Stable"),
    "testing": _("Testing"),
    "unstable": _("Unstable"),
}
BRANCH_DESCRIPTIONS = {
    "stable": _("Tested packages. Recommended for images you will hand to other people."),
    "testing": _("Packages waiting for validation. Useful to preview the next stable set."),
    "unstable": _("Newest packages, closest to upstream. Expect breakage."),
}

# Desktop editions keep their proper product spelling in the interface.
EDITION_DISPLAY_NAMES = {
    "kde": "KDE Plasma",
    "gnome": "GNOME",
    "xfce": "Xfce",
    "cinnamon": "Cinnamon",
    "cosmic": "COSMIC",
    "deepin": "Deepin",
    "lxqt": "LXQt",
    "mate": "MATE",
    "budgie": "Budgie",
    "i3": "i3",
    "hyprland": "Hyprland",
}


def edition_display_name(edition: str) -> str:
    """Return the product spelling of an edition directory name."""
    return EDITION_DISPLAY_NAMES.get(edition.lower(), edition.capitalize())


# Kernel options
VALID_KERNELS = ["latest", "lts", "oldlts", "xanmod"]
KERNEL_DISPLAY_NAMES = {
    "lts": _("LTS (Recommended)"),
    "latest": _("Latest"),
    "oldlts": _("Old LTS"),
    "xanmod": _("XanMod"),
}

# Log directory
LOG_DIR_BASE = os.path.join(
    os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "gitrepo", "build-iso"
)

# ISO Profiles repositories
ISO_PROFILES = ["https://github.com/big-comm/iso-profiles", "https://github.com/biglinux/iso-profiles"]
ISO_PROFILES_REPOS = {
    "bigcommunity": "https://github.com/big-comm/iso-profiles",
    "biglinux": "https://github.com/biglinux/iso-profiles",
}

# Default ISO profiles by organization
DEFAULT_ISO_PROFILES = {
    "big-comm": "https://github.com/big-comm/iso-profiles",
    "biglinux": "https://github.com/biglinux/iso-profiles",
    "talesam": "https://github.com/big-comm/iso-profiles",  # talesam uses big-comm profiles
}

# API URLs for repositories
API_PROFILES = {
    "https://github.com/big-comm/iso-profiles": "https://api.github.com/repos/big-comm/iso-profiles/contents/",
    "https://github.com/biglinux/iso-profiles": "https://api.github.com/repos/biglinux/iso-profiles/contents/",
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
        "branches": {"manjaro": "stable", "community": "stable", "biglinux": "stable"},
        "kernel": "latest",
        "build_dir": "bigcommunity",
        "edition": "xfce",
    },
    "biglinux": {
        "distroname": "biglinux",
        "iso_profiles_repo": "https://github.com/biglinux/iso-profiles",
        "branches": {"manjaro": "stable", "community": "", "biglinux": "stable"},
        "kernel": "latest",
        "build_dir": "biglinux",
        "edition": "kde",
    },
    "talesam": {
        "distroname": "bigcommunity",  # talesam builds BigCommunity
        "iso_profiles_repo": "https://github.com/big-comm/iso-profiles",
        "branches": {"manjaro": "stable", "community": "stable", "biglinux": "stable"},
        "kernel": "latest",
        "build_dir": "bigcommunity",
        "edition": "gnome",
    },
    "bigbruno": {
        # The distroname names the profile directory inside iso_profiles_repo,
        # so biglinux profiles mean a biglinux build.
        "distroname": "biglinux",
        "iso_profiles_repo": "https://github.com/biglinux/iso-profiles",
        "branches": {"manjaro": "stable", "community": "", "biglinux": "stable"},
        "kernel": "latest",
        "build_dir": "biglinux",
        "edition": "kde",
    },
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
APP_VERSION = "3.8.1"
APP_NAME = _("BUILD ISO")
APP_DISPLAY_NAME = _("Build ISO")
APP_DESC = _(
    "Wrapper for ISO building using GitHub Actions. Streamlines the process of creating custom Linux distribution ISO images through automation."
)

# =============================================================================
# LOCAL BUILD SETTINGS
# =============================================================================

BUILD_MODE_REMOTE = "remote"
BUILD_MODE_LOCAL = "local"

DEFAULT_OUTPUT_DIR = os.path.expanduser("~/ISO")
XDG_CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
CONFIG_DIR = os.path.join(XDG_CONFIG_HOME, "gitrepo")
CONFIG_FILE = os.path.join(CONFIG_DIR, "build-iso.json")
HISTORY_FILE = os.path.join(CONFIG_DIR, "build-iso-history.json")
LEGACY_CLI_CONFIG_FILE = os.path.expanduser("~/.config/build-iso/config.json")
LEGACY_GUI_CONFIG_FILE = os.path.expanduser("~/.config/build-iso-gui/settings.json")

# Compatibility aliases for callers that still name the old CLI store.
LOCAL_CONFIG_DIR = os.path.dirname(LEGACY_CLI_CONFIG_FILE)
LOCAL_CONFIG_FILE = os.path.join(LOCAL_CONFIG_DIR, "config.json")

# Container settings (following edition.yml)
CONTAINER_IMAGE = "talesam/community-build:latest"
# The ISO build engine lives inside BigLinux's iso-profiles (build-iso/), next
# to the profiles it interprets. It is the same code the GitLab pipeline and
# the GitHub workflow run. Distributions with their own profiles repository
# still build through this engine (PROFILES_ROOT override, see its header).
BUILD_ENGINE_REPO = "https://github.com/biglinux/iso-profiles"
