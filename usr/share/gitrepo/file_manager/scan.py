"""Batch status probes outside the file manager's embedded Python runtime."""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gitrepo.file_manager.status import repository_state


def main():
    paths = json.load(sys.stdin)
    with ThreadPoolExecutor(max_workers=4) as workers:
        states = dict(zip(paths, workers.map(repository_state, paths)))
    json.dump(states, sys.stdout)


if __name__ == "__main__":
    main()
