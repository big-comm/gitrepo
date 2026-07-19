# intentional-log: migration and persistence failures are actionable CLI output.
#
# core/settings.py - User settings management
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import json
import os
from copy import deepcopy

from gitrepo.common.atomic_file import AtomicJsonStore, AtomicWriteError, CorruptJsonError

from gitrepo.common.translation import _


class Settings:
    """Manages user settings with persistent storage"""

    def __init__(self, config_dir: str | None = None):
        xdg_config = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        self.config_dir = config_dir or os.path.join(xdg_config, "gitrepo")
        self.config_file = os.path.join(self.config_dir, "config.json")
        self._store = AtomicJsonStore(self.config_file)
        self.last_load_error = ""

        # Migration: check for old config and migrate
        self._migrate_old_config()

        self.settings = self.load()

    def _migrate_old_config(self):
        """Migrate from old ~/.config/build-package/settings.json if exists"""
        old_config_file = os.path.expanduser("~/.config/build-package/settings.json")

        if os.path.exists(old_config_file) and not os.path.exists(self.config_file):
            try:
                # Create new config dir
                os.makedirs(self.config_dir, exist_ok=True)

                # Read old config
                with open(old_config_file, "r", encoding="utf-8") as f:
                    old_settings = self._without_retired_welcome_settings(json.load(f))

                # Merge with new defaults
                new_settings = self.get_defaults()
                new_settings.update(old_settings)

                self._validate_document(new_settings)
                self._store.write(new_settings)

                print(_("Settings migrated to new location: {0}").format(self.config_file))
            except (AtomicWriteError, CorruptJsonError, OSError, TypeError, ValueError) as error:
                self.last_load_error = str(error)

    def load(self):
        """Load settings from file or return defaults"""
        if os.path.exists(self.config_file):
            try:
                saved = self._without_retired_welcome_settings(self._store.read())
                self._validate_document(saved)
                defaults = self.get_defaults()
                defaults.update(saved)
                # Confirmation for destructive Git operations is a product
                # invariant, not a user preference. Normalize legacy files
                # that allowed expert mode to disable it.
                defaults["confirm_destructive"] = True
                return defaults
            except (CorruptJsonError, OSError, TypeError, ValueError) as error:
                self.last_load_error = str(error)

        return self.get_defaults()

    def get_defaults(self):
        """Return default settings"""
        return {
            # === FEATURE FLAGS ===
            # Enable/disable package generation features (default: OFF for generic use)
            "package_features_enabled": False,
            # Enable/disable AUR package features
            "aur_features_enabled": False,
            # Enable/disable ISO builder features
            "iso_features_enabled": False,
            # === ORGANIZATION CONFIG ===
            # Organization name (empty = detect from git remote)
            "organization_name": "",
            # Workflow repository for GitHub Actions
            "workflow_repository": "",
            # GitHub base URL (for enterprise installations)
            "github_base_url": "https://github.com",
            # === OPERATION SETTINGS ===
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
            "auto_version_bump": True,
        }

    @staticmethod
    def _without_retired_welcome_settings(document):
        """Ignore removed onboarding keys while preserving every active setting."""
        if not isinstance(document, dict):
            return document
        active_settings = document.copy()
        for key in ("show_welcome_on_startup", "show_welcome", "first_run_completed"):
            active_settings.pop(key, None)
        return active_settings

    def _validate_document(self, document: dict) -> None:
        if not isinstance(document, dict):
            raise TypeError("settings root must be an object")
        defaults = self.get_defaults()
        for key, value in document.items():
            if key not in defaults:
                raise ValueError(f"unknown setting: {key}")
            if not isinstance(value, type(defaults[key])):
                raise TypeError(f"setting {key} must be {type(defaults[key]).__name__}")

    def save(self) -> bool:
        """Save settings to file"""
        try:
            self._validate_document(self.settings)
            self._store.write(self.settings)
            return True
        except (AtomicWriteError, OSError, TypeError, ValueError) as e:
            print(_("Error saving settings: {0}").format(e))
            return False

    def get(self, key, default=None):
        """Get setting value"""
        return self.settings.get(key, default)

    def set(self, key, value) -> bool:
        """Set setting value and save"""
        if key == "confirm_destructive" and value is not True:
            return False
        previous = deepcopy(self.settings)
        self.settings[key] = value
        if self.save():
            return True
        self.settings = previous
        return False

    def reset(self) -> bool:
        """Reset to defaults"""
        previous = self.settings
        self.settings = self.get_defaults()
        if self.save():
            return True
        self.settings = previous
        return False
