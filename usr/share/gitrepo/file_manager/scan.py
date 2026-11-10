"""Batch status probes outside the file manager's embedded Python runtime."""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gitrepo.file_manager.mounts import probe_allowed, read_mounts
from gitrepo.file_manager.status import repository_state


def scan(paths):
    """States of PATHS; FUSE and network mounts are never touched.

    The provider already filters them; this guards against a mount that
    appeared between its check and this process.
    """
    mounts = read_mounts()
    local = [path for path in paths if isinstance(path, str) and probe_allowed(path, mounts)]
    states = dict.fromkeys(path for path in paths if isinstance(path, str))
    with ThreadPoolExecutor(max_workers=4) as workers:
        states.update(zip(local, workers.map(repository_state, local)))
    return states


def main():
    json.dump(scan(json.load(sys.stdin)), sys.stdout)


if __name__ == "__main__":
    main()
