import os
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "usr" / "share"))

from gitrepo.common.atomic_file import (  # noqa: E402
    AtomicJsonStore,
    AtomicWriteError,
    CorruptJsonError,
    atomic_write_text,
)


def test_atomic_json_round_trip_and_permissions(tmp_path):
    path = tmp_path / "config" / "settings.json"
    store = AtomicJsonStore(path)

    store.write({"enabled": True})

    assert store.read() == {"enabled": True}
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(path.parent.glob(f".{path.name}.*"))


def test_corrupt_json_is_preserved(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"truncated":', encoding="utf-8")
    store = AtomicJsonStore(path)

    with pytest.raises(CorruptJsonError):
        store.read()

    assert path.read_text(encoding="utf-8") == '{"truncated":'


def test_failed_replace_preserves_previous_file(monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"version": 1}\n', encoding="utf-8")

    def fail_replace(source, target):
        raise OSError("injected replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(AtomicWriteError):
        atomic_write_text(path, '{"version": 2}\n')

    assert path.read_text(encoding="utf-8") == '{"version": 1}\n'
    assert not list(tmp_path.glob(f".{path.name}.*"))


def test_symlink_target_is_rejected(tmp_path):
    original = tmp_path / "original"
    original.write_text("keep", encoding="utf-8")
    target = tmp_path / "settings.json"
    target.symlink_to(original)

    with pytest.raises(AtomicWriteError):
        atomic_write_text(target, "replace")

    assert original.read_text(encoding="utf-8") == "keep"
