"""Tell FUSE and network mounts apart without touching the path itself.

Any lookup under a FUSE or network mount (stat, exists, statvfs, realpath)
waits for its server, and that wait ignores SIGKILL: after a resume, an NTFS
partition (ntfs-3g) or gvfs left the probe stuck in uninterruptible sleep until
the kernel panicked on the hung task. The mount is therefore found by matching
the path's text against /proc/self/mountinfo, never by asking the filesystem.
"""

from __future__ import annotations

import os
import re

MOUNTINFO = "/proc/self/mountinfo"

# fuse.* covers gvfsd-fuse, sshfs, rclone and the document portal.
REMOTE_TYPES = frozenset(
    {
        "fuse",
        "fuseblk",
        "cifs",
        "smb3",
        "smbfs",
        "nfs",
        "nfs4",
        "9p",
        "afs",
        "ceph",
        "glusterfs",
        "davfs",
        "autofs",  # Looking inside triggers the mount, often a network one.
    }
)

_ESCAPE = re.compile(r"\\([0-7]{3})")
_MAX_SYMLINKS = 40


def _unescape(field: str) -> str:
    """mountinfo writes space, tab, newline and backslash as \\040, \\011, \\012, \\134."""
    return _ESCAPE.sub(lambda match: chr(int(match[1], 8)), field)


def parse_mountinfo(text: str) -> list[tuple[str, str]]:
    """Return (mount point, filesystem type) in mount order."""
    mounts = []
    for line in text.splitlines():
        fields = line.split(" ")
        try:
            separator = fields.index("-", 6)  # Optional fields end with a lone "-".
            mounts.append((_unescape(fields[4]), fields[separator + 1]))
        except (ValueError, IndexError):
            continue
    return mounts


def read_mounts(source: str = MOUNTINFO) -> list[tuple[str, str]]:
    try:
        with open(source, encoding="utf-8", errors="surrogateescape") as mountinfo:
            return parse_mountinfo(mountinfo.read())
    except OSError:
        return []


def is_remote_type(fstype: str) -> bool:
    return fstype in REMOTE_TYPES or fstype.startswith("fuse.")


def mount_type(path: str, mounts: list[tuple[str, str]]) -> str | None:
    """Filesystem type of the most specific mount containing PATH, by text only.

    Among equal mount points the last one wins: it is mounted on top.
    """
    best, best_type = -1, None
    for point, fstype in mounts:
        inside = point == "/" or path == point or path.startswith(point.rstrip("/") + "/")
        if inside and len(point) >= best:
            best, best_type = len(point), fstype
    return best_type


def _on_remote(path: str, mounts) -> bool:
    fstype = mount_type(path, mounts)
    return fstype is not None and is_remote_type(fstype)


def probe_allowed(path: str, mounts: list[tuple[str, str]]) -> bool:
    """True when PATH, with its symlinks followed, lies on a local filesystem.

    Symlinks are followed one component at a time, and each component is
    classified by text before readlink touches it: ~/Windows -> /mnt/win must
    not send the probe into the NTFS mount. Nothing is ever asked of a
    component that sits on a FUSE or network mount.
    """
    if not path.startswith("/"):
        return False
    current, pending, hops = "/", path.split("/")[::-1], 0
    while pending:
        name = pending.pop()
        if name in ("", "."):
            continue
        if name == "..":
            current = os.path.dirname(current)
            continue
        candidate = os.path.join(current, name)
        if _on_remote(candidate, mounts):
            return False
        try:
            target = os.readlink(candidate)
        except OSError:  # Not a symlink, or gone: the text is the path.
            current = candidate
            continue
        hops += 1
        if hops > _MAX_SYMLINKS:
            return False
        if target.startswith("/"):
            current = "/"
        pending.extend(target.split("/")[::-1])
    return not _on_remote(current, mounts)
