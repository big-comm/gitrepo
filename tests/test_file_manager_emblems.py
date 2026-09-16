"""Emblem refreshes stay asynchronous and release retired file objects."""

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
    jobs = []

    class Job:
        def __init__(self, paths, complete):
            self.paths = paths
            self.complete = complete
            self.cancelled = False
            jobs.append(self)

        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr(emblems, "ScanJob", Job)
    instance = emblems.EmblemProvider()
    instance.jobs = jobs
    yield instance, callbacks


def drain(callbacks):
    while callbacks:
        callback, args = callbacks.pop(0)
        callback(*args)


def test_directory_requests_are_batched_without_blocking(provider):
    instance, callbacks = provider
    files = [FileInfo(f"/repo-{index}") for index in range(60)]
    for info in files:
        instance.update(info)
    assert instance.jobs == []
    assert all(info.emblems == [] for info in files)
    drain(callbacks)
    assert len(instance.jobs) == 1
    assert instance.jobs[0].paths == [info.path for info in files]
    instance.jobs[0].complete({info.path: "modified" for info in files})
    for info in files:
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
    monkeypatch.setattr(emblems, "ScanJob", lambda *args: pytest.fail("unexpected scan"))
    instance.update(FileInfo("/file", directory=False))
    instance.update(FileInfo(None))
    assert not instance._entries


def test_multiple_file_objects_share_one_pending_scan(provider):
    instance, callbacks = provider
    first, second = FileInfo("/repo"), FileInfo("/repo")
    instance.update(first)
    instance.update(second)
    drain(callbacks)
    assert len(instance.jobs) == 1
    assert instance.jobs[0].paths == ["/repo"]
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


def test_revisiting_folder_uses_cached_state_without_a_new_scan(provider):
    instance, callbacks = provider
    info = FileInfo("/repo")
    instance.update(info)
    drain(callbacks)
    instance.jobs[0].complete({"/repo": "modified"})
    del info
    assert instance._refresh() == emblems.GLib.SOURCE_REMOVE
    assert "/repo" in instance._entries
    reopened = FileInfo("/repo")
    instance.update(reopened)
    assert reopened.emblems == ["gitrepo-modified"]
    drain(callbacks)
    assert len(instance.jobs) == 1


def test_new_requests_wait_for_the_current_batch(provider):
    instance, callbacks = provider
    first, second = FileInfo("/first"), FileInfo("/second")
    instance.update(first)
    drain(callbacks)
    instance.update(second)
    drain(callbacks)
    assert len(instance.jobs) == 1
    instance.jobs[0].complete({"/first": "clean"})
    assert len(instance.jobs) == 2
    assert instance.jobs[1].paths == ["/second"]


def test_stale_cached_state_is_shown_while_refresh_runs(provider):
    instance, callbacks = provider
    info = FileInfo("/repo")
    entry = emblems._Entry(state="clean", checked=emblems.monotonic() - 20)
    instance._entries[info.path] = entry
    instance.update(info)
    assert info.emblems == ["gitrepo-clean"]
    drain(callbacks)
    assert instance.jobs[0].paths == ["/repo"]
    instance.jobs[0].complete({"/repo": "modified"})
    assert info.invalidations == 1


def test_shutdown_cancels_the_native_subprocess(provider, monkeypatch):
    instance, callbacks = provider
    monkeypatch.setattr(emblems.GLib, "source_remove", lambda *_args: None)
    info = FileInfo("/repo")
    instance.update(info)
    drain(callbacks)
    instance.close()
    assert instance.jobs[0].cancelled
