#
# core/version_bumper.py - Semantic version bump from commit metadata
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import os
import re

from .git_utils import GitUtils
from gitrepo.common.translation import _


def _extract_commit_metadata(commit_message: str, explicit_type=None):
    """Return (commit_type, breaking_change) parsed from *commit_message*."""
    commit_type = explicit_type if explicit_type not in (None, "custom") else None
    breaking_change = False
    message = (commit_message or "").strip()

    if message:
        first_line = message.splitlines()[0].strip()
        cleaned_header = re.sub(r"^[^\w]+", "", first_line)
        match = re.match(r"(?P<type>[a-zA-Z]+)(?:\([^\)]*\))?(?P<breaking>!?):", cleaned_header)
        if match:
            if not commit_type:
                commit_type = match.group("type").lower()
            if match.group("breaking"):
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
        major, minor, patch = [int(p) for p in current_version.split(".")]
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


APP_NAME_PATTERN = re.compile(r"APP_NAME\s*=\s*(?:_\(\s*)?[\"']([^\"']+)[\"']")


def _locate_app_version_entry(bp):
    """Find the one APP_VERSION this repository owns, or nothing when unclear."""
    pattern = re.compile(r'(APP_VERSION\s*=\s*)(["\'])(\d+\.\d+\.\d+)(["\'])')
    cached = _read_version_entry(bp._app_version_cache, pattern)
    if cached:
        return cached
    repo_path = bp.repo_path or GitUtils.get_repo_root_path()
    identifiers = _repository_identifiers(repo_path)

    entries = []
    for file_path in _version_candidate_paths(repo_path):
        found = _read_version_entry(file_path, pattern)
        if not found:
            continue
        _path, content, _match = found
        app_name = APP_NAME_PATTERN.search(content)
        matches_repository = bool(app_name) and _normalize_identifier(app_name.group(1)) in identifiers
        entries.append((0 if matches_repository else 1, file_path, found))

    if not entries:
        return None, None, None
    entries.sort(key=lambda entry: (entry[0], entry[1]))
    # A repository holding several applications must say which one it versions;
    # bumping an arbitrary one would publish the wrong version.
    if len(entries) > 1 and entries[0][0] == entries[1][0]:
        return None, None, None

    _rank, file_path, found = entries[0]
    bp._app_version_cache = file_path
    return found


def _normalize_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _repository_identifiers(repo_path) -> set[str]:
    """Return the names this repository answers to: directory and pkgname."""
    if not repo_path:
        return set()
    identifiers = {_normalize_identifier(os.path.basename(os.path.normpath(repo_path)))}
    for relative in ("PKGBUILD", os.path.join("pkgbuild", "PKGBUILD")):
        try:
            with open(os.path.join(repo_path, relative), "r", encoding="utf-8") as pkgbuild:
                content = pkgbuild.read()
        except (OSError, UnicodeDecodeError):
            continue
        match = re.search(r"^pkgname=([a-zA-Z0-9@._+-]+)$", content, re.MULTILINE)
        if match:
            identifiers.add(_normalize_identifier(match.group(1)))
    return identifiers


def _read_version_entry(file_path, pattern):
    if not file_path:
        return None
    try:
        if os.path.getsize(file_path) > 1_000_000:
            return None
        with open(file_path, "r", encoding="utf-8") as source:
            content = source.read()
    except (OSError, UnicodeDecodeError):
        return None
    for match in pattern.finditer(content):
        prefix = content[content.rfind("\n", 0, match.start()) + 1 : match.start()]
        if prefix.strip().startswith(("#", "//", ";", "/*")):
            continue
        if prefix.rstrip().endswith(("'", '"')):
            continue
        return file_path, content, match
    return None


def _version_candidate_paths(repo_path):
    if not repo_path or not os.path.isdir(repo_path):
        return
    ignored = {".git", "__pycache__", "node_modules", "vendor", "venv", ".venv", "build", "dist"}
    extensions = {
        "",
        ".py",
        ".cfg",
        ".conf",
        ".ini",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        ".txt",
        ".sh",
        ".js",
        ".ts",
        ".rs",
        ".c",
        ".h",
        ".cpp",
        ".go",
        ".rb",
        ".java",
        ".kt",
        ".vala",
    }
    for root, directories, files in os.walk(repo_path):
        directories[:] = sorted(directory for directory in directories if directory not in ignored)
        for filename in sorted(files):
            if os.path.splitext(filename)[1].lower() in extensions:
                yield os.path.join(root, filename)


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
    updated_content = content[: match.start()] + new_assignment + content[match.end() :]

    try:
        with open(file_path, "w", encoding="utf-8") as fh:
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
