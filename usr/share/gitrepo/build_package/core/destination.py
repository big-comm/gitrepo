"""Which organization builds and publishes this repository's package.

The choice is remembered per repository, so picking BigLinux for one package
does not send the next BigCommunity package to the BigLinux robot. A repository
seen for the first time starts from the owner of its origin when that owner is
one of the destinations; otherwise from the last choice made anywhere.
"""

from __future__ import annotations

from .config import DEFAULT_ORGANIZATION, VALID_ORGANIZATIONS
from .git_utils import GitUtils


def repository_key() -> str:
    """``owner/repository`` of origin on GitHub, lowercased; empty outside one."""
    return GitUtils.get_repo_name().lower()


def resolve_destination(settings, explicit: str | None = None) -> str:
    """Pick the destination: command line, this repository's choice, its owner, the last choice."""
    if explicit in VALID_ORGANIZATIONS:
        return explicit
    key = repository_key()
    if key:
        saved = settings.get("build_destinations", {}).get(key)
        if saved in VALID_ORGANIZATIONS:
            return saved
        owner = key.split("/", 1)[0]
        if owner in VALID_ORGANIZATIONS:
            return owner
    fallback = settings.get("build_destination", DEFAULT_ORGANIZATION)
    return fallback if fallback in VALID_ORGANIZATIONS else DEFAULT_ORGANIZATION


def remember_destination(settings, organization: str) -> bool:
    """Keep *organization* for this repository, and as the starting point for unknown ones."""
    if organization not in VALID_ORGANIZATIONS:
        return False
    key = repository_key()
    if key:
        choices = dict(settings.get("build_destinations", {}))
        choices[key] = organization
        if not settings.set("build_destinations", choices):
            return False
    return settings.set("build_destination", organization)
