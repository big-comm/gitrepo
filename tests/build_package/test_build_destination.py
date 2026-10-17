"""Build destination: which organization's robot builds and publishes (BigCommunity or BigLinux)."""

import importlib
import subprocess
from types import SimpleNamespace

import pytest


@pytest.fixture
def modules(build_package_modules, monkeypatch, tmp_path):
    # Settings() inside BuildPackage reads $XDG_CONFIG_HOME/gitrepo: keep it in tmp.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # Outside any repository only the saved default applies; the tests below
    # that need an origin create their own repository.
    work = tmp_path / "outside"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    settings_module, _token_store = build_package_modules
    return SimpleNamespace(
        settings=settings_module,
        build=importlib.import_module("gitrepo.build_package.core.build_package"),
        operations=importlib.import_module("gitrepo.build_package.core.package_operations"),
        config=importlib.import_module("gitrepo.build_package.core.config"),
        config_dir=tmp_path / "gitrepo",
    )


def test_default_destination_is_bigcommunity(modules):
    assert modules.settings.Settings(str(modules.config_dir)).get("build_destination") == "big-comm"
    instance = modules.build.BuildPackage()
    assert instance.organization == "big-comm" and instance.repo_workflow == "big-comm/build-package"
    assert instance.args.organization == "big-comm"


def test_saved_destination_becomes_the_default(modules):
    assert modules.settings.Settings(str(modules.config_dir)).set("build_destination", "biglinux")
    instance = modules.build.BuildPackage()
    assert instance.organization == "biglinux" and instance.repo_workflow == "biglinux/build-package"
    assert instance.branch_types() == ("testing", "stable", "extra")


def test_command_line_wins_over_saved_default(modules):
    modules.settings.Settings(str(modules.config_dir)).set("build_destination", "biglinux")
    args = modules.build.parse_arguments(["--organization", "big-comm"])
    instance = modules.build.BuildPackage(args=args)
    assert instance.organization == "big-comm" and "extra" in instance.branch_types()


def test_switching_destination_resets_the_github_client(modules):
    instance = modules.build.BuildPackage()
    old_api = instance.github_api
    instance.github_user_name = "talesam"
    assert instance.set_organization("biglinux")
    assert instance.github_api is not old_api and instance.github_api.organization == "biglinux"
    assert instance.repo_workflow == "biglinux/build-package" and instance._github_user_name == ""
    assert not instance.set_organization("someone-else") and instance.organization == "biglinux"


def test_a_destination_refuses_a_repository_it_does_not_have(modules, monkeypatch):
    monkeypatch.setitem(modules.config.DESTINATION_BRANCHES, "biglinux", ("testing", "stable"))
    instance = modules.build.BuildPackage()
    instance.set_organization("biglinux")
    messages = []
    instance.logger = SimpleNamespace(log=lambda color, text: messages.append(text))
    instance.is_git_repo = True
    # __wrapped__: the operation itself, without the repository lock of the journey
    generate = modules.operations.commit_and_generate_package.__wrapped__
    assert generate(instance, "extra") is False
    assert any("BigLinux" in m and "extra" in m for m in messages)


def test_dispatch_goes_to_the_selected_organization(modules, monkeypatch):
    api_module = importlib.import_module("gitrepo.build_package.core.github_api")
    calls = []

    class Response:
        status_code = 204

    monkeypatch.setattr(api_module.requests, "post", lambda url, **kw: calls.append((url, kw["json"])) or Response())
    monkeypatch.setattr(api_module.GitHubAPI, "_report_dispatched_run", lambda *a, **k: None)
    monkeypatch.setattr(api_module.GitUtils, "get_repo_name", staticmethod(lambda: "biglinux/bigcontrolcenter"))
    api = api_module.GitHubAPI("token", "biglinux")
    logger = SimpleNamespace(log=lambda *a: None)
    assert api.trigger_workflow("bigcontrolcenter", "stable", "", False, False, logger)
    url, body = calls[0]
    assert url == "https://api.github.com/repos/biglinux/build-package/dispatches"
    assert body["client_payload"]["branch_type"] == "stable"
    assert body["client_payload"]["url"] == "https://github.com/biglinux/bigcontrolcenter"


def _repository(tmp_path, monkeypatch, origin):
    """A repository whose origin is github.com/OWNER/NAME, entered as the current directory."""
    path = tmp_path / origin.replace("/", "-")
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin", f"https://github.com/{origin}.git"], check=True)
    monkeypatch.chdir(path)
    return path


def _settings(modules):
    return modules.settings.Settings(str(modules.config_dir))


def test_the_origin_owner_picks_the_destination_of_a_new_repository(modules, tmp_path, monkeypatch):
    _settings(modules).set("build_destination", "big-comm")
    _repository(tmp_path, monkeypatch, "biglinux/big-multimedia")
    assert modules.build.BuildPackage().organization == "biglinux"

    _settings(modules).set("build_destination", "biglinux")
    _repository(tmp_path, monkeypatch, "big-comm/gitrepo")
    assert modules.build.BuildPackage().organization == "big-comm"


def test_a_choice_is_kept_for_its_repository_only(modules, tmp_path, monkeypatch):
    destination = importlib.import_module("gitrepo.build_package.core.destination")
    _repository(tmp_path, monkeypatch, "biglinux/big-multimedia")
    assert destination.remember_destination(_settings(modules), "big-comm")
    assert modules.build.BuildPackage().organization == "big-comm"

    # Another BigLinux repository still starts from its own owner.
    _repository(tmp_path, monkeypatch, "biglinux/bigcontrolcenter")
    assert modules.build.BuildPackage().organization == "biglinux"

    # The choice survives a new Settings read, keyed by owner/repository.
    assert _settings(modules).get("build_destinations") == {"biglinux/big-multimedia": "big-comm"}


def test_a_repository_outside_both_organizations_uses_the_last_choice(modules, tmp_path, monkeypatch):
    destination = importlib.import_module("gitrepo.build_package.core.destination")
    _repository(tmp_path, monkeypatch, "biglinux/big-multimedia")
    destination.remember_destination(_settings(modules), "biglinux")

    _repository(tmp_path, monkeypatch, "talesam/my-fork")
    assert modules.build.BuildPackage().organization == "biglinux"


def test_the_command_line_still_wins_over_the_repository_choice(modules, tmp_path, monkeypatch):
    _repository(tmp_path, monkeypatch, "biglinux/big-multimedia")
    args = modules.build.parse_arguments(["--organization", "big-comm"])
    assert modules.build.BuildPackage(args=args).organization == "big-comm"


def test_an_unknown_destination_is_not_remembered(modules, tmp_path, monkeypatch):
    destination = importlib.import_module("gitrepo.build_package.core.destination")
    _repository(tmp_path, monkeypatch, "biglinux/big-multimedia")
    assert not destination.remember_destination(_settings(modules), "someone-else")
    assert _settings(modules).get("build_destinations") == {}
