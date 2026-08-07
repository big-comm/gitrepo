#
# core/version_bumper.py - Semantic version bump from commit metadata
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import os
import re
import stat
from dataclasses import dataclass

from gitrepo.common.atomic_file import AtomicWriteError, atomic_write_text

from .git_utils import GitUtils
from gitrepo.common.translation import _


@dataclass(frozen=True)
class VersionBump:
    """A prepared APP_VERSION change, reviewable before anything is written."""

    file_path: str
    relative_path: str
    current_version: str
    new_version: str
    bump_level: str
    content: str


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
APP_VERSION_OWNER_PATTERN = re.compile(r"APP_VERSION_OWNER\s*=\s*[\"']([^\"']+)[\"']")


def _locate_app_version_entry(bp):
    """Find the one APP_VERSION this repository owns, or nothing when unclear.

    A single APP_VERSION in the tree is unambiguous and needs no marker. Only
    when several exist does ownership matter, so a vendored dependency is never
    bumped in place of the repository's own version.
    """
    pattern = re.compile(r'(APP_VERSION\s*=\s*)(["\'])(\d+\.\d+\.\d+)(["\'])')
    repo_path = bp.repo_path or GitUtils.get_repo_root_path()
    candidates = list(_version_candidate_paths(repo_path))
    identifiers = _repository_identifiers(repo_path)

    found_entries = []
    matching_entries = []
    for file_path in candidates:
        if not _is_regular_version_candidate(file_path):
            if bp.logger:
                bp.logger.log(
                    "yellow",
                    _("Skipping the version bump: {0} is not a regular file inside the repository.").format(file_path),
                )
            continue
        found = _read_version_entry(file_path, pattern)
        if not found:
            continue
        _path, content, _match = found
        found_entries.append((file_path, found))
        owner = APP_VERSION_OWNER_PATTERN.search(content)
        app_name = APP_NAME_PATTERN.search(content)
        if owner:
            matches_repository = _normalize_identifier(owner.group(1)) in identifiers
        elif app_name:
            normalized_name = _normalize_identifier(app_name.group(1))
            matches_repository = any(
                normalized_name == identifier or (len(identifier) >= 5 and normalized_name.endswith(identifier))
                for identifier in identifiers
            )
        else:
            matches_repository = False
        if matches_repository:
            matching_entries.append((file_path, found))

    if len(matching_entries) == 1:
        file_path, found = matching_entries[0]
    elif not matching_entries and len(found_entries) == 1:
        file_path, found = found_entries[0]
    else:
        _report_ambiguous_version(bp, repo_path, found_entries, matching_entries)
        return None, None, None

    bp._app_version_cache = file_path
    return found


def _report_ambiguous_version(bp, repo_path, found_entries, matching_entries) -> None:
    """Say which APP_VERSION was read and why it was left alone."""
    if not bp.logger or getattr(bp, "_app_version_warning_shown", False):
        return
    if not found_entries:
        return

    paths = ", ".join(sorted(os.path.relpath(path, repo_path) for path, _found in found_entries))
    if matching_entries:
        message = _(
            "Several APP_VERSION constants claim this repository ({0}). "
            "Keep APP_VERSION_OWNER on only one of them to bump it automatically."
        ).format(paths)
    else:
        message = _(
            "Found APP_VERSION in more than one file ({0}), so none was bumped. "
            "Add APP_VERSION_OWNER next to the one this repository owns."
        ).format(paths)
    bp.logger.log("yellow", message)
    bp._app_version_warning_shown = True


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
    if not _is_regular_version_candidate(file_path):
        return None
    try:
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


def _is_regular_version_candidate(file_path) -> bool:
    if not file_path:
        return False
    try:
        info = os.lstat(file_path)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and info.st_size <= 1_000_000


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

    result = GitUtils.list_version_candidates(repo_path)
    if result is not None:
        for relative_path in result:
            if os.path.splitext(relative_path)[1].lower() in extensions:
                yield os.path.join(repo_path, relative_path)
        return

    for root, directories, files in os.walk(repo_path):
        directories[:] = sorted(directory for directory in directories if directory not in ignored)
        for filename in sorted(files):
            if os.path.splitext(filename)[1].lower() in extensions:
                yield os.path.join(root, filename)


def _writable_repository_file(file_path: str, repo_root: str) -> str:
    """Return the canonical path when it is a regular file inside *repo_root*.

    The candidate walk sees whatever the repository contains, so a symlink
    pointing outside the tree must never become the file that gets rewritten.
    """
    if not repo_root:
        return ""
    root = os.path.realpath(repo_root)
    resolved = os.path.realpath(file_path)
    if os.path.commonpath([root, resolved]) != root:
        return ""
    try:
        info = os.lstat(file_path)
    except OSError:
        return ""
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return ""
    return resolved


def plan_version_bump(bp, commit_message: str, explicit_type=None) -> VersionBump | None:
    """Prepare the APP_VERSION change without touching the working tree."""
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

    repo_root = bp.repo_path or GitUtils.get_repo_root_path()
    resolved = _writable_repository_file(file_path, repo_root)
    if not resolved:
        if bp.logger:
            bp.logger.log(
                "yellow",
                _("Skipping the version bump: {0} is not a regular file inside the repository.").format(file_path),
            )
        return None

    current_version = match.group(3)
    new_version = _bump_semver(current_version, bump_level)
    if current_version == new_version:
        return None

    new_assignment = f"{match.group(1)}{match.group(2)}{new_version}{match.group(4)}"
    return VersionBump(
        file_path=resolved,
        relative_path=os.path.relpath(resolved, os.path.realpath(repo_root)),
        current_version=current_version,
        new_version=new_version,
        bump_level=bump_level,
        content=content[: match.start()] + new_assignment + content[match.end() :],
    )


def publish_version_bump(bp, plan: VersionBump) -> bool:
    """Write the prepared bump atomically, keeping the file's own permissions."""
    try:
        mode = stat.S_IMODE(os.stat(plan.file_path).st_mode)
        atomic_write_text(plan.file_path, plan.content, mode=mode)
    except (OSError, AtomicWriteError) as exc:
        if bp.logger:
            bp.logger.log(
                "red",
                _("Could not update APP_VERSION ({0}). Reason: {1}").format(plan.relative_path, exc),
            )
        return False

    if bp.logger:
        bp.logger.log(
            "green",
            _("APP_VERSION bumped from {0} to {1} ({2} bump) in {3}").format(
                plan.current_version, plan.new_version, plan.bump_level, plan.relative_path
            ),
        )
    return True


def apply_auto_version_bump(bp, commit_message: str, explicit_type=None):
    """Plan and publish the bump in one step; returns the new version or None."""
    plan = plan_version_bump(bp, commit_message, explicit_type)
    if not plan or not publish_version_bump(bp, plan):
        return None
    return plan.new_version
