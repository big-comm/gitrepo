import json

from gitrepo.build_iso.core.history_store import BuildHistoryStore
from gitrepo.build_iso.core.settings import Settings
from gitrepo.build_iso.local_config import LocalConfig
from gitrepo.common.atomic_file import AtomicWriteError


def test_settings_round_trip(tmp_path):
    config_file = tmp_path / "build-iso" / "settings.json"
    settings = Settings(config_file=str(config_file))

    assert settings.set("general", "distribution", "biglinux") is True

    reloaded = Settings(config_file=str(config_file))
    assert reloaded.distribution == "biglinux"
    assert config_file.stat().st_mode & 0o777 == 0o600


def test_settings_set_rolls_back_when_publication_fails(monkeypatch, tmp_path):
    settings = Settings(config_file=str(tmp_path / "settings.json"))
    original = (settings.distribution, settings.edition)

    def fail_write(value):
        raise AtomicWriteError("injected failure")

    monkeypatch.setattr(settings._store, "write", fail_write)

    assert (
        settings.set_many(
            {
                ("general", "distribution"): "biglinux",
                ("general", "edition"): "kde",
            }
        )
        is False
    )
    assert (settings.distribution, settings.edition) == original


def test_retired_first_run_setting_is_ignored_without_rewriting(tmp_path):
    config_file = tmp_path / "settings.json"
    document = Settings.DEFAULTS.copy()
    document["first_run"] = False
    original = json.dumps(document)
    config_file.write_text(original, encoding="utf-8")

    settings = Settings(config_file=str(config_file))

    assert settings.last_load_error == ""
    assert settings.distribution == "bigcommunity"
    assert settings.get("first_run") is None
    assert config_file.read_text(encoding="utf-8") == original


def test_invalid_settings_are_preserved_and_reported(tmp_path):
    config_file = tmp_path / "settings.json"
    config_file.write_text('{"version":', encoding="utf-8")
    settings = Settings(config_file=str(config_file))

    assert settings.last_load_error
    assert config_file.read_text(encoding="utf-8") == '{"version":'
    assert settings.distribution == "bigcommunity"


def test_legacy_cli_settings_are_imported_without_removing_source(tmp_path):
    legacy_file = tmp_path / "legacy" / "config.json"
    canonical_file = tmp_path / "gitrepo" / "build-iso.json"
    legacy_file.parent.mkdir()
    legacy_document = {
        "output_dir": str(tmp_path / "ISO"),
        "distroname": "biglinux",
        "edition": "kde",
        "manjaro_branch": "testing",
        "biglinux_branch": "testing",
        "bigcommunity_branch": "stable",
        "kernel": "latest",
    }
    legacy_file.write_text(json.dumps(legacy_document), encoding="utf-8")

    settings = Settings(config_file=str(canonical_file), legacy_files=(str(legacy_file),))

    assert settings.distribution == "biglinux"
    assert settings.edition == "kde"
    assert settings.branches["manjaro"] == "testing"
    assert settings.migration_source == str(legacy_file)
    assert legacy_file.exists()
    assert canonical_file.stat().st_mode & 0o777 == 0o600


def test_corrupt_legacy_settings_are_preserved_without_publishing_defaults(tmp_path):
    legacy_file = tmp_path / "legacy.json"
    canonical_file = tmp_path / "build-iso.json"
    legacy_file.write_text('{"output_dir":', encoding="utf-8")

    settings = Settings(config_file=str(canonical_file), legacy_files=(str(legacy_file),))

    assert settings.last_load_error
    assert settings.distribution == "bigcommunity"
    assert legacy_file.read_text(encoding="utf-8") == '{"output_dir":'
    assert not canonical_file.exists()


def test_terminal_local_config_uses_canonical_store(tmp_path):
    settings = Settings(config_file=str(tmp_path / "build-iso.json"))
    local_config = LocalConfig(settings)

    assert local_config.save_config({"edition": "kde", "kernel": "latest"}) is True

    reloaded = Settings(config_file=str(tmp_path / "build-iso.json"))
    assert reloaded.edition == "kde"
    assert reloaded.kernel == "latest"


def test_history_round_trip_is_bounded_and_clear_is_idempotent(tmp_path):
    path = tmp_path / "history.json"
    store = BuildHistoryStore(str(path))

    for number in range(105):
        assert store.add({"number": number}) is True

    assert [entry["number"] for entry in store.load()] == list(range(5, 105))
    assert store.clear() is True
    assert store.clear() is True
    assert store.load() == []


def test_corrupt_history_is_not_overwritten(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("not json", encoding="utf-8")
    store = BuildHistoryStore(str(path))

    assert store.add({"success": True}) is False
    assert store.last_error
    assert path.read_text(encoding="utf-8") == "not json"


def test_history_rejects_non_object_entries(tmp_path):
    path = tmp_path / "history.json"
    path.write_text(json.dumps(["invalid"]), encoding="utf-8")
    store = BuildHistoryStore(str(path))

    assert store.load() == []
    assert store.last_error == "history entries must be objects"
