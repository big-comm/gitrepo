"""Build destination: which organization's robot builds and publishes (BigCommunity or BigLinux)."""

import importlib
from types import SimpleNamespace

import pytest


@pytest.fixture
def modules(build_package_modules, monkeypatch, tmp_path):
    # Settings() inside BuildPackage reads $XDG_CONFIG_HOME/gitrepo: keep it in tmp.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
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
    assert instance.branch_types() == ("testing", "stable")


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


def test_biglinux_refuses_the_extra_repository(modules):
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
