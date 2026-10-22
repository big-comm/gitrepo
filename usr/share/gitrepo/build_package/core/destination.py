"""Which organization builds and publishes this repository's package.

The choice is remembered per repository, so picking BigLinux for one package
does not send the next BigCommunity package to the BigLinux robot. A repository
seen for the first time starts from the owner of its origin when that owner is
one of the destinations; otherwise from the last choice made anywhere.
"""

from __future__ import annotations

from gitrepo.common.translation import _

from .config import DEFAULT_ORGANIZATION, DESTINATION_NAMES, VALID_ORGANIZATIONS
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


def resolve_also(settings, primary: str) -> list[str]:
    """Organizations this repository also publishes to, after *primary*."""
    key = repository_key()
    if not key:
        return []
    also = settings.get("build_also_destinations", {}).get(key, [])
    return [organization for organization in VALID_ORGANIZATIONS if organization in also and organization != primary]


def remember_targets(settings, targets: list[str]) -> bool:
    """Keep the principal destination and the extra ones for this repository."""
    targets = [organization for organization in dict.fromkeys(targets) if organization in VALID_ORGANIZATIONS]
    if not targets or not remember_destination(settings, targets[0]):
        return False
    key = repository_key()
    if not key:
        return True
    also = dict(settings.get("build_also_destinations", {}))
    if targets[1:]:
        also[key] = targets[1:]
    else:
        also.pop(key, None)
    return settings.set("build_also_destinations", also)


# The name a token is saved under when no organization-specific one exists.
DEFAULT_TOKEN_NAME = "default"


def token_usage(name: str) -> tuple[bool, str]:
    """Say whether GitRepo ever reads the token saved under *name*, and when."""
    key = name.strip().lower()
    if key in VALID_ORGANIZATIONS:
        return True, _("Used for packages built by github.com/{0}").format(key)
    if key == DEFAULT_TOKEN_NAME:
        return True, _("Used when no token is saved for the destination organization")
    return False, _(
        "Never used: GitRepo only looks for {0} or default. Save the token again for the organization."
    ).format(" / ".join(VALID_ORGANIZATIONS))


def token_source(organization: str, entries: list[tuple[str, str]]) -> str:
    """Name of the saved entry GitRepo uses for *organization*: itself, default, or none."""
    names = [name.lower() for name, _token in entries]
    if organization.lower() in names:
        return organization.lower()
    return DEFAULT_TOKEN_NAME if DEFAULT_TOKEN_NAME in names else ""


def describe_targets(organizations: list[str]) -> str:
    """Name the organizations that publish, as a reader would say it: "BigCommunity and BigLinux"."""
    names = [DESTINATION_NAMES.get(org, org) for org in organizations]
    if len(names) == 2:
        return _("{0} and {1}").format(*names)
    return ", ".join(names)
