#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# local_config.py - Configuration management for local ISO builds
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import os
import json
from translation_utils import _

class LocalConfig:
    """Manages local build configuration stored in ~/.config/build-iso/config.json"""

    CONFIG_DIR = os.path.expanduser("~/.config/build-iso")
    CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

    DEFAULT_CONFIG = {
        "output_dir": os.path.expanduser("~/ISO"),
        "distroname": "bigcommunity",
        "edition": "gnome",
        "manjaro_branch": "stable",
        "biglinux_branch": "stable",
        "bigcommunity_branch": "stable",
        "kernel": "lts"
    }

    def __init__(self):
        """Initialize configuration and load existing config if available"""
        self.config = self.load_config()

    def load_config(self) -> dict:
        """Load configuration from file or return defaults if not exists"""
        if not os.path.exists(self.CONFIG_FILE):
            return self.DEFAULT_CONFIG.copy()

        try:
            with open(self.CONFIG_FILE, 'r') as f:
                loaded_config = json.load(f)
                # Merge with defaults to ensure all keys exist
                config = self.DEFAULT_CONFIG.copy()
                config.update(loaded_config)
                return config
        except (json.JSONDecodeError, IOError) as e:
            # If file is corrupted or unreadable, return defaults
            return self.DEFAULT_CONFIG.copy()

    def save_config(self, config_dict: dict) -> bool:
        """Save configuration dictionary to file as JSON"""
        try:
            # Create config directory if it doesn't exist
            os.makedirs(self.CONFIG_DIR, exist_ok=True)

            # Merge with existing config to preserve other keys
            self.config.update(config_dict)

            # Write to file
            with open(self.CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=2)

            return True
        except (IOError, OSError) as e:
            return False

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
        except (IOError, OSError) as e:
            return False

        # Check if directory is writable
        if not os.access(expanded_path, os.W_OK):
            return False

        # Save to config
        return self.save_config({"output_dir": expanded_path})

    def get_config(self) -> dict:
        """Get full configuration dictionary"""
        return self.config.copy()
