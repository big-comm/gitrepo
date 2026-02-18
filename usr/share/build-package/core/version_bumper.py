#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# core/version_bumper.py - Semantic version bump from commit metadata
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import os
import re

from .git_utils import GitUtils
from .translation_utils import _


def _extract_commit_metadata(commit_message: str, explicit_type=None):
    """Return (commit_type, breaking_change) parsed from *commit_message*."""
    commit_type = explicit_type if explicit_type not in (None, "custom") else None
    breaking_change = False
    message = (commit_message or "").strip()

    if message:
        first_line = message.splitlines()[0].strip()
        cleaned_header = re.sub(r'^[^\w]+', '', first_line)
        match = re.match(r'(?P<type>[a-zA-Z]+)(?:\([^\)]*\))?(?P<breaking>!?):', cleaned_header)
        if match:
            if not commit_type:
                commit_type = match.group('type').lower()
            if match.group('breaking'):
                breaking_change = True
        if not breaking_change and "BREAKING CHANGE" in message.upper():
            breaking_change = True

    return commit_type.lower() if commit_type else None, breaking_change


def _infer_bump_level(commit_type, breaking_change):
    """Return 'major', 'minor', 'patch', or None based on commit metadata."""
    if breaking_change:
        return "major"
    if not commit_type:
        return None
    commit_type = commit_type.lower()
    if commit_type == "feat":
        return "minor"
    patch_types = {"fix", "perf", "docs", "style", "refactor", "test", "build", "ci", "chore"}
    if commit_type in patch_types:
        return "patch"
    return None


def _bump_semver(current_version: str, bump_level: str) -> str:
    """Return the bumped semantic version string."""
    try:
        major, minor, patch = [int(p) for p in current_version.split('.')]
    except (ValueError, AttributeError):
        return current_version

    if bump_level == "major":
        major += 1
        minor = 0
        patch = 0
    elif bump_level == "minor":
        minor += 1
        patch = 0
    else:  # patch
        patch += 1

    return f"{major}.{minor}.{patch}"


def _locate_app_version_entry(bp):
    """Find the file and regex match for the APP_VERSION assignment.

    Uses *bp._app_version_cache* to skip the directory walk on subsequent calls.
    Returns (file_path, content, match) or (None, None, None) when not found.
    """
    pattern = re.compile(r'(APP_VERSION\s*=\s*)(["\'])(\d+\.\d+\.\d+)(["\'])')
    repo_path = bp.repo_path or GitUtils.get_repo_root_path()

    if bp._app_version_cache:
        try:
            with open(bp._app_version_cache, 'r', encoding='utf-8') as fh:
                cached_content = fh.read()
            cached_match = pattern.search(cached_content)
            if cached_match:
                return bp._app_version_cache, cached_content, cached_match
        except (OSError, UnicodeDecodeError):
            bp._app_version_cache = None

    if not repo_path or not os.path.isdir(repo_path):
        return None, None, None

    ignore_dirs = {
        '.git', '__pycache__', 'node_modules', 'vendor', 'venv', '.venv', 'env',
        'build', 'dist', '.idea', '.vscode',
    }
    allowed_extensions = {
        "", ".py", ".cfg", ".conf", ".ini", ".json", ".toml", ".yaml", ".yml",
        ".txt", ".sh", ".bash", ".zsh", ".fish",
    }

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        dirs.sort()
        for filename in sorted(files):
            ext = os.path.splitext(filename)[1].lower()
            if ext not in allowed_extensions:
                continue

            file_path = os.path.join(root, filename)

            try:
                if os.path.getsize(file_path) > 1_000_000:
                    continue
            except OSError:
                continue

            try:
                with open(file_path, 'r', encoding='utf-8') as fh:
                    content = fh.read()
            except (OSError, UnicodeDecodeError):
                continue

            for match in pattern.finditer(content):
                line_start = content.rfind('\n', 0, match.start()) + 1
                line_prefix = content[line_start:match.start()]
                stripped_prefix = line_prefix.strip()

                if stripped_prefix.startswith(("#", "//", ";", "/*")):
                    continue

                prefix_no_trailing = line_prefix.rstrip()
                if prefix_no_trailing and prefix_no_trailing[-1] in ("'", '"'):
                    continue

                bp._app_version_cache = file_path
                return file_path, content, match

    return None, None, None


def apply_auto_version_bump(bp, commit_message: str, explicit_type=None):
    """Bump APP_VERSION in the source tree based on *commit_message* semantics.

    Returns the new version string, or None when no bump was applied.
    """
    commit_type, breaking_change = _extract_commit_metadata(commit_message, explicit_type)
    bump_level = _infer_bump_level(commit_type, breaking_change)

    if not bump_level:
        return None

    file_path, content, match = _locate_app_version_entry(bp)
    if not file_path or not match:
        if not bp._app_version_warning_shown and bp.logger:
            bp.logger.log("yellow", _("APP_VERSION constant not found. Skipping automatic version bump."))
            bp._app_version_warning_shown = True
        return None

    current_version = match.group(3)
    new_version = _bump_semver(current_version, bump_level)

    if current_version == new_version:
        return None

    new_assignment = f"{match.group(1)}{match.group(2)}{new_version}{match.group(4)}"
    updated_content = content[:match.start()] + new_assignment + content[match.end():]

    try:
        with open(file_path, 'w', encoding='utf-8') as fh:
            fh.write(updated_content)
    except OSError as exc:
        if bp.logger:
            bp.logger.log(
                "yellow",
                _("Could not update APP_VERSION ({0}). Reason: {1}").format(file_path, exc),
            )
        return None

    relative_path = os.path.relpath(file_path, bp.repo_path or GitUtils.get_repo_root_path())
    if bp.logger:
        bp.logger.log(
            "green",
            _("APP_VERSION bumped from {0} to {1} ({2} bump) in {3}").format(
                current_version, new_version, bump_level, relative_path
            ),
        )

    return new_version
