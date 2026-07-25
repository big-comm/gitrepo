"""Validation for user-configurable HTTPS endpoints."""

from __future__ import annotations

from collections.abc import Collection
import re
from urllib.parse import urlsplit, urlunsplit


class UnsafeNetworkUrl(ValueError):
    """Raised when a URL crosses the application's network trust boundary."""


# A GitHub owner or repository name. Requiring an alphanumeric first character
# also rejects the "." and ".." segments that would escape the intended path.
_GITHUB_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def is_github_path_segment(segment: str) -> bool:
    """Return True when *segment* is a usable GitHub owner or repository name."""
    return bool(_GITHUB_SEGMENT.fullmatch(segment))


def validate_https_url(url: str, allowed_hosts: Collection[str]) -> str:
    """Return a normalized HTTPS URL restricted to an explicit host allowlist."""
    if any(ord(character) < 32 or ord(character) == 127 for character in url):
        raise UnsafeNetworkUrl("control characters are not supported")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise UnsafeNetworkUrl("the URL is malformed") from error

    hostname = parsed.hostname.lower() if parsed.hostname else ""
    normalized_hosts = {host.lower() for host in allowed_hosts}
    if parsed.scheme != "https" or hostname not in normalized_hosts:
        raise UnsafeNetworkUrl("only allowlisted HTTPS hosts are supported")
    if parsed.username or parsed.password or port not in (None, 443):
        raise UnsafeNetworkUrl("credentials and custom ports are not supported")
    netloc = hostname if port is None else f"{hostname}:{port}"
    return urlunsplit(("https", netloc, parsed.path, parsed.query, ""))


def validate_github_repository_url(url: str) -> str:
    """Return a canonical public GitHub owner/repository clone URL."""
    try:
        requested = urlsplit(url)
    except ValueError as error:
        raise UnsafeNetworkUrl("the URL is malformed") from error
    if requested.query or requested.fragment:
        raise UnsafeNetworkUrl("query strings and fragments are not supported")

    safe_url = validate_https_url(url, {"github.com"})
    parsed = urlsplit(safe_url)
    parts = [part for part in parsed.path.removesuffix(".git").split("/") if part]
    if len(parts) != 2 or not all(is_github_path_segment(part) for part in parts):
        raise UnsafeNetworkUrl("the URL must identify one GitHub owner and repository")
    return f"https://github.com/{parts[0]}/{parts[1]}.git"
