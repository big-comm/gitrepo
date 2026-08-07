#
# core/settings.py - JSON-based settings persistence for Build ISO GUI
#

import os
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from gitrepo.build_iso.config import LEGACY_CLI_CONFIG_FILE, LEGACY_GUI_CONFIG_FILE
from gitrepo.build_iso.core.config import CONFIG_FILE, DEFAULT_OUTPUT_DIR
from gitrepo.common.atomic_file import AtomicJsonStore, AtomicWriteError, CorruptJsonError


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
            "iso_profiles_custom_url": "",
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
    }

    def __init__(self, config_file: str | None = None, legacy_files: Sequence[str] | None = None) -> None:
        self.last_load_error = ""
        self.migration_source = ""
        self.config_file = config_file or CONFIG_FILE
        self._store = AtomicJsonStore(self.config_file)
        if legacy_files is None:
            legacy_files = () if config_file is not None else (LEGACY_GUI_CONFIG_FILE, LEGACY_CLI_CONFIG_FILE)
        self._migrate_legacy(legacy_files)
        self._settings = self._load()

    def _migrate_legacy(self, legacy_files: Sequence[str]) -> None:
        """Import one legacy settings file without modifying the source."""
        if Path(self.config_file).exists():
            return
        for legacy_file in legacy_files:
            legacy_path = Path(legacy_file)
            if not legacy_path.exists():
                continue
            try:
                legacy_document = AtomicJsonStore(legacy_path).read()
                migrated = self._convert_legacy_document(legacy_document)
                self._validate_document(migrated)
                self._store.write(migrated)
                self.migration_source = str(legacy_path)
            except (AtomicWriteError, CorruptJsonError, OSError, TypeError, ValueError) as error:
                self.last_load_error = str(error)
            return

    def _convert_legacy_document(self, document: dict[str, Any]) -> dict[str, Any]:
        document = self._without_retired_welcome_setting(document)
        if "general" in document or "version" in document:
            return self._merge(self.DEFAULTS, document)

        allowed_keys = {
            "output_dir",
            "distroname",
            "edition",
            "manjaro_branch",
            "biglinux_branch",
            "bigcommunity_branch",
            "kernel",
            "container_engine",
        }
        unknown_keys = set(document) - allowed_keys
        if unknown_keys:
            raise ValueError(f"unknown legacy setting: {sorted(unknown_keys)[0]}")

        migrated = self._deep_copy(self.DEFAULTS)
        general = migrated["general"]
        branches = general["branches"]
        general["output_dir"] = document.get("output_dir", general["output_dir"])
        general["distribution"] = document.get("distroname", general["distribution"])
        general["edition"] = document.get("edition", general["edition"])
        general["kernel"] = document.get("kernel", general["kernel"])
        branches["manjaro"] = document.get("manjaro_branch", branches["manjaro"])
        branches["biglinux"] = document.get("biglinux_branch", branches["biglinux"])
        branches["community"] = document.get("bigcommunity_branch", branches["community"])
        migrated["container"]["engine"] = document.get("container_engine", migrated["container"]["engine"])
        return migrated

    def _load(self) -> dict[str, Any]:
        """Load settings from disk, merging with defaults"""
        if not os.path.exists(self.config_file):
            return self._deep_copy(self.DEFAULTS)

        try:
            loaded = self._store.read()
            if isinstance(loaded, dict):
                loaded = self._without_retired_welcome_setting(loaded)
            self._validate_document(loaded)
            return self._merge(self.DEFAULTS, loaded)
        except (CorruptJsonError, OSError, ValueError, TypeError) as error:
            self.last_load_error = str(error)
            return self._deep_copy(self.DEFAULTS)

    def _save(self) -> bool:
        """Write settings to disk"""
        try:
            self._validate_document(self._settings)
            self._store.write(self._settings)
            return True
        except (AtomicWriteError, OSError, TypeError, ValueError):
            return False

    def _deep_copy(self, d: dict[str, Any]) -> dict[str, Any]:
        return deepcopy(d)

    @staticmethod
    def _without_retired_welcome_setting(document: dict[str, Any]) -> dict[str, Any]:
        """Return active settings without rewriting a legacy source file."""
        active_settings = document.copy()
        active_settings.pop("first_run", None)
        return active_settings

    def _validate_document(self, document: dict[str, Any]) -> None:
        if not isinstance(document, dict):
            raise TypeError("settings root must be an object")
        if document.get("version", 1) != self.DEFAULTS["version"]:
            raise ValueError("unsupported settings version")
        self._validate_values(self.DEFAULTS, document)

    def _validate_values(self, defaults: dict[str, Any], overrides: dict[str, Any]) -> None:
        for key, value in overrides.items():
            if key not in defaults:
                raise ValueError(f"unknown setting: {key}")
            expected = defaults[key]
            if isinstance(expected, dict):
                if not isinstance(value, dict):
                    raise TypeError(f"setting {key} must be an object")
                self._validate_values(expected, value)
            elif not isinstance(value, type(expected)):
                raise TypeError(f"setting {key} must be {type(expected).__name__}")

    def _merge(self, defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
        """Deep merge overrides into defaults"""
        result = self._deep_copy(defaults)
        for key, value in overrides.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge(result[key], value)
            else:
                result[key] = value
        return result

    def get(self, *keys: str, default: Any = None) -> Any:
        """Get a nested setting value. Usage: settings.get('general', 'distribution')"""
        current = self._settings
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current

    def set(self, *args: Any) -> bool:
        """Set a nested setting value. Usage: settings.set('general', 'distribution', 'biglinux')"""
        if len(args) < 2:
            return False
        *keys, value = args
        if not all(isinstance(key, str) for key in keys):
            return False
        return self.set_many({tuple(keys): value})

    def set_many(self, updates: Mapping[tuple[str, ...], Any]) -> bool:
        """Validate and atomically publish several related settings."""
        candidate = self._deep_copy(self._settings)
        for path, value in updates.items():
            if not path:
                return False
            current: dict[str, Any] = candidate
            for key in path[:-1]:
                nested = current.get(key)
                if not isinstance(nested, dict):
                    return False
                current = nested
            current[path[-1]] = value
        try:
            self._validate_document(candidate)
            self._store.write(candidate)
        except (AtomicWriteError, OSError, TypeError, ValueError):
            return False
        self._settings = candidate
        return True

    def local_values(self) -> dict[str, str]:
        """Return the flat settings view consumed by the terminal local builder."""
        return {
            "output_dir": self.output_dir,
            "distroname": self.distribution,
            "edition": self.edition,
            "manjaro_branch": self.branches["manjaro"],
            "biglinux_branch": self.branches["biglinux"],
            "bigcommunity_branch": self.branches["community"],
            "kernel": self.kernel,
            "container_engine": self.container_engine_preference,
        }

    def set_local_values(self, values: Mapping[str, str]) -> bool:
        """Atomically update the terminal local-builder view."""
        allowed_keys = set(self.local_values())
        unknown_keys = set(values) - allowed_keys
        if unknown_keys:
            return False

        key_paths = {
            "output_dir": ("general", "output_dir"),
            "distroname": ("general", "distribution"),
            "edition": ("general", "edition"),
            "kernel": ("general", "kernel"),
            "manjaro_branch": ("general", "branches", "manjaro"),
            "biglinux_branch": ("general", "branches", "biglinux"),
            "bigcommunity_branch": ("general", "branches", "community"),
            "container_engine": ("container", "engine"),
        }
        return self.set_many({key_paths[key]: value for key, value in values.items()})

    @property
    def distribution(self) -> str:
        return cast(str, self.get("general", "distribution", default="bigcommunity"))

    @property
    def edition(self) -> str:
        return cast(str, self.get("general", "edition", default="gnome"))

    @property
    def kernel(self) -> str:
        return cast(str, self.get("general", "kernel", default="lts"))

    @property
    def branches(self) -> dict[str, str]:
        return cast(
            dict[str, str],
            self.get("general", "branches", default={"manjaro": "stable", "biglinux": "stable", "community": "stable"}),
        )

    @property
    def output_dir(self) -> str:
        return os.path.expanduser(cast(str, self.get("general", "output_dir", default=DEFAULT_OUTPUT_DIR)))

    @property
    def container_image(self) -> str:
        custom = cast(str, self.get("advanced", "custom_container_image", default=""))
        return custom or cast(str, self.get("container", "image", default="talesam/community-build:latest"))

    @property
    def container_engine_preference(self) -> str:
        return cast(str, self.get("container", "engine", default="auto"))

    def reset(self) -> bool:
        """Reset all settings to defaults"""
        previous = self._settings
        self._settings = self._deep_copy(self.DEFAULTS)
        if self._save():
            return True
        self._settings = previous
        return False
