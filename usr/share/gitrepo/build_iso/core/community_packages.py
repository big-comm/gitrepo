#
# core/community_packages.py - Whether a community repository already publishes a package
#
# A kernel such as linux-big reaches testing before stable. An ISO that asks
# for it on a channel that does not have it yet fails an hour into the build,
# deep inside the chroot, so the choice is checked against the channel's
# package database when it is made. The answer only informs: nothing is
# blocked, and a database that cannot be read says nothing at all.
#

from __future__ import annotations

import io
import tarfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable

from gitrepo.common.network_url import validate_https_url
from gitrepo.common.translation import _

from gitrepo.build_iso.config import (
    APP_VERSION,
    BRANCH_DISPLAY_NAMES,
    COMMUNITY_KERNEL_PACKAGES,
    COMMUNITY_REPO_HOST,
)

# A community database is about 10 KB; anything this large is not one.
_MAX_DATABASE_BYTES = 16 * 1024 * 1024
_CACHE_SECONDS = 300

_cache: dict[str, tuple[float, frozenset[str]]] = {}
_cache_lock = threading.Lock()


def database_url(branch: str) -> str:
    """Return the package database of one community channel (stable, testing, ...)."""
    url = f"https://{COMMUNITY_REPO_HOST}/{branch}/x86_64/community-{branch}.db"
    return validate_https_url(url, {COMMUNITY_REPO_HOST})


def package_names(database: bytes) -> frozenset[str]:
    """Read the package names out of a pacman database archive.

    Each package is a top-level directory named <name>-<version>-<release>;
    version and release never contain a dash, so the name is what precedes
    the last two.
    """
    names = set()
    with tarfile.open(fileobj=io.BytesIO(database), mode="r:*") as archive:
        for member in archive.getmembers():
            parts = member.name.split("/", 1)[0].rsplit("-", 2)
            if len(parts) == 3 and parts[0]:
                names.add(parts[0])
    return frozenset(names)


def _download(url: str) -> bytes:
    # The repository host refuses Python's default User-Agent with 403.
    request = urllib.request.Request(url, headers={"User-Agent": f"gitrepo/{APP_VERSION}"})
    with urllib.request.urlopen(request, timeout=10) as response:  # nosec B310 - allowlisted HTTPS host
        data: bytes = response.read(_MAX_DATABASE_BYTES + 1)
    if len(data) > _MAX_DATABASE_BYTES:
        raise ValueError("package database is too large")
    return data


def channel_packages(branch: str, download: Callable[[str], bytes] = _download) -> frozenset[str] | None:
    """Return the packages a community channel publishes, or None if it cannot be read."""
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(branch)
        if cached and now - cached[0] < _CACHE_SECONDS:
            return cached[1]
    try:
        names = package_names(download(database_url(branch)))
    except (OSError, ValueError, tarfile.TarError, urllib.error.URLError):
        return None
    with _cache_lock:
        _cache[branch] = (now, names)
    return names


def kernel_notice(
    kernel: str,
    distribution: str,
    community_branch: str,
    lookup: Callable[[str], frozenset[str] | None] = channel_packages,
) -> str:
    """Return a warning when the chosen kernel cannot be installed from the chosen channel.

    Empty when the kernel comes from Manjaro, when the channel publishes it,
    or when the channel could not be read: an unverifiable choice is not
    reported as a broken one.
    """
    package = COMMUNITY_KERNEL_PACKAGES.get(kernel)
    if not package:
        return ""
    if distribution != "bigcommunity":
        return _("The {0} kernel is only available for BigCommunity images.").format(package)
    published = lookup(community_branch)
    if published is None or package in published:
        return ""
    return _(
        "The {0} kernel is not published in Community {1} yet, so this ISO would fail to build. "
        "Choose Community Testing, or wait until it is published."
    ).format(package, BRANCH_DISPLAY_NAMES.get(community_branch, community_branch))


def available_kernels(kernels: list[str], distribution: str) -> list[str]:
    """Return the kernels a distribution can build with, in their usual order."""
    return [kernel for kernel in kernels if kernel not in COMMUNITY_KERNEL_PACKAGES or distribution == "bigcommunity"]
