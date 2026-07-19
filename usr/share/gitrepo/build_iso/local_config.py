#
# local_config.py - Configuration management for local ISO builds
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import os

from gitrepo.build_iso.core.settings import Settings


class LocalConfig:
    """Flat terminal adapter over the canonical Build ISO settings store."""

    DEFAULT_CONFIG = {
        "output_dir": os.path.expanduser("~/ISO"),
        "distroname": "bigcommunity",
        "edition": "gnome",
        "manjaro_branch": "stable",
        "biglinux_branch": "stable",
        "bigcommunity_branch": "stable",
        "kernel": "lts",
    }

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.last_load_error = self.settings.last_load_error
        self.config = self.load_config()

    def load_config(self) -> dict[str, str]:
        return self.settings.local_values()

    def save_config(self, config_dict: dict[str, str]) -> bool:
        if not self.settings.set_local_values(config_dict):
            return False
        self.config = self.load_config()
        return True

    def get_output_dir(self) -> str:
        """Get the configured output directory"""
        return self.config.get("output_dir", self.DEFAULT_CONFIG["output_dir"])

    def set_output_dir(self, path: str) -> bool:
        """Validate and save new output directory"""
        # Expand user path
        expanded_path = os.path.expanduser(path)

        # Validate path
        if not expanded_path or expanded_path.strip() == "":
            return False

        # Try to create directory if it doesn't exist
        try:
            os.makedirs(expanded_path, exist_ok=True)
        except (IOError, OSError):
            return False

        # Check if directory is writable
        if not os.access(expanded_path, os.W_OK):
            return False

        # Save to config
        return self.save_config({"output_dir": expanded_path})
