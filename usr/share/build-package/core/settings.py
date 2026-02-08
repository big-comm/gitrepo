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

    # Predefined organizations for quick selection
    PREDEFINED_ORGANIZATIONS = [
        {"name": "BigCommunity", "value": "big-comm"},
        {"name": "BigLinux", "value": "biglinux"},
    ]

    def __init__(self):
        # New config path: ~/.config/gitrepo/config.json
        self.config_dir = os.path.expanduser("~/.config/gitrepo")
        self.config_file = os.path.join(self.config_dir, "config.json")
        
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
                with open(old_config_file, 'r', encoding='utf-8') as f:
                    old_settings = json.load(f)
                
                # Merge with new defaults
                new_settings = self.get_defaults()
                new_settings.update(old_settings)
                
                # Save to new location
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(new_settings, f, indent=2)
                
                print(_("Settings migrated to new location: {0}").format(self.config_file))
            except Exception:
                pass  # Silently fail migration

    def load(self):
        """Load settings from file or return defaults"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    # Merge with defaults to ensure new keys exist
                    defaults = self.get_defaults()
                    defaults.update(saved)
                    return defaults
            except Exception:
                pass

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

            # === UI SETTINGS ===
            # Show welcome dialog on startup
            "show_welcome_on_startup": True,
            
            # First run completed flag
            "first_run_completed": False,
        }

    def save(self):
        """Save settings to file"""
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2)
            return True
        except Exception as e:
            print(_("Error saving settings: {0}").format(e))
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

    def is_feature_enabled(self, feature):
        """Check if a feature is enabled"""
        feature_map = {
            "package": "package_features_enabled",
            "aur": "aur_features_enabled",
            "iso": "iso_features_enabled",
        }
        key = feature_map.get(feature, f"{feature}_features_enabled")
        return self.get(key, False)

    def get_organization(self):
        """Get configured organization or empty string"""
        return self.get("organization_name", "")

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
