"""The Big kernel series a build can install, read from the BigLinux repositories."""

from __future__ import annotations

import http.client
import io
import re
import tarfile

from gitrepo.build_iso.config import VALID_KERNELS

BIGLINUX_PACKAGES_HOST = "packages.biglinux.com.br"

# A pacman database holds one <name>-<version>-<release> directory per package.
# linux-big is the meta package, whose version is the current series (1:7.2);
# linux-big72 is a series; module packages such as linux-big72-zfs have one
# hyphen more and do not match.
_META = re.compile(r"linux-big-(?:[0-9]+:)?([0-9]+)\.([0-9]+)-[^-]+")
_SERIES = re.compile(r"linux-(big[0-9]+)-[^-]+-[^-]+")


def read_big_kernels(biglinux_branch: str) -> tuple[str, tuple[str, ...]]:
    """Return the current series and every series (big72, big73) on the branch.

    A testing build has [biglinux-testing] above [biglinux-stable], so testing
    decides the current series there, as the engine's resolve_kernel does.
    Raises OSError when a database cannot be downloaded and tarfile.TarError
    when it cannot be read.
    """
    sections = ["biglinux-stable"]
    if biglinux_branch == "testing":
        sections.insert(0, "biglinux-testing")
    current = ""
    series: set[str] = set()
    for section in sections:
        with tarfile.open(fileobj=io.BytesIO(_download_database(section)), mode="r:*") as archive:
            packages = {name.partition("/")[0] for name in archive.getnames()}
        for package in packages:
            if not current and (meta := _META.fullmatch(package)):
                current = f"big{meta[1]}{meta[2]}"
            elif series_match := _SERIES.fullmatch(package):
                series.add(series_match[1])
    return current, tuple(sorted(series, key=lambda selector: int(selector[3:])))


def _download_database(section: str) -> bytes:
    connection = http.client.HTTPSConnection(BIGLINUX_PACKAGES_HOST, timeout=10)
    try:
        connection.request("GET", f"/{section}/x86_64/{section}.db")
        response = connection.getresponse()
        if response.status != http.client.OK:
            raise OSError(f"{section}.db: HTTP {response.status} {response.reason}")
        return response.read()
    finally:
        connection.close()


def local_kernel_choices(current: str, series: tuple[str, ...]) -> list[str]:
    """Return the kernel selectors of a local build, the default first.

    big follows the current series, so that series is not offered twice.
    """
    others = [kernel for kernel in VALID_KERNELS if kernel != "big"]
    return ["big", *(selector for selector in series if selector != current), *others]
