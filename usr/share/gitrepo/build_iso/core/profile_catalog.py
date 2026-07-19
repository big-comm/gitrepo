"""Load ISO profile editions with durable cache and truthful failure semantics."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit
import urllib.error
import urllib.request

from gitrepo.common.atomic_file import AtomicJsonStore, CorruptJsonError
from gitrepo.common.network_url import validate_github_repository_url, validate_https_url

from .config import API_PROFILES, APP_VERSION, DEFAULT_EDITIONS, EXCLUDED_EDITIONS


PROFILE_MARKERS = ("profiledef.sh", "Packages-Desktop", "packages.x86_64", "packages-desktop")
CACHE_VERSION = 1
CACHE_TTL_SECONDS = 6 * 60 * 60


def _default_cache_file() -> Path:
    configured = os.environ.get("XDG_CACHE_HOME", "")
    cache_home = (
        Path(configured).expanduser() if configured and Path(configured).is_absolute() else Path.home() / ".cache"
    )
    return cache_home / "build-iso-gui" / "profile-catalog.json"


PROFILE_CACHE_FILE = _default_cache_file()
_CACHE_IO_LOCK = threading.Lock()
_URL_LOCKS_GUARD = threading.Lock()
_URL_LOCKS: dict[str, threading.Lock] = {}


@dataclass(frozen=True)
class ProfileCatalogResult:
    editions: tuple[str, ...]
    origin: str
    error: str = ""
    is_fallback: bool = False
    is_cached: bool = False
    is_stale: bool = False
    failure_kind: str = ""
    retry_at: int = 0


@dataclass(frozen=True)
class _RemoteCatalog:
    editions: tuple[str, ...]
    is_cached: bool = False
    is_stale: bool = False
    failure_kind: str = ""
    retry_at: int = 0
    error: str = ""


class _CatalogSourceError(OSError):
    def __init__(self, message: str, *, failure_kind: str = "network", retry_at: int = 0):
        super().__init__(message)
        self.failure_kind = failure_kind
        self.retry_at = retry_at


def load_profile_catalog(
    distro: str,
    source_type: str,
    source_value: str = "",
    *,
    force_refresh: bool = False,
) -> ProfileCatalogResult:
    """Load one distro catalog and explicitly label cache or fallback use."""
    try:
        if source_type == "local":
            editions = _read_local_editions(source_value, distro)
            origin = f"local:{source_value}"
            remote = _RemoteCatalog(editions)
        elif source_type == "custom_url":
            remote = _read_github_editions(_custom_api_url(source_value, distro), force_refresh=force_refresh)
            origin = f"custom:{source_value}"
        else:
            remote = _read_github_editions(API_PROFILES[distro], force_refresh=force_refresh)
            origin = "official:GitHub"
        filtered = _filter_editions(remote.editions)
        if not filtered:
            raise ValueError("the selected source contains no supported profile editions")
        return ProfileCatalogResult(
            filtered,
            origin,
            remote.error,
            is_cached=remote.is_cached,
            is_stale=remote.is_stale,
            failure_kind=remote.failure_kind,
            retry_at=remote.retry_at,
        )
    except _CatalogSourceError as error:
        fallback = _filter_editions(DEFAULT_EDITIONS.get(distro, ()))
        return ProfileCatalogResult(
            fallback,
            "built-in fallback",
            str(error),
            True,
            failure_kind=error.failure_kind,
            retry_at=error.retry_at,
        )
    except (KeyError, OSError, ValueError, TypeError, json.JSONDecodeError, urllib.error.URLError) as error:
        fallback = _filter_editions(DEFAULT_EDITIONS.get(distro, ()))
        return ProfileCatalogResult(fallback, "built-in fallback", str(error), True, failure_kind="network")


def _read_github_editions(url: str, *, force_refresh: bool = False) -> _RemoteCatalog:
    safe_url = validate_https_url(url, {"api.github.com"})
    with _url_lock(safe_url):
        now = int(time.time())
        cached = _read_cache_entry(safe_url)
        cached_editions = tuple(cached.get("editions", ())) if cached else ()
        retry_at = int(cached.get("retry_at", 0)) if cached else 0

        if retry_at > now:
            return _rate_limited_catalog(cached_editions, retry_at)
        if _cache_is_fresh(cached, cached_editions, now, force_refresh, retry_at):
            return _RemoteCatalog(cached_editions, is_cached=True)

        request = urllib.request.Request(safe_url, headers=_github_headers(cached))
        try:
            with urllib.request.urlopen(request, timeout=10) as response:  # nosec B310
                payload = json.loads(response.read().decode("utf-8"))
                editions = _parse_github_editions(payload)
                _store_cache_entry(
                    safe_url,
                    editions,
                    etag=response.headers.get("ETag", ""),
                    fetched_at=now,
                    retry_at=0,
                )
                return _RemoteCatalog(editions)
        except urllib.error.HTTPError as error:
            if error.code == 304 and cached_editions:
                _store_cache_entry(
                    safe_url,
                    cached_editions,
                    etag=cached.get("etag", ""),
                    fetched_at=now,
                    retry_at=0,
                )
                return _RemoteCatalog(cached_editions, is_cached=True)
            reset = _primary_rate_limit_reset(error, now)
            if reset:
                _store_cache_entry(
                    safe_url,
                    cached_editions,
                    etag=cached.get("etag", "") if cached else "",
                    fetched_at=int(cached.get("fetched_at", 0)) if cached else 0,
                    retry_at=reset,
                )
                return _rate_limited_catalog(cached_editions, reset)
            if cached_editions and error.code in (403, 429, 500, 502, 503, 504):
                return _RemoteCatalog(cached_editions, True, True, "network", error=str(error))
            raise
        except (OSError, ValueError, TypeError, json.JSONDecodeError, urllib.error.URLError) as error:
            if cached_editions:
                return _RemoteCatalog(cached_editions, True, True, "network", error=str(error))
            raise


def _cache_is_fresh(
    cached: dict | None,
    cached_editions: tuple[str, ...],
    now: int,
    force_refresh: bool,
    retry_at: int,
) -> bool:
    return bool(
        cached
        and cached_editions
        and not force_refresh
        and not retry_at
        and int(cached.get("fetched_at", 0)) + CACHE_TTL_SECONDS > now
    )


def _github_headers(cached: dict | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"Build-ISO/{APP_VERSION}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = _github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if cached and cached.get("etag"):
        headers["If-None-Match"] = cached["etag"]
    return headers


def _github_token() -> str:
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    if not token or len(token) > 4096 or any(character in token for character in "\r\n\0"):
        return ""
    return token


def _primary_rate_limit_reset(error: urllib.error.HTTPError, now: int) -> int:
    if error.code not in (403, 429) or error.headers.get("X-RateLimit-Remaining") != "0":
        return 0
    try:
        reset = int(error.headers.get("X-RateLimit-Reset", "0"))
    except (TypeError, ValueError):
        reset = 0
    if reset > now:
        return reset
    try:
        retry_after = int(error.headers.get("Retry-After", "0"))
    except (TypeError, ValueError):
        retry_after = 0
    return now + max(retry_after, 60)


def _rate_limited_catalog(cached_editions: tuple[str, ...], retry_at: int) -> _RemoteCatalog:
    message = "GitHub API request quota reached"
    if cached_editions:
        return _RemoteCatalog(cached_editions, True, True, "rate_limit", retry_at, message)
    raise _CatalogSourceError(message, failure_kind="rate_limit", retry_at=retry_at)


def _parse_github_editions(payload) -> tuple[str, ...]:
    if not isinstance(payload, list):
        raise ValueError("the profile service returned an unexpected response")
    return tuple(
        item["name"]
        for item in payload
        if isinstance(item, dict)
        and item.get("type") == "dir"
        and isinstance(item.get("name"), str)
        and not item["name"].startswith(".")
    )


def _url_lock(url: str) -> threading.Lock:
    with _URL_LOCKS_GUARD:
        return _URL_LOCKS.setdefault(url, threading.Lock())


def _empty_cache_document() -> dict:
    return {"version": CACHE_VERSION, "catalogs": {}}


def _read_cache_document() -> dict:
    try:
        document = AtomicJsonStore(PROFILE_CACHE_FILE).read()
    except (FileNotFoundError, CorruptJsonError, OSError):
        return _empty_cache_document()
    if document.get("version") != CACHE_VERSION or not isinstance(document.get("catalogs"), dict):
        return _empty_cache_document()
    return document


def _read_cache_entry(url: str) -> dict | None:
    with _CACHE_IO_LOCK:
        entry = _read_cache_document()["catalogs"].get(url)
    if not isinstance(entry, dict):
        return None
    editions = entry.get("editions")
    if not isinstance(editions, list) or not all(isinstance(edition, str) for edition in editions):
        return None
    return {
        "editions": tuple(editions),
        "etag": entry.get("etag", "") if isinstance(entry.get("etag", ""), str) else "",
        "fetched_at": entry.get("fetched_at", 0) if isinstance(entry.get("fetched_at", 0), int) else 0,
        "retry_at": entry.get("retry_at", 0) if isinstance(entry.get("retry_at", 0), int) else 0,
    }


def _store_cache_entry(
    url: str,
    editions: tuple[str, ...],
    *,
    etag: str,
    fetched_at: int,
    retry_at: int,
) -> None:
    with _CACHE_IO_LOCK:
        document = _read_cache_document()
        document["catalogs"][url] = {
            "editions": list(editions),
            "etag": etag,
            "fetched_at": fetched_at,
            "retry_at": retry_at,
        }
        try:
            _write_cache_document(document)
        except (OSError, TypeError):
            pass


def _write_cache_document(document: dict) -> None:
    AtomicJsonStore(PROFILE_CACHE_FILE).write(document)


def _reset_runtime_state_for_tests() -> None:
    with _URL_LOCKS_GUARD:
        _URL_LOCKS.clear()


def _custom_api_url(repository_url: str, distro: str) -> str:
    safe_url = validate_github_repository_url(repository_url)
    parts = [part for part in urlsplit(safe_url).path.removesuffix(".git").split("/") if part]
    if len(parts) != 2:
        raise ValueError("the custom URL must identify one GitHub owner and repository")
    owner, repository = parts
    return f"https://api.github.com/repos/{owner}/{repository}/contents/{distro}"


def _read_local_editions(root: str, distro: str) -> tuple[str, ...]:
    if not root:
        raise ValueError("no local profile directory is configured")
    distro_root = os.path.join(root, distro)
    search_root = distro_root if os.path.isdir(distro_root) else root
    if not os.path.isdir(search_root):
        raise ValueError("the local profile directory does not exist")
    return tuple(
        entry
        for entry in sorted(os.listdir(search_root))
        if _is_profile_directory(os.path.join(search_root, entry), entry)
    )


def _is_profile_directory(path: str, name: str) -> bool:
    return (
        not name.startswith(".")
        and os.path.isdir(path)
        and any(os.path.isfile(os.path.join(path, marker)) for marker in PROFILE_MARKERS)
    )


def _filter_editions(editions) -> tuple[str, ...]:
    excluded = set(EXCLUDED_EDITIONS)
    return tuple(sorted({edition for edition in editions if edition.lower() not in excluded}))
