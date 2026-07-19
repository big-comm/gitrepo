# intentional-log: subprocess fixtures print JSON for the parent test to assert.
import json
import ast
import subprocess
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "usr" / "share"))

from gitrepo.common import child_process  # noqa: E402
from gitrepo.common.render_environment import (  # noqa: E402
    GSK_RENDERER_MARKER,
    child_process_environment,
    configure_gtk_renderer,
)
from gitrepo.common.network_url import (  # noqa: E402
    UnsafeNetworkUrl,
    validate_github_repository_url,
    validate_https_url,
)


def test_cairo_is_injected_only_when_renderer_is_absent():
    environment = {}

    assert configure_gtk_renderer(environment) is True
    assert environment == {"GSK_RENDERER": "cairo", GSK_RENDERER_MARKER: "1"}

    external = {"GSK_RENDERER": "gl"}
    assert configure_gtk_renderer(external) is False
    assert external == {"GSK_RENDERER": "gl"}


def test_only_gitrepo_injection_is_removed_from_child_environment():
    injected = {"GSK_RENDERER": "cairo", GSK_RENDERER_MARKER: "1", "KEEP": "yes"}
    external = {"GSK_RENDERER": "vulkan", "KEEP": "yes"}

    assert child_process_environment(injected) == {"KEEP": "yes"}
    assert child_process_environment(external) == external


def test_real_child_does_not_inherit_injected_renderer(monkeypatch):
    monkeypatch.setenv("GSK_RENDERER", "cairo")
    monkeypatch.setenv(GSK_RENDERER_MARKER, "1")
    command = [
        sys.executable,
        "-c",
        "import json, os; print(json.dumps([os.environ.get('GSK_RENDERER'), "
        f"os.environ.get('{GSK_RENDERER_MARKER}')]))",
    ]

    result = child_process.run(command, check=True, capture_output=True, text=True)

    assert json.loads(result.stdout) == [None, None]


def test_real_child_preserves_external_renderer(monkeypatch):
    monkeypatch.setenv("GSK_RENDERER", "gl")
    monkeypatch.delenv(GSK_RENDERER_MARKER, raising=False)

    result = child_process.run(
        [sys.executable, "-c", "import os; print(os.environ['GSK_RENDERER'])"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "gl"


def test_generic_process_apis_reject_git_without_explicit_intent():
    with pytest.raises(child_process.GitIntentRequiredError):
        child_process.run(["git", "status"])

    with pytest.raises(child_process.GitIntentRequiredError):
        child_process.Popen(["/usr/bin/git", "status"])


def test_run_git_ordinary_preserves_argv_and_sanitized_environment(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(child_process._subprocess, "run", fake_run)
    command = ["/usr/bin/git", "-C", "/tmp/repository", "status", "--short"]

    child_process.run_git(
        command,
        intent="ordinary",
        env={"GSK_RENDERER": "cairo", GSK_RENDERER_MARKER: "1", "KEEP": "yes"},
    )

    assert calls == [(command, {"env": {"KEEP": "yes"}})]


def test_run_git_destructive_requires_authorization(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(child_process._subprocess, "run", fake_run)
    command = ["git", "reset", "--hard", "HEAD"]

    with pytest.raises(child_process.DestructiveGitCommandError):
        child_process.run_git(command, intent="destructive")

    with child_process.authorize_destructive_git():
        child_process.run_git(command, intent="destructive")

    assert calls[0][0] == command


def test_run_git_rejects_invalid_intent_and_non_git_argv():
    with pytest.raises(ValueError, match="intent"):
        child_process.run_git(["git", "status"], intent="unknown")

    with pytest.raises(child_process.GitIntentRequiredError, match="Git argv"):
        child_process.run_git(["printf", "not git"], intent="ordinary")


def test_literal_git_call_sites_use_run_git_with_literal_intent():
    share = Path(__file__).resolve().parents[1] / "usr" / "share"
    violations = []
    for product in (share / "gitrepo/build_package", share / "gitrepo/build_iso"):
        for path in product.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                command = node.args[0]
                if not isinstance(command, (ast.List, ast.Tuple)) or not command.elts:
                    continue
                function = node.func
                if not (
                    isinstance(function, ast.Attribute)
                    and isinstance(function.value, ast.Name)
                    and function.value.id == "subprocess"
                ):
                    continue
                executable = command.elts[0]
                if not isinstance(executable, ast.Constant) or Path(str(executable.value)).name != "git":
                    continue
                function_name = function.attr
                intent = next((keyword.value for keyword in node.keywords if keyword.arg == "intent"), None)
                if (
                    function_name != "run_git"
                    or not isinstance(intent, ast.Constant)
                    or intent.value not in {"ordinary", "destructive"}
                ):
                    violations.append(f"{path}:{node.lineno}")

    assert violations == []


def test_applications_do_not_bypass_child_process_boundary():
    share = Path(__file__).resolve().parents[1] / "usr" / "share"
    bypasses = []
    for product in (share / "gitrepo/build_package", share / "gitrepo/build_iso"):
        for path in product.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import) and any(alias.name == "subprocess" for alias in node.names):
                    bypasses.append(f"{path}:{node.lineno}")
                if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
                    bypasses.append(f"{path}:{node.lineno}")

    assert bypasses == []


def test_gui_configures_renderer_before_importing_gtk():
    share = Path(__file__).resolve().parents[1] / "usr" / "share"
    for relative in ("gitrepo/build_package/gui/main_gui.py", "gitrepo/build_iso/gui/main_gui.py"):
        source = (share / relative).read_text(encoding="utf-8")
        assert source.index("configure_gtk_renderer()") < source.index("import gi")


def test_network_urls_require_allowlisted_https_without_credentials():
    assert validate_https_url("https://api.github.com/repos/a/b", {"api.github.com"}) == (
        "https://api.github.com/repos/a/b"
    )
    for unsafe in (
        "http://api.github.com/repos/a/b",
        "file:///etc/passwd",
        "https://user:secret@api.github.com/repos/a/b",
        "https://api.github.com.evil.invalid/repos/a/b",
    ):
        with pytest.raises(UnsafeNetworkUrl):
            validate_https_url(unsafe, {"api.github.com"})


def test_github_repository_url_is_exact_and_canonical():
    assert validate_github_repository_url("https://github.com/biglinux/iso-profiles") == (
        "https://github.com/biglinux/iso-profiles.git"
    )
    for unsafe in (
        "https://github.com/biglinux/iso-profiles?token=secret",
        "https://user:secret@github.com/biglinux/iso-profiles",
        "https://github.com/biglinux/iso-profiles/extra",
    ):
        with pytest.raises(UnsafeNetworkUrl):
            validate_github_repository_url(unsafe)
