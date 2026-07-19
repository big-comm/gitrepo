import importlib
import json

from gitrepo.common import token_store as shared_token_store
from gitrepo.common.atomic_file import AtomicWriteError


def _use_memory_secret(monkeypatch, initial=None, store_succeeds=True):
    secret = {"payload": initial}

    def lookup(_schema, _attributes, _cancellable):
        return secret["payload"]

    def store(_schema, _attributes, _collection, _label, payload, _cancellable):
        if store_succeeds:
            secret["payload"] = payload
        return store_succeeds

    monkeypatch.setattr(shared_token_store.Secret, "password_lookup_sync", lookup)
    monkeypatch.setattr(shared_token_store.Secret, "password_store_sync", store)
    return secret


def test_settings_round_trip(build_package_modules, tmp_path):
    settings_module, _ = build_package_modules
    config_dir = tmp_path / "gitrepo"

    settings = settings_module.Settings(str(config_dir))
    assert settings.set("auto_version_bump", False) is True

    reloaded = settings_module.Settings(str(config_dir))
    assert reloaded.get("auto_version_bump") is False
    assert (config_dir / "config.json").stat().st_mode & 0o777 == 0o600


def test_settings_set_rolls_back_when_publication_fails(build_package_modules, monkeypatch, tmp_path):
    settings_module, _ = build_package_modules
    settings = settings_module.Settings(str(tmp_path / "gitrepo"))
    original = settings.get("auto_version_bump")

    def fail_write(value):
        raise AtomicWriteError("injected failure")

    monkeypatch.setattr(settings._store, "write", fail_write)

    assert settings.set("auto_version_bump", False) is False
    assert settings.get("auto_version_bump") == original


def test_corrupt_settings_are_preserved(build_package_modules, tmp_path):
    settings_module, _ = build_package_modules
    config_dir = tmp_path / "gitrepo"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    config_file.write_text('{"broken":', encoding="utf-8")

    settings = settings_module.Settings(str(config_dir))

    assert settings.last_load_error
    assert config_file.read_text(encoding="utf-8") == '{"broken":'


def test_retired_welcome_settings_are_ignored_without_rewriting(build_package_modules, tmp_path):
    settings_module, _ = build_package_modules
    config_dir = tmp_path / "gitrepo"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    document = settings_module.Settings(str(tmp_path / "defaults")).get_defaults()
    document.update(
        {
            "auto_version_bump": False,
            "show_welcome_on_startup": False,
            "show_welcome": False,
            "first_run_completed": True,
        }
    )
    original = json.dumps(document)
    config_file.write_text(original, encoding="utf-8")

    settings = settings_module.Settings(str(config_dir))

    assert settings.last_load_error == ""
    assert settings.get("auto_version_bump") is False
    assert settings.get("show_welcome") is None
    assert config_file.read_text(encoding="utf-8") == original


def test_legacy_disabled_destructive_confirmation_is_normalized(build_package_modules, tmp_path):
    settings_module, _ = build_package_modules
    config_dir = tmp_path / "gitrepo"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    document = settings_module.Settings(str(tmp_path / "defaults")).get_defaults()
    document["confirm_destructive"] = False
    config_file.write_text(json.dumps(document), encoding="utf-8")

    settings = settings_module.Settings(str(config_dir))

    assert settings.get("confirm_destructive") is True
    assert settings.set("confirm_destructive", False) is False
    assert settings.get("confirm_destructive") is True


def test_plan_without_safe_preview_still_confirms_destructive_operations(build_package_modules):
    importlib.import_module("gitrepo.build_package.core.settings")
    preview_module = importlib.import_module("gitrepo.build_package.core.operation_preview")

    class Logger:
        def __init__(self):
            self.messages = []

        def log(self, style, message):
            self.messages.append((style, message))

    class Menu:
        def __init__(self):
            self.questions = []

        def confirm(self, question):
            self.questions.append(question)
            return False

    logger = Logger()
    menu = Menu()
    plan = preview_module.OperationPlan(logger, menu, show_preview=False)
    plan.add("Discard local changes", ["git", "reset", "--hard", "HEAD"], destructive=True)

    assert plan.execute_with_confirmation() is False
    assert len(menu.questions) == 1
    assert any("git reset --hard HEAD" in message for _, message in logger.messages)


def test_token_store_round_trip_uses_libsecret(build_package_modules, monkeypatch, tmp_path):
    _, token_module = build_package_modules
    token_file = tmp_path / "github_token"
    monkeypatch.setattr(token_module, "TOKEN_FILE", str(token_file))
    monkeypatch.setattr(token_module, "TOKEN_FILE_LEGACY", str(tmp_path / "legacy"))
    secret = _use_memory_secret(monkeypatch)

    assert token_module.TokenStore.upsert("biglinux", "secret-value") is True
    assert token_module.TokenStore.get_token("biglinux") == "secret-value"
    assert "secret-value" in secret["payload"]
    assert not token_file.exists()


def test_failed_token_migration_preserves_legacy(build_package_modules, monkeypatch, tmp_path):
    _, token_module = build_package_modules
    token_file = tmp_path / "github_token"
    legacy = tmp_path / "legacy"
    legacy.write_text("secret-value\n", encoding="utf-8")
    monkeypatch.setattr(token_module, "TOKEN_FILE", str(token_file))
    monkeypatch.setattr(token_module, "TOKEN_FILE_LEGACY", str(legacy))

    _use_memory_secret(monkeypatch, store_succeeds=False)

    token_module.TokenStore.migrate_if_needed()

    assert legacy.read_text(encoding="utf-8") == "secret-value\n"
    assert not token_file.exists()


def test_successful_token_migration_removes_cleartext_files(build_package_modules, monkeypatch, tmp_path):
    _, token_module = build_package_modules
    token_file = tmp_path / "github_token"
    legacy = tmp_path / "legacy"
    token_file.write_text("biglinux=organization-secret\n", encoding="utf-8")
    legacy.write_text("default-secret\n", encoding="utf-8")
    monkeypatch.setattr(token_module, "TOKEN_FILE", str(token_file))
    monkeypatch.setattr(token_module, "TOKEN_FILE_LEGACY", str(legacy))
    _use_memory_secret(monkeypatch)

    token_module.TokenStore.migrate_if_needed()

    assert token_module.TokenStore.get_token("biglinux") == "organization-secret"
    assert not token_file.exists()
    assert not legacy.exists()
