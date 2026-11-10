"""Emblem refreshes stay asynchronous and release retired file objects."""

import os
import weakref
from concurrent.futures import Future
from pathlib import Path

import pytest

from gitrepo.file_manager import emblems, mounts, scan, scanner

# A machine like the one that panicked: an NTFS partition through ntfs-3g
# under an ext4 /mnt, gvfs and the document portal, plus network shares.
MOUNTINFO = r"""22 1 0:21 / / rw,relatime shared:1 - btrfs /dev/sda2 rw
30 22 8:3 / /home rw,relatime shared:2 - ext4 /dev/sda3 rw
40 22 8:4 / /mnt rw,relatime shared:3 - ext4 /dev/sda4 rw
41 40 8:5 / /mnt/win rw,nosuid,nodev,relatime shared:5 - fuseblk /dev/sda5 rw,user_id=0,group_id=0
42 40 8:17 / /mnt/My\040Disk rw,relatime shared:6 - fuseblk /dev/sdb1 rw
50 22 0:50 / /run/user/1000/gvfs rw,nosuid,nodev,relatime shared:7 - fuse.gvfsd-fuse gvfsd-fuse rw
51 22 0:51 / /run/user/1000/doc rw,nosuid,nodev,relatime shared:8 - fuse.portal portal rw
60 22 0:60 / /srv/share rw,relatime shared:9 - cifs //nas/share rw
61 22 0:61 / /srv/nfs rw,relatime shared:10 - nfs4 nas:/export rw
62 22 0:62 / /srv/sshfs rw,relatime - fuse.sshfs me@host:/ rw
"""
TABLE = mounts.parse_mountinfo(MOUNTINFO)


@pytest.fixture(autouse=True)
def _no_host_symlinks(monkeypatch, tmp_path):
    """Only links made by the test count: this host's own (/media -> /mnt) must not."""
    real_readlink = os.readlink

    def readlink(path, *args, **kwargs):
        if os.fspath(path).startswith(str(tmp_path)):
            return real_readlink(path, *args, **kwargs)
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(mounts.os, "readlink", readlink)


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
    monkeypatch.setattr(emblems.mounts, "read_mounts", lambda: TABLE)
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
    files[0].gone = True  # Its folder is no longer displayed anywhere.
    instance.update(files[1])
    instance.update(files[2])
    assert len(instance._entries) == 2
    assert files[0].path not in instance._entries
    assert obsolete.cancelled()


def test_folders_still_displayed_are_never_evicted(provider, monkeypatch):
    # Tabs showing more folders than the cache bound (BigCommunity alone
    # lists 69) used to push the first ones out while they were still on
    # screen: their emblems then froze until F5 asked for them again.
    instance, callbacks = provider
    monkeypatch.setattr(instance, "MAX_ENTRIES", 4)
    files = [FileInfo(f"/repo-{index}") for index in range(10)]
    for info in files:
        instance.update(info)
    drain(callbacks)
    instance.jobs[-1].complete({info.path: "unpushed" for info in files})

    assert all(info.path in instance._entries for info in files)

    # The first repository is pushed; the next refresh must reach it.
    instance.jobs.clear()
    for entry in instance._entries.values():
        entry.checked = 0
    instance._refresh()
    drain(callbacks)
    assert files[0].path in instance.jobs[0].paths
    invalidations = files[0].invalidations
    instance.jobs[0].complete({files[0].path: "clean"})
    assert files[0].invalidations == invalidations + 1
    files[0].emblems.clear()
    instance.update(files[0])
    assert files[0].emblems == ["gitrepo-clean"]


def test_folders_no_longer_displayed_make_room_first(provider, monkeypatch):
    instance, _ = provider
    monkeypatch.setattr(instance, "MAX_ENTRIES", 3)
    shown = [FileInfo(f"/shown-{index}") for index in range(2)]
    left = FileInfo("/left-behind")
    instance.update(left)
    for info in shown:
        instance.update(info)
    left.gone = True

    instance.update(FileInfo("/new"))

    assert "/left-behind" not in instance._entries
    assert all(info.path in instance._entries for info in shown)


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


REMOTE = [
    "/mnt/win",
    "/mnt/win/Users/me/repo",
    "/mnt/My Disk/repo",
    "/run/user/1000/gvfs/sftp:host=nas/repo",
    "/run/user/1000/doc/1a2b3c/repo",
    "/srv/share/repo",
    "/srv/nfs/repo",
    "/srv/sshfs/repo",
]
LOCAL = ["/home/me/repo", "/opt/repo", "/mnt/data/repo", "/mnt/winfoo/repo", "/mnt/My Diskette/repo", "/srv/repo"]


@pytest.mark.parametrize("path", REMOTE)
def test_fuse_and_network_mounts_are_not_probed(path):
    assert not mounts.probe_allowed(path, TABLE)


@pytest.mark.parametrize("path", LOCAL)
def test_local_filesystems_are_probed(path):
    assert mounts.probe_allowed(path, TABLE)


def test_the_most_specific_mount_wins():
    assert mounts.mount_type("/mnt/data", TABLE) == "ext4"
    assert mounts.mount_type("/mnt/win/x", TABLE) == "fuseblk"
    assert mounts.mount_type("/mnt/winfoo", TABLE) == "ext4"
    assert mounts.mount_type("/opt", TABLE) == "btrfs"
    # Mounted on top of the same point: the later mount is the one seen.
    stacked = [*TABLE, ("/mnt/win", "ext4")]
    assert mounts.mount_type("/mnt/win/x", stacked) == "ext4"


def test_mount_points_are_unescaped():
    assert ("/mnt/My Disk", "fuseblk") in TABLE
    table = mounts.parse_mountinfo(r"9 1 0:9 / /a\011b\012c\134d rw - fuse.rclone remote: rw")
    assert table == [("/a\tb\nc\\d", "fuse.rclone")]


def test_classification_never_asks_the_filesystem(monkeypatch, tmp_path):
    """Any lookup under a FUSE mount can hang; only readlink on local text may run."""

    def forbidden(*args, **kwargs):
        raise AssertionError(f"filesystem call on {args}")

    linked = tmp_path / "Windows"
    linked.symlink_to("/mnt/win")
    readlinks = []
    real_readlink = os.readlink  # The fixture's: only tmp_path holds real links.

    def readlink(path, *args, **kwargs):
        readlinks.append(os.fspath(path))
        return real_readlink(path, *args, **kwargs)

    for name in ("stat", "lstat", "statvfs", "scandir", "listdir", "access"):
        monkeypatch.setattr(os, name, forbidden)
    monkeypatch.setattr(os.path, "exists", forbidden)
    monkeypatch.setattr(os.path, "realpath", forbidden)
    for name in ("exists", "stat", "lstat", "resolve", "is_dir", "is_symlink"):
        monkeypatch.setattr(Path, name, forbidden)
    monkeypatch.setattr(os, "readlink", readlink)

    results = {path: mounts.probe_allowed(path, TABLE) for path in [*REMOTE, f"{linked}/repo"]}
    monkeypatch.undo()

    assert not any(results.values())
    assert readlinks, "the local symlink must be followed"
    assert not any(mounts.is_remote_type(mounts.mount_type(path, TABLE)) for path in readlinks)


def test_a_symlink_into_a_fuse_mount_is_not_probed(tmp_path):
    (tmp_path / "Windows").symlink_to("/mnt/win/Users")
    (tmp_path / "work").mkdir()
    (tmp_path / "shortcut").symlink_to("work")
    (tmp_path / "loop").symlink_to("loop")
    assert not mounts.probe_allowed(f"{tmp_path}/Windows/repo", TABLE)
    assert mounts.probe_allowed(f"{tmp_path}/shortcut/repo", TABLE)
    assert not mounts.probe_allowed(f"{tmp_path}/loop/repo", TABLE)


def test_unreadable_mountinfo_skips_nothing(tmp_path):
    assert mounts.read_mounts(str(tmp_path / "missing")) == []
    assert mounts.probe_allowed("/home/me/repo", [])


def test_scan_process_skips_remote_mounts_on_its_own(monkeypatch):
    probed = []
    monkeypatch.setattr(scan, "read_mounts", lambda: TABLE)
    monkeypatch.setattr(scan, "repository_state", lambda path: probed.append(path) or "clean")
    states = scan.scan(["/home/me/repo", "/mnt/win/repo", "/run/user/1000/gvfs/x", "/srv/share/repo"])
    assert probed == ["/home/me/repo"]
    assert states == {
        "/home/me/repo": "clean",
        "/mnt/win/repo": None,
        "/run/user/1000/gvfs/x": None,
        "/srv/share/repo": None,
    }


def test_remote_folders_get_no_scan_process(provider):
    instance, callbacks = provider
    remote, local = FileInfo("/mnt/win/repo"), FileInfo("/home/me/repo")
    instance.update(remote)
    instance.update(local)
    drain(callbacks)
    assert [job.paths for job in instance.jobs] == [["/home/me/repo"]]
    assert instance._entries["/mnt/win/repo"].state is None
    assert instance._entries["/mnt/win/repo"].future is None


def test_only_remote_folders_start_no_process_at_all(provider):
    instance, callbacks = provider
    for path in REMOTE:
        instance.update(FileInfo(path))
    drain(callbacks)
    assert instance.jobs == []


def test_a_mount_that_appears_later_is_skipped(provider, monkeypatch):
    instance, callbacks = provider
    info = FileInfo("/media/usb/repo")
    instance.update(info)
    drain(callbacks)
    instance.jobs[0].complete({"/media/usb/repo": "clean"})
    assert instance._entries[info.path].state == "clean"

    plugged = [*TABLE, ("/media/usb", "fuseblk")]
    monkeypatch.setattr(emblems.mounts, "read_mounts", lambda: plugged)
    instance._entries[info.path].checked = 0
    instance._refresh()
    drain(callbacks)
    assert len(instance.jobs) == 1
    assert instance._entries[info.path].state is None


def test_a_timed_out_batch_backs_off_and_keeps_its_emblems(provider):
    instance, callbacks = provider
    info = FileInfo("/home/me/repo")
    instance._entries[info.path] = emblems._Entry(files={hash(info): info.weak_ref()}, state="clean")
    instance._schedule(info.path, instance._entries[info.path])
    drain(callbacks)
    instance.jobs[0].complete({}, True)

    entry = instance._entries[info.path]
    assert entry.state == "clean"  # A timeout says nothing about the repository.
    for _ in range(3):  # The refresh timer keeps firing: no new process.
        entry.checked = 0
        instance._refresh()
        drain(callbacks)
    assert len(instance.jobs) == 1

    instance._blocked = dict.fromkeys(instance._blocked, 0)  # The backoff has passed.
    entry.checked = 0
    instance._refresh()
    drain(callbacks)
    assert len(instance.jobs) == 2


def test_no_new_process_until_a_stuck_one_has_exited(provider):
    instance, callbacks = provider
    first, second = FileInfo("/home/me/a"), FileInfo("/home/me/b")
    instance.update(first)
    drain(callbacks)
    for _ in range(3):
        instance.update(second)
        instance._refresh()
        drain(callbacks)
    assert len(instance.jobs) == 1
    instance.jobs[0].complete({}, True)
    assert [job.paths for job in instance.jobs[1:]] == [["/home/me/b"]]


def test_scan_job_reports_a_timeout_only_when_the_process_exits():
    killed, results = [], []

    class Process:
        def force_exit(self):
            killed.append(True)

        def communicate_utf8_finish(self, _result):
            return True, "", ""

        def get_successful(self):
            return False

    job = scanner.ScanJob.__new__(scanner.ScanJob)
    job._process, job._timeout, job._cancelled, job.timed_out = Process(), 0, False, False
    job._complete = lambda states, timed_out: results.append((states, timed_out))
    job._expire()
    assert killed == [True]
    assert results == []  # SIGKILL does not free a task stuck in FUSE.
    job._finished(job._process, None)
    assert results == [({}, True)]
