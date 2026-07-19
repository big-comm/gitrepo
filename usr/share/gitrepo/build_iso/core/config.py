#
# core/config.py - Configuration constants for Build ISO GUI
#

from gitrepo.build_iso.config import (
    APP_DISPLAY_NAME as APP_NAME,
    APP_ID,
    APP_VERSION,
    BUILD_ISO_REPO,
    CONFIG_DIR,
    CONFIG_FILE,
    CONTAINER_IMAGE,
    DEFAULT_OUTPUT_DIR,
    DISTRO_DISPLAY_NAMES as VALID_DISTROS,
    HISTORY_FILE,
    ISO_PROFILES_REPOS,
    KERNEL_DISPLAY_NAMES as VALID_KERNELS,
    VALID_BRANCHES,
)


__all__ = [
    "API_PROFILES",
    "APP_DESCRIPTION",
    "APP_ID",
    "APP_NAME",
    "APP_VERSION",
    "BUILD_ISO_REPO",
    "CONFIG_DIR",
    "CONFIG_FILE",
    "CONTAINER_IMAGE",
    "DEFAULT_EDITIONS",
    "DEFAULT_OUTPUT_DIR",
    "EXCLUDED_EDITIONS",
    "HISTORY_FILE",
    "ISO_PROFILES_REPOS",
    "VALID_BRANCHES",
    "VALID_DISTROS",
    "VALID_KERNELS",
]


APP_DESCRIPTION = "Build BigCommunity and BigLinux ISO images"

# API URLs for fetching editions dynamically
API_PROFILES = {
    "bigcommunity": "https://api.github.com/repos/big-comm/iso-profiles/contents/bigcommunity",
    "biglinux": "https://api.github.com/repos/biglinux/iso-profiles/contents/biglinux",
}

# Default editions per distro (fallback if API unavailable)
DEFAULT_EDITIONS = {
    "bigcommunity": ["gnome", "kde", "xfce", "cinnamon", "cosmic", "deepin"],
    "biglinux": ["kde", "gnome", "xfce", "cinnamon"],
}

# Editions excluded from build selection (development/incomplete profiles)
EXCLUDED_EDITIONS = ["hyprland", "core", "minimal"]
