#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# core/settings.py - JSON-based settings persistence for Build ISO GUI
#

import json
import os

from core.config import CONFIG_DIR, CONFIG_FILE, DEFAULT_OUTPUT_DIR


class Settings:
    """Manages application settings with JSON persistence"""

    DEFAULTS = {
        "version": 1,
        "general": {
            "distribution": "bigcommunity",
            "edition": "gnome",
            "kernel": "lts",
            "branches": {
                "manjaro": "stable",
                "biglinux": "stable",
                "community": "stable",
            },
            "output_dir": DEFAULT_OUTPUT_DIR,
        },
        "container": {
            "engine": "auto",
            "image": "talesam/community-build:latest",
            "auto_update_image": True,
        },
        "build": {
            "clean_cache_before": False,
            "clean_cache_after": False,
            "keep_work_on_failure": True,
            "iso_profiles_source": "remote",
            "iso_profiles_local_path": "",
        },
        "notifications": {
            "desktop": True,
            "sound": False,
        },
        "advanced": {
            "debug_mode": False,
            "custom_build_repo": "",
            "custom_container_image": "",
        },
        "first_run": True,
    }

    def __init__(self):
        self._settings = self._load()

    def _load(self) -> dict:
        """Load settings from disk, merging with defaults"""
        if not os.path.exists(CONFIG_FILE):
            return self._deep_copy(self.DEFAULTS)

        try:
            with open(CONFIG_FILE, "r") as f:
                loaded = json.load(f)
            return self._merge(self.DEFAULTS, loaded)
        except (json.JSONDecodeError, IOError):
            return self._deep_copy(self.DEFAULTS)

    def _save(self):
        """Write settings to disk"""
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(self._settings, f, indent=2)

    def _deep_copy(self, d: dict) -> dict:
        return json.loads(json.dumps(d))

    def _merge(self, defaults: dict, overrides: dict) -> dict:
        """Deep merge overrides into defaults"""
        result = self._deep_copy(defaults)
        for key, value in overrides.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge(result[key], value)
            else:
                result[key] = value
        return result

    def get(self, *keys, default=None):
        """Get a nested setting value. Usage: settings.get('general', 'distribution')"""
        current = self._settings
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current

    def set(self, *args):
        """Set a nested setting value. Usage: settings.set('general', 'distribution', 'biglinux')"""
        if len(args) < 2:
            return
        *keys, value = args
        current = self._settings
        for key in keys[:-1]:
            if key not in current or not isinstance(current[key], dict):
                current[key] = {}
            current = current[key]
        current[keys[-1]] = value
        self._save()

    @property
    def is_first_run(self) -> bool:
        return self.get("first_run", default=True)

    def mark_first_run_done(self):
        self.set("first_run", False)

    @property
    def distribution(self) -> str:
        return self.get("general", "distribution", default="bigcommunity")

    @property
    def edition(self) -> str:
        return self.get("general", "edition", default="gnome")

    @property
    def kernel(self) -> str:
        return self.get("general", "kernel", default="lts")

    @property
    def branches(self) -> dict:
        return self.get("general", "branches", default={"manjaro": "stable", "biglinux": "stable", "community": "stable"})

    @property
    def output_dir(self) -> str:
        return os.path.expanduser(self.get("general", "output_dir", default=DEFAULT_OUTPUT_DIR))

    @property
    def container_image(self) -> str:
        custom = self.get("advanced", "custom_container_image", default="")
        return custom if custom else self.get("container", "image", default="talesam/community-build:latest")

    @property
    def container_engine_preference(self) -> str:
        return self.get("container", "engine", default="auto")

    def get_build_config(self) -> dict:
        """Get a config dict suitable for LocalBuilder"""
        return {
            "distroname": self.distribution,
            "edition": self.edition,
            "kernel": self.kernel,
            "branches": self.branches,
            "iso_profiles_repo": self._get_iso_profiles_repo(),
            "build_dir": self.distribution,
            "output_dir": self.output_dir,
            "clean_cache": self.get("build", "clean_cache_before", default=False),
            "clean_cache_after_build": self.get("build", "clean_cache_after", default=False),
        }

    # ── Setters ──

    @distribution.setter
    def distribution(self, value: str):
        self.set("general", "distribution", value)

    @edition.setter
    def edition(self, value: str):
        self.set("general", "edition", value)

    @kernel.setter
    def kernel(self, value: str):
        self.set("general", "kernel", value)

    @branches.setter
    def branches(self, value: dict):
        self.set("general", "branches", value)

    @output_dir.setter
    def output_dir(self, value: str):
        self.set("general", "output_dir", value)

    @container_image.setter
    def container_image(self, value: str):
        self.set("container", "image", value)

    def save(self):
        """Public save method"""
        self._save()

    def reset(self):
        """Reset all settings to defaults"""
        self._settings = self._deep_copy(self.DEFAULTS)
        self._save()

    def _get_iso_profiles_repo(self) -> str:
        from core.config import ISO_PROFILES_REPOS
        return ISO_PROFILES_REPOS.get(self.distribution, ISO_PROFILES_REPOS["bigcommunity"])
