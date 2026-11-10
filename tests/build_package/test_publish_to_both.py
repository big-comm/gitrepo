"""One build published by both organizations, each with its own token."""

import importlib
import subprocess
from types import SimpleNamespace

import pytest


@pytest.fixture
def modules(build_package_modules, monkeypatch, tmp_path):
    monkeypatch.setenv("LANGUAGE", "en")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    repository = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repository)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "remote", "add", "origin", "https://github.com/big-comm/ashyterm.git"],
        check=True,
    )
    monkeypatch.chdir(repository)
    settings_module, token_store = build_package_modules
    tokens = {"big-comm": "tok-community", "biglinux": "tok-linux"}
    monkeypatch.setattr(token_store.TokenStore, "get_token", staticmethod(lambda org: tokens.get(org, "")))
    return SimpleNamespace(
        settings=settings_module,
        tokens=tokens,
        build=importlib.import_module("gitrepo.build_package.core.build_package"),
        operations=importlib.import_module("gitrepo.build_package.core.package_operations"),
        api=importlib.import_module("gitrepo.build_package.core.github_api"),
        destination=importlib.import_module("gitrepo.build_package.core.destination"),
        config_dir=tmp_path / "gitrepo",
    )


class Logger:
    def __init__(self):
        self.messages = []

    def log(self, style, message):
        self.messages.append((style, message))

    def text(self):
        return "\n".join(message for _style, message in self.messages)


class Response:
    def __init__(self, status_code):
        self.status_code = status_code
        self.text = ""

    def json(self):
        return {}


def _both(modules):
    bp = modules.build.BuildPackage()
    bp.logger = Logger()
    bp.set_publish_targets(["big-comm", "biglinux"])
    bp.github_api.token = modules.tokens["big-comm"]
    bp.github_api.headers = {"Authorization": "token tok-community"}
    return bp


def _capture_dispatches(modules, monkeypatch, answers):
    calls = []

    def post(url, headers=None, **kwargs):
        calls.append((url, headers.get("Authorization")))
        return Response(answers[len(calls) - 1])

    monkeypatch.setattr(modules.api.requests, "post", post)
    monkeypatch.setattr(modules.api.GitHubAPI, "_report_dispatched_run", lambda *a, **k: None)
    monkeypatch.setattr(modules.api.TokenStore, "read_all", staticmethod(lambda: list(modules.tokens.items())))
    return calls


def test_the_build_is_dispatched_to_both_principal_first_with_each_token(modules, monkeypatch):
    calls = _capture_dispatches(modules, monkeypatch, [204, 204])
    bp = _both(modules)

    assert modules.operations._trigger_package_workflow(bp, "ashyterm", "stable", "main", False)

    assert calls == [
        ("https://api.github.com/repos/big-comm/build-package/dispatches", "token tok-community"),
        ("https://api.github.com/repos/biglinux/build-package/dispatches", "token tok-linux"),
    ]
    assert "BigCommunity: build started" in bp.logger.text() and "BigLinux: build started" in bp.logger.text()


def test_one_refusal_is_reported_by_name(modules, monkeypatch):
    _capture_dispatches(modules, monkeypatch, [204, 403])
    bp = _both(modules)

    assert not modules.operations._trigger_package_workflow(bp, "ashyterm", "stable", "main", False)

    assert "BigCommunity: build started" in bp.logger.text()
    assert "BigLinux: build not started" in bp.logger.text()


def test_without_a_token_for_the_second_nothing_is_committed(modules, monkeypatch):
    modules.tokens.pop("biglinux")
    bp = _both(modules)
    bp.is_git_repo = True
    monkeypatch.setattr(bp.github_api, "ensure_github_token", lambda logger: True)
    monkeypatch.setattr(
        modules.operations, "_commit_pending_changes", lambda *a: pytest.fail("committed before checking tokens")
    )

    generate = modules.operations.commit_and_generate_package.__wrapped__
    assert generate(bp, "stable") is False
    assert "No access token is saved for biglinux" in bp.logger.text()
    assert "Nothing was committed, pushed or built." in bp.logger.text()


def test_the_choice_is_remembered_for_the_repository(modules):
    settings = modules.settings.Settings(str(modules.config_dir))
    assert modules.destination.remember_targets(settings, ["big-comm", "biglinux"])

    bp = modules.build.BuildPackage()

    assert bp.publish_targets() == ["big-comm", "biglinux"]
    assert modules.settings.Settings(str(modules.config_dir)).get("build_also_destinations") == {
        "big-comm/ashyterm": ["biglinux"]
    }


def test_the_command_line_organization_publishes_alone(modules):
    modules.destination.remember_targets(modules.settings.Settings(str(modules.config_dir)), ["big-comm", "biglinux"])
    args = modules.build.parse_arguments(["--organization", "biglinux"])

    assert modules.build.BuildPackage(args=args).publish_targets() == ["biglinux"]


def test_the_terminal_menu_offers_one_or_both(modules):
    bp = modules.build.BuildPackage()
    offered = []

    def show_menu(title, options, default_index=0, additional_content=None):
        offered.extend(options)
        return 2, options[2]

    bp.menu = SimpleNamespace(show_menu=show_menu)

    assert bp._choose_publish_targets()

    assert offered[:3] == ["BigCommunity", "BigLinux", "BigCommunity and BigLinux"]
    assert bp.publish_targets() == ["big-comm", "biglinux"]


def test_priority_exists_only_while_biglinux_publishes_alone(modules):
    bp = modules.build.BuildPackage()
    bp.set_publish_targets(["biglinux"])
    assert "priority" in bp.branch_types()

    bp.set_publish_targets(["big-comm"])
    assert "priority" not in bp.branch_types()

    # BigCommunity has no priority repository, so publishing with both leaves it out.
    bp.set_publish_targets(["biglinux", "big-comm"])
    assert bp.branch_types() == ("testing", "stable", "extra")


def test_a_priority_build_is_dispatched_from_main(modules, monkeypatch):
    calls = []
    monkeypatch.setattr(modules.api.requests, "post", lambda url, json=None, **kw: calls.append(json) or Response(204))
    monkeypatch.setattr(modules.api.GitHubAPI, "_report_dispatched_run", lambda *a, **k: None)
    monkeypatch.setattr(modules.api.TokenStore, "read_all", staticmethod(lambda: list(modules.tokens.items())))

    api = modules.api.GitHubAPI("tok-linux", "biglinux")
    assert api.trigger_workflow("bigocrpdf", "priority", "dev-talesam", False, False, Logger())

    payload = calls[0]["client_payload"]
    assert payload["branch_type"] == "priority" and payload["branch"] == "main"
    assert "new_branch" not in payload


def test_the_progress_window_follows_every_build(build_package_modules):
    pytest.importorskip("gi")
    from gitrepo.build_package.gui.dialogs.progress_dialog import ProgressDialog

    log = (
        "URL to monitor the build: https://github.com/big-comm/build-package/actions\n"
        "Build #2797 started: https://github.com/big-comm/build-package/actions/runs/111\n"
        "URL to monitor the build: https://github.com/biglinux/build-package/actions\n"
        "Repository: https://github.com/biglinux/bigocrpdf\n"
    )
    buffer = type(
        "Buffer",
        (),
        {"get_start_iter": lambda self: 0, "get_end_iter": lambda self: 1, "get_text": lambda self, a, b, c: log},
    )()
    dialog = ProgressDialog.__new__(ProgressDialog)
    dialog.details_buffer = buffer

    assert dialog._extract_github_urls() == [
        "https://github.com/big-comm/build-package/actions/runs/111",
        "https://github.com/biglinux/build-package/actions",
    ]
