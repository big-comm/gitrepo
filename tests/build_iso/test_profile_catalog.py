import importlib
import io
import json
from email.message import Message
import threading
import time
import urllib.error

import pytest


class Response(io.BytesIO):
    def __init__(self, payload, headers=None):
        super().__init__(payload)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


@pytest.fixture
def catalog(monkeypatch, tmp_path):
    module = importlib.import_module("gitrepo.build_iso.core.profile_catalog")
    monkeypatch.setattr(module, "PROFILE_CACHE_FILE", tmp_path / "profile-catalog.json")
    module._reset_runtime_state_for_tests()
    return module


def http_error(url, *, remaining="0", reset="2000000000"):
    headers = Message()
    headers["X-RateLimit-Limit"] = "60"
    headers["X-RateLimit-Remaining"] = remaining
    headers["X-RateLimit-Reset"] = reset
    body = io.BytesIO(json.dumps({"message": "API rate limit exceeded"}).encode())
    return urllib.error.HTTPError(url, 403, "rate limit exceeded", headers, body)


def test_official_catalog_preserves_origin_and_filters_editions(monkeypatch, catalog):
    payload = [
        {"type": "dir", "name": "kde"},
        {"type": "dir", "name": "minimal"},
        {"type": "file", "name": "README.md"},
    ]
    monkeypatch.setattr(
        catalog.urllib.request, "urlopen", lambda *args, **kwargs: Response(json.dumps(payload).encode())
    )

    result = catalog.load_profile_catalog("biglinux", "remote")

    assert result.editions == ("kde",)
    assert result.origin == "official:GitHub"
    assert result.error == ""
    assert result.is_fallback is False


def test_network_failure_is_an_explicit_fallback(monkeypatch, catalog):
    monkeypatch.setattr(
        catalog.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(catalog.urllib.error.URLError("offline")),
    )

    result = catalog.load_profile_catalog("biglinux", "remote")

    assert result.editions
    assert result.origin == "built-in fallback"
    assert "offline" in result.error
    assert result.is_fallback is True


def test_local_catalog_accepts_only_profile_directories(tmp_path, catalog):
    valid = tmp_path / "biglinux" / "kde"
    invalid = tmp_path / "biglinux" / "random-folder"
    valid.mkdir(parents=True)
    invalid.mkdir()
    (valid / "profiledef.sh").write_text("#!/bin/sh\n", encoding="utf-8")

    result = catalog.load_profile_catalog("biglinux", "local", str(tmp_path))

    assert result.editions == ("kde",)
    assert result.origin == f"local:{tmp_path}"
    assert result.is_fallback is False


def test_successful_remote_catalog_is_reused_from_persistent_cache(monkeypatch, catalog):
    payload = json.dumps([{"type": "dir", "name": "kde"}]).encode()
    calls = []

    def respond(request, **_kwargs):
        calls.append(request)
        return Response(payload, {"ETag": '"catalog-v1"'})

    monkeypatch.setattr(catalog.urllib.request, "urlopen", respond)
    first = catalog.load_profile_catalog("biglinux", "remote")
    second = catalog.load_profile_catalog("biglinux", "remote")

    assert first.editions == second.editions == ("kde",)
    assert first.is_cached is False
    assert second.is_cached is True
    assert len(calls) == 1
    document = json.loads(catalog.PROFILE_CACHE_FILE.read_text(encoding="utf-8"))
    assert document["version"] == 1
    assert document["catalogs"]


def test_concurrent_remote_loads_are_coalesced(monkeypatch, catalog):
    payload = json.dumps([{"type": "dir", "name": "kde"}]).encode()
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def respond(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(timeout=2)
        return Response(payload)

    monkeypatch.setattr(catalog.urllib.request, "urlopen", respond)
    results = []
    first = threading.Thread(target=lambda: results.append(catalog.load_profile_catalog("biglinux", "remote")))
    second = threading.Thread(target=lambda: results.append(catalog.load_profile_catalog("biglinux", "remote")))
    first.start()
    assert entered.wait(timeout=2)
    second.start()
    release.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert calls == 1
    assert [result.editions for result in results] == [("kde",), ("kde",)]


def test_rate_limit_is_classified_and_suppresses_retry_until_reset(monkeypatch, catalog):
    reset = int(time.time()) + 600
    calls = 0

    def reject(request, **_kwargs):
        nonlocal calls
        calls += 1
        raise http_error(request.full_url, reset=str(reset))

    monkeypatch.setattr(catalog.urllib.request, "urlopen", reject)
    first = catalog.load_profile_catalog("biglinux", "remote")
    second = catalog.load_profile_catalog("biglinux", "remote", force_refresh=True)

    assert first.is_fallback is True
    assert first.failure_kind == "rate_limit"
    assert first.retry_at == reset
    assert second.failure_kind == "rate_limit"
    assert calls == 1
    assert "rate limit" not in first.error.lower()


def test_rate_limit_uses_stale_verified_catalog_without_disabling_source(monkeypatch, catalog):
    url = catalog.API_PROFILES["biglinux"]
    catalog.PROFILE_CACHE_FILE.write_text(
        json.dumps(
            {
                "version": 1,
                "catalogs": {
                    url: {
                        "editions": ["kde"],
                        "etag": '"old"',
                        "fetched_at": 1,
                        "retry_at": 0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    reset = int(time.time()) + 600
    monkeypatch.setattr(
        catalog.urllib.request,
        "urlopen",
        lambda request, **_kwargs: (_ for _ in ()).throw(http_error(request.full_url, reset=str(reset))),
    )

    result = catalog.load_profile_catalog("biglinux", "remote")

    assert result.editions == ("kde",)
    assert result.is_fallback is False
    assert result.is_cached is True
    assert result.is_stale is True
    assert result.failure_kind == "rate_limit"
    assert result.retry_at == reset


def test_catalog_is_revalidated_after_recorded_reset_even_inside_ttl(monkeypatch, catalog):
    now = int(time.time())
    url = catalog.API_PROFILES["biglinux"]
    catalog.PROFILE_CACHE_FILE.write_text(
        json.dumps(
            {
                "version": 1,
                "catalogs": {
                    url: {
                        "editions": ["kde"],
                        "etag": '"old"',
                        "fetched_at": now,
                        "retry_at": now - 1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    calls = []
    payload = json.dumps([{"type": "dir", "name": "gnome"}]).encode()
    monkeypatch.setattr(
        catalog.urllib.request,
        "urlopen",
        lambda request, **_kwargs: calls.append(request) or Response(payload),
    )

    result = catalog.load_profile_catalog("biglinux", "remote")

    assert result.editions == ("gnome",)
    assert len(calls) == 1


def test_permanent_http_error_does_not_present_old_cache_as_current(monkeypatch, catalog):
    url = catalog.API_PROFILES["biglinux"]
    catalog.PROFILE_CACHE_FILE.write_text(
        json.dumps(
            {
                "version": 1,
                "catalogs": {
                    url: {
                        "editions": ["kde"],
                        "etag": '"old"',
                        "fetched_at": 1,
                        "retry_at": 0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        catalog.urllib.request,
        "urlopen",
        lambda request, **_kwargs: (_ for _ in ()).throw(
            urllib.error.HTTPError(request.full_url, 404, "not found", Message(), io.BytesIO(b"{}"))
        ),
    )

    result = catalog.load_profile_catalog("biglinux", "remote")

    assert result.is_fallback is True
    assert result.is_cached is False


def test_optional_environment_token_is_used_without_entering_cache(monkeypatch, catalog):
    payload = json.dumps([{"type": "dir", "name": "kde"}]).encode()
    requests = []
    monkeypatch.setenv("GITHUB_TOKEN", "test-secret-token")
    monkeypatch.setattr(
        catalog.urllib.request,
        "urlopen",
        lambda request, **_kwargs: requests.append(request) or Response(payload),
    )

    result = catalog.load_profile_catalog("biglinux", "remote")

    assert result.editions == ("kde",)
    assert requests[0].get_header("Authorization") == "Bearer test-secret-token"
    assert "test-secret-token" not in catalog.PROFILE_CACHE_FILE.read_text(encoding="utf-8")


def test_corrupt_or_unwritable_cache_does_not_hide_remote_success(monkeypatch, catalog):
    catalog.PROFILE_CACHE_FILE.write_text('{"truncated":', encoding="utf-8")
    payload = json.dumps([{"type": "dir", "name": "kde"}]).encode()
    monkeypatch.setattr(catalog.urllib.request, "urlopen", lambda *_args, **_kwargs: Response(payload))
    monkeypatch.setattr(catalog, "_write_cache_document", lambda _document: (_ for _ in ()).throw(OSError("denied")))

    result = catalog.load_profile_catalog("biglinux", "remote")

    assert result.editions == ("kde",)
    assert result.is_fallback is False
    assert catalog.PROFILE_CACHE_FILE.read_text(encoding="utf-8") == '{"truncated":'
