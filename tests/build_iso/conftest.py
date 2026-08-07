import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest


SHARE_ROOT = Path(__file__).resolve().parents[2] / "usr" / "share"
sys.path.insert(0, str(SHARE_ROOT))


def _execute_bit_is_honoured(directory: Path) -> bool:
    """Report whether `test -x` can succeed under *directory*.

    A hardened `noexec` mount clears X_OK for every file it holds, so a test
    that exercises an `[[ -x ... ]]` branch silently takes the wrong path there.
    """
    probe = directory / ".exec-probe"
    try:
        probe.write_text("#!/bin/sh\n", encoding="utf-8")
        probe.chmod(0o755)
        return os.access(probe, os.X_OK)
    except OSError:
        return False
    finally:
        probe.unlink(missing_ok=True)


def _force_remove(directory: Path) -> None:
    """Remove *directory*, including entries a test left unreadable.

    Tests that exercise a permission failure leave modes like 0o000 behind, and
    plain rmtree() cannot descend into those. Leaving them would accumulate
    undeletable directories outside the pytest tmp tree.
    """

    # os.walk descends only after the caller has seen each (root, dirs, files),
    # so widening a directory here happens before the walk enters it. An onexc
    # retry cannot do this: rmtree does not re-scan a directory it failed on.
    os.chmod(directory, 0o700)
    for root, directories, _files in os.walk(directory):
        for name in directories:
            try:
                os.chmod(os.path.join(root, name), 0o700)
            except OSError:
                pass
    shutil.rmtree(directory)


@pytest.fixture
def exec_tmp_path(tmp_path):
    """A temporary directory where the execute bit is honoured.

    Used by tests that patch shell code branching on `[[ -x ... ]]`. Falls back
    to XDG_CACHE_HOME when the pytest tmp dir lives on a `noexec` mount.
    """
    if _execute_bit_is_honoured(tmp_path):
        yield tmp_path
        return

    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "gitrepo-tests"
    try:
        cache_root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        pytest.skip(f"no exec-capable temporary directory available: {error}")

    fallback = Path(tempfile.mkdtemp(prefix="exec-", dir=cache_root))
    try:
        if not _execute_bit_is_honoured(fallback):
            pytest.skip("no exec-capable temporary directory available")
        yield fallback
    finally:
        _force_remove(fallback)
