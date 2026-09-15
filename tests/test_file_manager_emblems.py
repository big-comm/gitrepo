"""Emblem refreshes stay asynchronous and release retired file objects."""

import threading
import weakref
from concurrent.futures import Future
from pathlib import Path

import pytest

from gitrepo.file_manager import emblems


class FileInfo:
    def __init__(self, path, directory=True):
        self.path = path
        self.directory = directory
        self.gone = False
        self.emblems = []
        self.invalidations = 0

    def is_directory(self):
        return self.directory

    def is_gone(self):
        return self.gone

    def get_location(self):
        return self

    def get_path(self):
        return self.path

    def weak_ref(self):
        return weakref.ref(self)

    def add_emblem(self, name):
        self.emblems.append(name)

    def invalidate_extension_info(self):
        self.invalidations += 1


@pytest.fixture
def provider(monkeypatch):
    callbacks = []
    monkeypatch.setattr(emblems.GLib, "idle_add", lambda callback, *args: callbacks.append((callback, args)))
    monkeypatch.setattr(emblems.GLib, "timeout_add_seconds", lambda *args: 1)
    instance = emblems.EmblemProvider()
    yield instance, callbacks
    instance._workers.shutdown(wait=True, cancel_futures=True)


def drain(callbacks):
    while callbacks:
        callback, args = callbacks.pop(0)
        callback(*args)


def test_slow_git_never_blocks_the_provider(provider, monkeypatch):
    instance, callbacks = provider
    started = threading.Event()
    release = threading.Event()

    def probe(path):
        started.set()
        assert release.wait(2)
        return "modified"

    monkeypatch.setattr(emblems, "repository_state", probe)
    info = FileInfo("/repo")
    try:
        instance.update(info)
        assert started.wait(2)
        assert info.emblems == []
    finally:
        release.set()
    instance._workers.shutdown(wait=True)
    assert info.invalidations == 0  # Workers cannot call file-manager APIs.
    drain(callbacks)
    assert info.invalidations == 1
    instance.update(info)
    assert info.emblems == ["gitrepo-modified"]


def test_refresh_replaces_emblem_and_failure_clears_it(provider):
    instance, callbacks = provider
    info = FileInfo("/repo")
    entry = emblems._Entry(files={hash(info): info.weak_ref()}, state="modified")
    instance._entries[info.path] = entry
    for state in ("unpushed", "clean", None):
        result = Future()
        result.set_result(state)
        instance._complete(info.path, entry, result)
        info.emblems.clear()  # Invalidation makes the manager clear old emblems.
        instance.update(info)
        assert info.emblems == ([f"gitrepo-{state}"] if state else [])
    assert info.invalidations == 3


def test_regular_files_and_remote_locations_are_not_scanned(provider, monkeypatch):
    instance, _ = provider
    monkeypatch.setattr(instance._workers, "submit", lambda *args: pytest.fail("unexpected scan"))
    instance.update(FileInfo("/file", directory=False))
    instance.update(FileInfo(None))
    assert not instance._entries


def test_multiple_file_objects_share_one_pending_scan(provider, monkeypatch):
    instance, _ = provider
    scans = []

    def submit(*args):
        scans.append(args)
        return Future()

    monkeypatch.setattr(instance._workers, "submit", submit)
    first, second = FileInfo("/repo"), FileInfo("/repo")
    instance.update(first)
    instance.update(second)
    assert len(scans) == 1
    assert len(instance._entries["/repo"].files) == 2


def test_closed_folder_objects_stop_polling(provider):
    instance, _ = provider
    info = FileInfo("/repo")
    instance._entries[info.path] = emblems._Entry(files={hash(info): info.weak_ref()})
    del info
    assert instance._refresh() == emblems.GLib.SOURCE_REMOVE
    assert not instance._entries
    assert instance._timer == 0


def test_evicted_result_cannot_overwrite_a_new_entry(provider):
    instance, _ = provider
    old = emblems._Entry(state="modified")
    new = emblems._Entry(state="clean")
    instance._entries["/repo"] = new
    result = Future()
    result.set_result("conflict")
    instance._complete("/repo", old, result)
    assert new.state == "clean"


def test_cache_bounds_cancel_obsolete_pending_scans(provider, monkeypatch):
    instance, _ = provider
    monkeypatch.setattr(instance, "MAX_ENTRIES", 2)
    monkeypatch.setattr(instance._workers, "submit", lambda *args: Future())
    files = [FileInfo(f"/repo-{index}") for index in range(3)]
    instance.update(files[0])
    obsolete = instance._entries[files[0].path].future
    instance.update(files[1])
    instance.update(files[2])
    assert len(instance._entries) == 2
    assert obsolete.cancelled()


def test_shutdown_stops_refresh_and_ignores_late_results(provider, monkeypatch):
    instance, _ = provider
    removed = []
    monkeypatch.setattr(emblems.GLib, "source_remove", removed.append)
    info = FileInfo("/repo")
    entry = emblems._Entry(files={hash(info): info.weak_ref()}, state="clean")
    instance._entries[info.path] = entry
    instance._timer = 1
    instance.close()
    result = Future()
    result.set_result("modified")
    instance._complete(info.path, entry, result)
    instance.update(info)
    assert removed == [1]
    assert not instance._entries
    assert info.invalidations == 0


def test_extension_entrypoints_resolve_shared_runtime():
    share = Path(__file__).parents[1] / "usr/share"
    for manager in ("nautilus", "nemo"):
        extension = share / f"{manager}-python/extensions/gitrepo_emblems.py"
        assert extension.resolve().parents[2] == share.resolve()
