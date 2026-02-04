#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# core/settings.py - User settings management
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import json
import os
from .translation_utils import _

class Settings:
    """Manages user settings with persistent storage"""

    def __init__(self):
        self.config_dir = os.path.expanduser("~/.config/build-package")
        self.config_file = os.path.join(self.config_dir, "settings.json")
        self.settings = self.load()

    def load(self):
        """Load settings from file or return defaults"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass

        return self.get_defaults()

    def get_defaults(self):
        """Return default settings"""
        return {
            # Operation mode: quick (fast automation) | safe (more control) | expert (maximum automation)
            "operation_mode": "safe",

            # Conflict resolution strategy: auto-ours | auto-theirs | interactive | manual
            "conflict_strategy": "interactive",

            # Auto-fetch before operations
            "auto_fetch": True,

            # Auto-switch to user branch
            "auto_switch_branch": True,

            # Auto-sync remote branch with main
            "auto_sync_remote": True,

            # Show git commands before executing
            "show_git_commands": False,

            # Confirm destructive operations (force push, reset --hard, etc)
            "confirm_destructive": True,

            # Auto-pull before commit
            "auto_pull": False,

            # Version bump behavior
            "auto_version_bump": True
        }

    def save(self):
        """Save settings to file"""
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving settings: {e}")
            return False

    def get(self, key, default=None):
        """Get setting value"""
        return self.settings.get(key, default)

    def set(self, key, value):
        """Set setting value and save"""
        self.settings[key] = value
        self.save()

    def reset(self):
        """Reset to defaults"""
        self.settings = self.get_defaults()
        self.save()

    def get_mode_config(self):
        """Get configuration for current operation mode"""
        mode = self.get("operation_mode", "safe")

        if mode == "quick":
            return {
                "auto_resolve_conflicts": True,
                "auto_switch_branches": True,
                "auto_merge": True,
                "auto_pull": True,
                "confirm_destructive": True,
                "show_preview": False
            }
        elif mode == "expert":
            return {
                "auto_resolve_conflicts": True,
                "auto_switch_branches": True,
                "auto_merge": True,
                "auto_pull": True,
                "confirm_destructive": False,
                "show_preview": False
            }
        else:  # safe
            return {
                "auto_resolve_conflicts": False,
                "auto_switch_branches": False,
                "auto_merge": False,
                "auto_pull": False,
                "confirm_destructive": True,
                "show_preview": True
            }
