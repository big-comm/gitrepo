# intentional-log: subprocess fixtures print JSON for the parent test to assert.
import json
import ast
import os
import posixpath
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


@pytest.mark.parametrize("executable", ["git", "/usr/bin/git", b"git", b"/usr/bin/git"])
def test_generic_process_apis_reject_git_without_explicit_intent(executable):
    with pytest.raises(child_process.GitIntentRequiredError):
        child_process.run([executable, "status"])

    with pytest.raises(child_process.GitIntentRequiredError):
        child_process.Popen([executable, "status"])


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


def test_run_git_accepts_bytes_git_and_rejects_bytes_non_git(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(child_process._subprocess, "run", fake_run)

    child_process.run_git([b"/usr/bin/git", b"status"], intent="ordinary")

    assert calls[0][0] == [b"/usr/bin/git", b"status"]
    with pytest.raises(child_process.GitIntentRequiredError, match="Git argv"):
        child_process.run_git([b"/usr/bin/printf", b"safe"], intent="ordinary")


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


def _git_executable(command):
    if not isinstance(command, (ast.List, ast.Tuple)) or not command.elts:
        return False
    executable = command.elts[0]
    if not isinstance(executable, ast.Constant):
        return False
    try:
        value = os.fspath(executable.value)
    except TypeError:
        return False
    return posixpath.basename(value) in {"git", b"git"}


def _git_boundary_symbols(tree: ast.AST) -> tuple[set[str], dict[str, str], dict[str, ast.expr]]:
    module_aliases: set[str] = set()
    function_aliases: dict[str, str] = {}
    assignments: dict[str, ast.expr] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "gitrepo.common":
            module_aliases.update(alias.asname or alias.name for alias in node.names if alias.name == "child_process")
        elif isinstance(node, ast.Import) and any(alias.name == "gitrepo.common.child_process" for alias in node.names):
            module_aliases.update(
                alias.asname or alias.name for alias in node.names if alias.name == "gitrepo.common.child_process"
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "gitrepo.common.child_process":
            function_aliases.update(
                (alias.asname or alias.name, alias.name)
                for alias in node.names
                if alias.name in {"run", "Popen", "run_git"}
            )
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            assignments[node.targets[0].id] = node.value
    return module_aliases, function_aliases, assignments


def _git_boundary_function(node: ast.Call, module_aliases: set[str], function_aliases: dict[str, str]) -> str | None:
    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
        if node.func.value.id in module_aliases:
            return node.func.attr
    if isinstance(node.func, ast.Name):
        return function_aliases.get(node.func.id)
    return None


def _call_argument(node: ast.Call, keyword_name: str) -> ast.expr | None:
    if node.args:
        return node.args[0]
    return next((keyword.value for keyword in node.keywords if keyword.arg == keyword_name), None)


def _resolve_assignment(command: ast.expr | None, assignments: dict[str, ast.expr]) -> ast.expr | None:
    seen: set[str] = set()
    while isinstance(command, ast.Name) and command.id in assignments:
        if command.id in seen:
            break
        seen.add(command.id)
        command = assignments[command.id]
    return command


def _has_literal_git_intent(node: ast.Call) -> bool:
    intent = next((keyword.value for keyword in node.keywords if keyword.arg == "intent"), None)
    return isinstance(intent, ast.Constant) and intent.value in {"ordinary", "destructive"}


def _git_boundary_violations(source: str) -> list[int]:
    tree = ast.parse(source)
    module_aliases, function_aliases, assignments = _git_boundary_symbols(tree)

    violations: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function_name = _git_boundary_function(node, module_aliases, function_aliases)
        if function_name is None:
            continue
        command = _resolve_assignment(_call_argument(node, "args"), assignments)
        if function_name in {"run", "Popen"} and _git_executable(command):
            violations.append(node.lineno)
        if function_name == "run_git" and not _has_literal_git_intent(node):
            violations.append(node.lineno)
    return violations


def test_git_boundary_audit_covers_aliases_keyword_args_and_variables():
    unsafe = """
from gitrepo.common import child_process as process
from gitrepo.common.child_process import Popen as launch
command = ["git", "status"]
process.run(command)
launch(args=(b"/usr/bin/git", b"status"))
"""
    safe = """
from gitrepo.common import child_process as process
command = ["git", "status"]
process.run_git(args=command, intent="ordinary")
process.run(args=["printf", "safe"])
"""

    assert _git_boundary_violations(unsafe) == [5, 6]
    assert _git_boundary_violations(safe) == []


def test_git_boundary_audit_requires_literal_intent():
    unsafe = """
from gitrepo.common.child_process import run_git as git_command
intent = "ordinary"
git_command(["git", "status"])
git_command(["git", "status"], intent=intent)
git_command(["git", "status"], intent="unknown")
"""
    safe = """
from gitrepo.common.child_process import run_git as git_command
git_command(args=["git", "status"], intent="ordinary")
git_command([b"/usr/bin/git", b"reset", b"--hard"], intent="destructive")
"""

    assert _git_boundary_violations(unsafe) == [4, 5, 6]
    assert _git_boundary_violations(safe) == []


def test_git_call_sites_use_explicit_intent_without_generic_bypass():
    share = Path(__file__).resolve().parents[1] / "usr" / "share"
    violations = []
    for product in (share / "gitrepo/build_package", share / "gitrepo/build_iso"):
        for path in product.rglob("*.py"):
            violations.extend(f"{path}:{line}" for line in _git_boundary_violations(path.read_text(encoding="utf-8")))

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
        "https://api.github.com:invalid/repos/a/b",
        "https://api.github.com/repos/a/b\nignored",
    ):
        with pytest.raises(UnsafeNetworkUrl):
            validate_https_url(unsafe, {"api.github.com"})


def test_github_repository_url_is_exact_and_canonical():
    assert validate_github_repository_url("https://github.com/biglinux/iso-profiles") == (
        "https://github.com/biglinux/iso-profiles.git"
    )
    for unsafe in (
        "https://github.com/biglinux/iso-profiles?token=secret",
        "https://github.com/biglinux/iso-profiles#unexpected-fragment",
        "https://user:secret@github.com/biglinux/iso-profiles",
        "https://github.com/biglinux/iso-profiles/extra",
    ):
        with pytest.raises(UnsafeNetworkUrl):
            validate_github_repository_url(unsafe)
