# Shared Foundations and Launchers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make GitRepo's shared Python contracts and four public launchers exemplary, specification-aligned, semantically accurate, and practically verified without changing their public command contracts.

**Architecture:** Keep the four public commands as small Bash launchers backed by one shared Bash helper that resolves the installed `usr/share` tree and replaces the caller with a canonical Python module. Keep shared Python behavior in `gitrepo.common`, harden its existing process, URL, persistence, credential, logging, render-environment, translation, and GTK contracts in place, and avoid new abstractions or dependencies.

**Tech Stack:** Bash 5, Python 3.10+, pytest, Ruff, Mypy, Pyright, GTK4/PyGObject, libsecret, Rich, ShellCheck, Shfmt, Arch `makepkg`, KDE/KWin, AT-SPI.

## Global Constraints

- Preserve `gitrepo [DIRECTORY]`, `bpkg [OPTIONS]`, `build-iso`, and `biso [OPTIONS]`, including documented arguments, streams, exit statuses, Python destinations, and observable effects.
- Change a public contract only for a demonstrated defect, security issue, or conflict with an authoritative upstream specification.
- Add no production dependency.
- Use explicit subprocess argument sequences without shell interpretation.
- Keep synchronous libsecret calls off GTK's main thread; the CLI may call them synchronously.
- Preserve corrupt durable data and the previous published file whenever atomic publication fails before replacement.
- Remove code only after import, call-site, integration, documentation, test, and practical-execution evidence confirms that it is dead.
- Keep English in code, comments, tests, and project documentation.
- Format only the exact accepted files for each task.
- Preserve unrelated staged, unstaged, and untracked work.

## File map

- Create `tests/test_launchers.py`: executable contract tests for all four public launchers.
- Create `usr/lib/gitrepo/launcher.bash`: shared strict-mode, source-tree resolution, `PYTHONPATH`, and Python-module execution contract.
- Create `tests/test_rich_logger.py`: terminal and persistent-log secret-redaction contract.
- Modify `usr/bin/gitrepo`: Bash launcher plus repository-directory validation.
- Modify `usr/bin/bpkg`: Bash launcher for the Build Package CLI module.
- Modify `usr/bin/build-iso`: Bash launcher for the Build ISO GTK module.
- Modify `usr/bin/biso`: Bash launcher for the Build ISO CLI module.
- Modify `usr/share/gitrepo/common/child_process.py`: Git global-option parsing and destructive-command classification.
- Modify `usr/share/gitrepo/common/network_url.py`: malformed URL and GitHub fragment handling.
- Modify `usr/share/gitrepo/common/rich_logger.py`: redact diagnostics before terminal and file publication.
- Modify `tests/test_render_environment.py`: process-boundary and URL regression coverage.
- Modify `pyproject.toml`: make Pyright's external-import policy match the system-package environment while retaining Mypy and runtime import enforcement.
- Modify `README.md`: accurately document Bash launchers and tested source-tree usage.
- Modify `MAINTENANCE.md`: record upstream contracts, exact validation commands, dead-code evidence, and troubleshooting.

---

### Task 1: Preserve the four launcher contracts in Bash

**Files:**
- Create: `tests/test_launchers.py`
- Create: `usr/lib/gitrepo/launcher.bash`
- Modify: `usr/bin/gitrepo`
- Modify: `usr/bin/bpkg`
- Modify: `usr/bin/build-iso`
- Modify: `usr/bin/biso`

**Interfaces:**
- Consumes: `gitrepo.build_package.gui.main_gui.main()`, `gitrepo.build_package.cli.main_cli.main()`, `gitrepo.build_iso.gui.main_gui.main()`, and `gitrepo.build_iso.cli.main()`.
- Produces: the unchanged commands `gitrepo`, `bpkg`, `build-iso`, and `biso`, now executed by `/usr/bin/bash` and delegating through `gitrepo_exec_python_module()` in one shared helper.

- [ ] **Step 1: Add failing launcher contract tests**

Create `tests/test_launchers.py` with:

```python
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = PROJECT_ROOT / "usr" / "bin"
LAUNCHER_HELPER = PROJECT_ROOT / "usr" / "lib" / "gitrepo" / "launcher.bash"
LAUNCHERS = ("gitrepo", "bpkg", "build-iso", "biso")


def test_launcher_helper_owns_strict_mode_and_python_exec() -> None:
    source = LAUNCHER_HELPER.read_text(encoding="utf-8")

    assert "set -o errexit" in source
    assert "set -o nounset" in source
    assert "set -o pipefail" in source
    assert "exec /usr/bin/python3 -m \"$module\" \"$@\"" in source


@pytest.mark.parametrize("name", LAUNCHERS)
def test_launchers_use_bash_and_the_shared_helper(name: str) -> None:
    source = (BIN_DIR / name).read_text(encoding="utf-8")

    assert source.startswith("#!/usr/bin/bash\n")
    assert "../lib/gitrepo/launcher.bash" in source
    assert source.count("gitrepo_exec_python_module") == 1


@pytest.mark.parametrize("name", ("bpkg", "biso"))
@pytest.mark.parametrize("option", ("--help", "--version"))
def test_cli_launchers_run_from_an_unrelated_directory(tmp_path: Path, name: str, option: str) -> None:
    result = subprocess.run(
        [str(BIN_DIR / name), option],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()


def test_gitrepo_rejects_too_many_directories() -> None:
    result = subprocess.run(
        [str(BIN_DIR / "gitrepo"), "one", "two"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "GitRepo accepts at most one directory.\n"


def test_gitrepo_rejects_a_missing_directory(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    result = subprocess.run(
        [str(BIN_DIR / "gitrepo"), str(missing)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == f"Not a directory: {missing}\n"
```

- [ ] **Step 2: Run the tests and confirm that the Bash contract fails**

Run:

```bash
pytest -q tests/test_launchers.py
```

Expected: five failures report that the helper does not exist and the current `#!/bin/sh` shebang does not equal `#!/usr/bin/bash`.

- [ ] **Step 3: Create the shared Bash launcher helper**

Create `usr/lib/gitrepo/launcher.bash` with:

```bash
# shellcheck shell=bash

set -o errexit
set -o nounset
set -o pipefail

helper_dir="$(cd -- "$(/usr/bin/dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
share_dir="$(cd -- "${helper_dir}/../../share" && pwd -P)"
readonly helper_dir share_dir

export PYTHONPATH="${share_dir}${PYTHONPATH:+:${PYTHONPATH}}"

gitrepo_exec_python_module() {
    local -r module=$1
    shift
    exec /usr/bin/python3 -m "$module" "$@"
}
```

- [ ] **Step 4: Replace the Build Package GUI launcher**

Replace `usr/bin/gitrepo` with:

```bash
#!/usr/bin/bash

source "$(cd -- "$(/usr/bin/dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/../lib/gitrepo/launcher.bash"

if (( $# > 1 )); then
    printf '%s\n' "GitRepo accepts at most one directory." >&2
    exit 2
fi

if (( $# == 1 )); then
    if [[ ! -d $1 ]]; then
        printf 'Not a directory: %s\n' "$1" >&2
        exit 2
    fi
    if ! git_root="$(/usr/bin/git -C "$1" rev-parse --show-toplevel 2>/dev/null)"; then
        message="The selected folder is not inside a Git repository: $1"
        printf '%s\n' "$message" >&2
        if [[ -x /usr/bin/notify-send ]]; then
            /usr/bin/notify-send --app-name=GitRepo --icon=dialog-warning "Not a Git Repository" "$message"
        fi
        exit 1
    fi
    readonly git_root
    cd -- "$git_root"
fi

gitrepo_exec_python_module gitrepo.build_package.gui.main_gui
```

- [ ] **Step 5: Replace the other three launchers**

Replace `usr/bin/bpkg` with:

```bash
#!/usr/bin/bash

source "$(cd -- "$(/usr/bin/dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/../lib/gitrepo/launcher.bash"

gitrepo_exec_python_module gitrepo.build_package.cli.main_cli "$@"
```

Replace `usr/bin/build-iso` with:

```bash
#!/usr/bin/bash

source "$(cd -- "$(/usr/bin/dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/../lib/gitrepo/launcher.bash"

gitrepo_exec_python_module gitrepo.build_iso.gui.main_gui "$@"
```

Replace `usr/bin/biso` with:

```bash
#!/usr/bin/bash

source "$(cd -- "$(/usr/bin/dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/../lib/gitrepo/launcher.bash"

gitrepo_exec_python_module gitrepo.build_iso.cli "$@"
```

- [ ] **Step 6: Format and validate the launcher slice**

Run:

```bash
shfmt -w -ln bash -ci usr/lib/gitrepo/launcher.bash usr/bin/gitrepo usr/bin/bpkg usr/bin/build-iso usr/bin/biso
bash -n usr/lib/gitrepo/launcher.bash usr/bin/gitrepo usr/bin/bpkg usr/bin/build-iso usr/bin/biso
shellcheck -s bash usr/lib/gitrepo/launcher.bash usr/bin/gitrepo usr/bin/bpkg usr/bin/build-iso usr/bin/biso
pytest -q tests/test_launchers.py
```

Expected: Bash and ShellCheck emit no output; pytest reports `11 passed`.

- [ ] **Step 7: Commit the launcher contract**

```bash
git add tests/test_launchers.py usr/lib/gitrepo/launcher.bash usr/bin/gitrepo usr/bin/bpkg usr/bin/build-iso usr/bin/biso
git commit -m "refactor: make public launchers exemplary bash"
```

---

### Task 2: Replace destructive Git inference with explicit intent

**Architecture amendment:** Three review cycles demonstrated that reproducing Git's evolving option grammar locally creates both bypasses and false positives. Per user approval, delete the heuristic parser and make intent mandatory at every Git subprocess boundary.

**Files:**
- Modify: `usr/share/gitrepo/common/child_process.py`
- Modify: production modules under `usr/share/gitrepo/build_package/` and `usr/share/gitrepo/build_iso/` that invoke Git through the shared process boundary.
- Modify: `tests/test_render_environment.py`
- Modify: focused tests affected by the explicit Git API.

**Interfaces:**
- Preserve: `run()`, `Popen()`, and `authorize_destructive_git()` for non-Git subprocesses.
- Add: `run_git(*popenargs, intent: Literal["ordinary", "destructive"], **kwargs)`.
- Produce: a fail-closed boundary where generic `run()`/`Popen()` reject Git argv, every Git caller declares intent, and `intent="destructive"` requires an active authorization scope.

- [ ] **Step 1: Add failing explicit-intent boundary tests**

Cover these contracts before production edits:

- generic `run(["git", ...])` and `Popen(["/usr/bin/git", ...])` raise `GitIntentRequiredError`;
- `run_git(..., intent="ordinary")` executes and preserves argv/environment behavior;
- `run_git(..., intent="destructive")` raises `DestructiveGitCommandError` without authorization and executes inside `authorize_destructive_git()`;
- invalid intent and non-Git argv passed to `run_git()` fail clearly;
- an AST contract test proves literal Git subprocess call sites use `run_git()` and provide an explicit `intent=` keyword.

- [ ] **Step 2: Verify RED**

Run the new boundary tests and confirm failure because `run_git`, `GitIntentRequiredError`, and explicit call-site intent do not exist.

- [ ] **Step 3: Implement the fail-closed process boundary**

In `child_process.py`:

- delete `_git_command_parts`, `_git_operands`, `_git_push_refspecs`, and `is_destructive_git_command`;
- identify Git only by argv executable basename (`git` or an absolute Git path), without parsing subcommand grammar;
- make generic `run()` and `Popen()` reject Git argv with `GitIntentRequiredError`;
- implement typed `run_git(..., intent=...)`, validate that argv invokes Git, preserve sanitized environment publication, and require authorization only for `destructive` intent;
- never pass the internal `intent` keyword to Python's `subprocess` module.

- [ ] **Step 4: Migrate every production Git call site**

Use `subprocess.run_git(command, intent="ordinary", ...)` for operations that do not discard local user data or rewrite remote history. Use `intent="destructive"` only for confirmed discard/history-rewrite flows and keep them inside `authorize_destructive_git()`.

Do not mark a command ordinary merely to satisfy the guard. Dynamic operation plans must derive the explicit intent from their existing destructive contract. Leave non-Git subprocess calls on `run()`/`Popen()`.

- [ ] **Step 5: Run boundary, product, static, and complete checks**

```bash
pytest -q tests/test_render_environment.py tests/build_package/test_destructive_git_safety.py tests/build_iso/test_iso_builder_security.py
ruff format --check usr/share/gitrepo tests
ruff check usr/share/gitrepo tests
mypy usr/share/gitrepo/common/child_process.py
pytest -q
```

Expected: all tests and static checks pass, with no warning in touched code.

- [ ] **Step 6: Commit the explicit Git boundary**

```bash
git add usr/share/gitrepo/common/child_process.py usr/share/gitrepo/build_package usr/share/gitrepo/build_iso tests
git commit -m "refactor: require explicit git operation intent"
```

---

### Task 3: Make URL validation semantically strict

**Files:**
- Modify: `usr/share/gitrepo/common/network_url.py`
- Modify: `tests/test_render_environment.py`

**Interfaces:**
- Consumes: `validate_https_url(url: str, allowed_hosts: Collection[str]) -> str`.
- Produces: the same function with `UnsafeNetworkUrl` for malformed ports and control characters, plus `validate_github_repository_url(url: str) -> str` that rejects both query strings and fragments before normalization.

- [ ] **Step 1: Add malformed and fragment URL regressions**

Extend the unsafe values in `test_network_urls_require_allowlisted_https_without_credentials` with:

```python
        "https://api.github.com:invalid/repos/a/b",
        "https://api.github.com/repos/a/b\nignored",
```

Extend the unsafe values in `test_github_repository_url_is_exact_and_canonical` with:

```python
        "https://github.com/biglinux/iso-profiles#unexpected-fragment",
```

- [ ] **Step 2: Verify the current validator accepts or misclassifies the new cases**

Run:

```bash
pytest -q tests/test_render_environment.py::test_network_urls_require_allowlisted_https_without_credentials tests/test_render_environment.py::test_github_repository_url_is_exact_and_canonical
```

Expected: failures show a raw `ValueError` for the invalid port and acceptance of the fragment after it has been stripped.

- [ ] **Step 3: Validate syntax before normalization**

Replace `validate_https_url` with:

```python
def validate_https_url(url: str, allowed_hosts: Collection[str]) -> str:
    """Return a normalized HTTPS URL restricted to an explicit host allowlist."""
    if any(ord(character) < 32 or ord(character) == 127 for character in url):
        raise UnsafeNetworkUrl("control characters are not supported")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise UnsafeNetworkUrl("the URL is malformed") from error

    hostname = parsed.hostname.lower() if parsed.hostname else ""
    normalized_hosts = {host.lower() for host in allowed_hosts}
    if parsed.scheme != "https" or hostname not in normalized_hosts:
        raise UnsafeNetworkUrl("only allowlisted HTTPS hosts are supported")
    if parsed.username or parsed.password or port not in (None, 443):
        raise UnsafeNetworkUrl("credentials and custom ports are not supported")
    netloc = hostname if port is None else f"{hostname}:{port}"
    return urlunsplit(("https", netloc, parsed.path, parsed.query, ""))
```

At the start of `validate_github_repository_url`, reject GitHub query and fragment components before calling the generic normalizer:

```python
    try:
        requested = urlsplit(url)
    except ValueError as error:
        raise UnsafeNetworkUrl("the URL is malformed") from error
    if requested.query or requested.fragment:
        raise UnsafeNetworkUrl("query strings and fragments are not supported")
```

Remove the now-unreachable `parsed.query or parsed.fragment` check after `safe_url` is created.

- [ ] **Step 4: Validate the URL boundary**

Run:

```bash
pytest -q tests/test_render_environment.py
ruff format --check usr/share/gitrepo/common/network_url.py tests/test_render_environment.py
ruff check usr/share/gitrepo/common/network_url.py tests/test_render_environment.py
mypy usr/share/gitrepo/common/network_url.py
```

Expected: all checks pass without diagnostics.

- [ ] **Step 5: Commit strict URL semantics**

```bash
git add usr/share/gitrepo/common/network_url.py tests/test_render_environment.py
git commit -m "fix: reject ambiguous network urls"
```

---

### Task 4: Redact secrets at the shared logger boundary

**Files:**
- Create: `tests/test_rich_logger.py`
- Modify: `usr/share/gitrepo/common/rich_logger.py`

**Interfaces:**
- Consumes: `redact_diagnostic(message: object) -> str`.
- Produces: `RichLogger.log(style: str, message: str) -> None` that publishes the same redacted text to the console and optional file while preserving Rich markup for messages that did not require redaction.

- [ ] **Step 1: Write the failing terminal-and-file redaction test**

Create `tests/test_rich_logger.py` with:

```python
from __future__ import annotations

from pathlib import Path

from gitrepo.common.rich_logger import RichLogger


def test_logger_redacts_secrets_from_terminal_and_file(tmp_path: Path, capsys) -> None:
    logger = RichLogger("gitrepo", "test", str(tmp_path), use_colors=False)
    logger.setup_log_file(lambda: "repository")

    logger.log("white", "Authorization: Bearer ghp_0123456789abcdef token=plain-secret")

    terminal = capsys.readouterr().out
    persisted = (tmp_path / "repository" / "gitrepo.log").read_text(encoding="utf-8")
    for output in (terminal, persisted):
        assert "0123456789abcdef" not in output
        assert "plain-secret" not in output
        assert "REDACTED" in output
```

- [ ] **Step 2: Confirm that the shared logger currently leaks the fixture secrets**

Run:

```bash
pytest -q tests/test_rich_logger.py
```

Expected: the test fails because both captured terminal output and the repository log contain the fixture tokens.

- [ ] **Step 3: Redact before either publication surface**

Import `redact_diagnostic` in `rich_logger.py`:

```python
from .diagnostic_redaction import redact_diagnostic
```

Replace the publication body at the start of `RichLogger.log` with:

```python
        safe_message = redact_diagnostic(message)
        self.console.print(
            safe_message,
            style=color_map.get(style, "white"),
            markup=safe_message == message,
        )
```

Write `safe_message`, not `message`, to the file:

```python
                stream.write(f"[{timestamp}] {safe_message}\n")
```

The conditional `markup` flag prevents the `[REDACTED]` marker from being interpreted as Rich markup while preserving existing intentional markup in ordinary messages.

- [ ] **Step 4: Run logger, redaction, and CLI-focused checks**

Run:

```bash
pytest -q tests/test_rich_logger.py tests/test_diagnostic_redaction.py
ruff format --check usr/share/gitrepo/common/rich_logger.py tests/test_rich_logger.py
ruff check usr/share/gitrepo/common/rich_logger.py tests/test_rich_logger.py
mypy usr/share/gitrepo/common/rich_logger.py
usr/bin/bpkg --version
usr/bin/biso --version
```

Expected: tests and static checks pass; both version commands return status 0 and print their application panels.

- [ ] **Step 5: Commit logger redaction**

```bash
git add usr/share/gitrepo/common/rich_logger.py tests/test_rich_logger.py
git commit -m "fix: redact secrets at shared logger boundary"
```

---

### Task 5: Make static analysis truthful and confirm the dead-code result

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: system-installed PyGObject and Rich modules, strict Mypy coverage, Pyright's configured include list, runtime import smoke, and Vulture's 100-percent-confidence scan.
- Produces: a reproducible static-analysis policy that suppresses only Pyright's unavailable external-source lookup while retaining internal import, typing, lint, and runtime checks.

- [ ] **Step 1: Reproduce the Pyright external-import baseline**

Run:

```bash
mypy usr/share/gitrepo/common
pyright
```

Expected on the verified host: both commands succeed. Pyright's existing narrow `reportMissingModuleSource` policy already suppresses only unavailable runtime source for resolved PyGObject modules.

- [ ] **Step 2: Correct the Pyright policy without adding stubs or machine-specific paths**

In `[tool.pyright]`, retain the narrow policy and document it:

```toml
# PyGObject exposes runtime modules without importable Python source; availability is verified by the import smoke.
reportMissingModuleSource = false
```

Do not disable `reportMissingImports`: it must retain its default error severity so misspelled or absent internal imports remain visible. Do not add a machine-specific site-packages path, generated stubs, or a new dependency.

- [ ] **Step 3: Verify complementary type and runtime gates**

Run:

```bash
mypy usr/share/gitrepo/common
pyright
PYTHONPATH="$PWD/usr/share" python3 -c 'import gi, rich; import gitrepo.common.page_hero; import gitrepo.common.rich_logger; import gitrepo.common.token_store'
```

Expected: Mypy and Pyright report zero errors and zero warnings; the import smoke exits 0 without output. A temporary missing-import probe must make Pyright exit nonzero, proving the narrow policy remains fail-closed; remove the probe immediately afterward.

- [ ] **Step 4: Verify the unchanged persistence, credential, translation, and GTK contracts**

Run:

```bash
pytest -q \
    tests/test_atomic_file.py \
    tests/test_translation_catalog.py \
    tests/test_icon_resources.py \
    tests/test_render_environment.py \
    tests/build_package/test_build_package_persistence.py \
    tests/build_iso/test_persistence.py \
    tests/build_iso/test_accessible_typography.py
rg -n "threading\.Thread|GLib\.idle_add|TokenStore\.(read_all|upsert|get_token|delete)" \
    usr/share/gitrepo/build_package/gui
```

Expected: all focused contracts pass. The consumer search shows that Build Package GTK keyring reads, writes, verification, and deletion execute in worker threads and publish completed UI state with `GLib.idle_add`; Build ISO's shared token read remains in its CLI/API path rather than a GTK callback.

- [ ] **Step 5: Confirm that no dead code is currently proven in the shared slice**

Run:

```bash
vulture usr/share/gitrepo/common usr/share/gitrepo/build_package usr/share/gitrepo/build_iso tests --min-confidence 100
rg -n "gitrepo\.common\.(atomic_file|child_process|diagnostic_redaction|network_url|page_hero|premium_style|render_environment|rich_logger|token_store|translation|version_display)" usr/share/gitrepo tests
```

Expected: Vulture emits no findings. The `rg` output shows product or test consumers for every shared module except `__init__.py`, whose package docstring is intentional. Remove nothing in this task because the agreed evidence threshold is not met.

- [ ] **Step 6: Commit the analyzer policy**

```bash
git add pyproject.toml
git commit -m "chore: align type checks with system python modules"
```

---

### Task 6: Align user and maintainer documentation with tested behavior

**Files:**
- Modify: `README.md`
- Modify: `MAINTENANCE.md`

**Interfaces:**
- Consumes: the four tested public commands, Bash launcher boundary, XDG data contracts, official upstream references, and validation commands from Tasks 1–5.
- Produces: reproducible user and maintenance guidance that makes no untested readiness or compatibility claims.

- [ ] **Step 1: Correct the README launcher description**

In the project-structure block, replace `four small POSIX launchers` with:

```text
usr/bin/                         four small Bash launchers
usr/lib/gitrepo/                 shared Bash launcher helper
```

After the source-tree launcher examples, add:

```markdown
The launchers require Bash and delegate to canonical Python modules with `python3 -m`. They preserve the Python process's exit status and signals. `gitrepo` validates an optional directory before GTK starts; the other launchers forward their arguments unchanged.
```

Keep the existing command table and XDG path table unchanged because they match the verified contracts.

- [ ] **Step 2: Update maintainer design and validation rules**

In `MAINTENANCE.md`, replace the design rule about launchers with:

```markdown
- Keep GTK, API access, credential handling, and durable settings in Python. Keep launchers and packaging glue in Bash. The shared launcher helper resolves the adjacent `usr/share` tree and uses `exec /usr/bin/python3 -m ...` so signals and exit status remain truthful.
```

Replace the launcher validation commands with:

```bash
bash -n usr/lib/gitrepo/launcher.bash usr/bin/bpkg usr/bin/biso usr/bin/build-iso usr/bin/gitrepo
shellcheck -s bash usr/lib/gitrepo/launcher.bash usr/bin/bpkg usr/bin/biso usr/bin/build-iso usr/bin/gitrepo
shfmt -d -ln bash -ci usr/lib/gitrepo/launcher.bash usr/bin/bpkg usr/bin/biso usr/bin/build-iso usr/bin/gitrepo
pytest -q tests/test_launchers.py
```

- [ ] **Step 3: Add the official-contract reference section**

Add this section before `## Packaging and release`:

```markdown
## Upstream contracts

Review behavior against primary, version-compatible sources:

- Python [`subprocess`](https://docs.python.org/3/library/subprocess.html), [`tempfile`](https://docs.python.org/3/library/tempfile.html), [`os.replace`](https://docs.python.org/3/library/os.html#os.replace), [`gettext`](https://docs.python.org/3/library/gettext.html), and [`urllib.parse`](https://docs.python.org/3/library/urllib.parse.html);
- the [GNU Bash Reference Manual](https://www.gnu.org/software/bash/manual/);
- the [Git command synopsis](https://git-scm.com/docs/git), including global options before the subcommand;
- [GTK accessibility](https://docs.gtk.org/gtk4/section-accessibility.html), [`GtkApplication`](https://docs.gtk.org/gtk4/class.Application.html), and the [PyGObject threading guide](https://pygobject.gnome.org/guide/threading.html);
- the [libsecret simple API](https://gnome.pages.gitlab.gnome.org/libsecret/libsecret-simple-api.html) and synchronous-call warnings;
- the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/);
- the [Arch package creation guidelines](https://wiki.archlinux.org/title/Creating_packages).

Synchronous libsecret operations may block indefinitely. CLI calls may remain synchronous, but GTK callers must execute them in worker threads and publish completed UI state through `GLib.idle_add`.

For dead-code review, use Ruff, Mypy, Pyright, Vulture at 100 percent confidence, repository-wide symbol searches, integration-file searches, tests, and practical entrypoint execution together. A tool finding alone is not deletion authority.
```

- [ ] **Step 4: Check documentation against the source**

Run:

```bash
rg -n "POSIX launcher|#!/bin/sh|sh -n" README.md MAINTENANCE.md
rg -n "gitrepo \[DIRECTORY\]|bpkg \[OPTIONS\]|build-iso|biso \[OPTIONS\]" README.md MAINTENANCE.md
node "${BIGAGENTS_TOOLS:-$HOME/.agents}/scripts/agent-fmt.mjs" --file README.md --file MAINTENANCE.md --check
```

Expected: the stale-term search emits no matches; public-command and formatter checks succeed.

- [ ] **Step 5: Commit the documentation update**

```bash
git add README.md MAINTENANCE.md
git commit -m "docs: document shared runtime contracts"
```

---

### Task 7: Run the automated and packaging gates

**Files:**
- Verify only; modify no files unless a check identifies an in-scope regression.

**Interfaces:**
- Consumes: all deliverables from Tasks 1–6.
- Produces: recorded evidence for Python, Bash, translations, desktop metadata, AppStream metadata, and Arch packaging.

- [ ] **Step 1: Run focused formatting and lint checks with an explicit file list**

```bash
node "${BIGAGENTS_TOOLS:-$HOME/.agents}/scripts/agent-fmt.mjs" \
    --file usr/share/gitrepo/common/child_process.py \
    --file usr/share/gitrepo/common/network_url.py \
    --file usr/share/gitrepo/common/rich_logger.py \
    --file tests/test_launchers.py --file tests/test_render_environment.py \
    --file tests/test_rich_logger.py --check
ruff format --check usr/share tests
ruff check usr/share tests
```

Expected: every command exits 0 with no warnings.

`agent-fmt` is intentionally limited to its accepted Python paths. Bash uses default Shfmt indentation through the explicit command in Step 3; `agent-fmt` supports neither extensionless shebang scripts, TOML, nor Markdown formatting. Mypy, Pyright, and pytest parse `pyproject.toml`; documentation is checked textually and by `git diff --check`.

- [ ] **Step 2: Run the complete Python gate**

```bash
pytest -q
mypy .
pyright
```

Expected: all tests pass; both type checkers report zero errors.

- [ ] **Step 3: Run Bash and metadata validators**

```bash
bash -n usr/lib/gitrepo/launcher.bash usr/bin/bpkg usr/bin/biso usr/bin/build-iso usr/bin/gitrepo pkgbuild/PKGBUILD
shellcheck -s bash usr/lib/gitrepo/launcher.bash usr/bin/bpkg usr/bin/biso usr/bin/build-iso usr/bin/gitrepo
shfmt -d -ln bash -ci usr/lib/gitrepo/launcher.bash usr/bin/bpkg usr/bin/biso usr/bin/build-iso usr/bin/gitrepo
for catalog in locale/*.po; do msgfmt --check --output-file=/dev/null "$catalog"; done
desktop-file-validate usr/share/applications/*.desktop usr/share/thunar/sendto/*.desktop
appstreamcli validate --no-net usr/share/metainfo/*.metainfo.xml
(cd pkgbuild && makepkg --printsrcinfo)
```

Expected: all commands exit 0; validators emit no errors in touched contracts.

- [ ] **Step 4: Exercise non-graphical public command semantics**

```bash
usr/bin/bpkg --help
usr/bin/bpkg --version
usr/bin/biso --help
usr/bin/biso --version
```

Expected: each command exits 0 and prints the matching product help or version panel.

---

### Task 8: Validate both GUI launchers and accessibility in practice

**Files:**
- Verify the runtime behavior of `usr/bin/gitrepo`, `usr/bin/build-iso`, and shared GTK components.
- Save screenshots and logs only in the private temporary artifact root created by the `linux-ui-a11y` workflow.

**Interfaces:**
- Consumes: `linux-ui-a11y`, the two Bash GUI launchers, GTK4 accessibility semantics, and the current application windows.
- Produces: screenshot, AT-SPI, keyboard, startup, and process-output evidence for both applications.

- [ ] **Step 1: Invoke the required UI skill and allocate its isolated session**

Before launching either GUI, invoke `linux-ui-a11y`, read its complete `SKILL.md`, and use its canonical KDE/KWin + Spectacle + AT-SPI path. Do not open either application on the user's visible desktop.

- [ ] **Step 2: Exercise `gitrepo` with a disposable repository**

Create an exact disposable repository through the skill's private execution root, run `git init` inside it, and launch:

```bash
/mnt/OldRoot/@home/bruno/codigo-pacotes/gitrepo/usr/bin/gitrepo /exact/disposable/repository
```

Verify all of the following:

- the process remains running without a Python traceback;
- the Build Package primary window is present and named;
- sidebar destinations, refresh, preferences, access tokens, and primary actions have meaningful AT-SPI roles and names;
- Tab and Shift+Tab reach required controls in a coherent order;
- Ctrl+R and Ctrl+Q activate the documented actions;
- a screenshot shows readable text, visible focus, and no clipped startup state.

- [ ] **Step 3: Exercise `build-iso` in the same isolated environment**

Launch:

```bash
/mnt/OldRoot/@home/bruno/codigo-pacotes/gitrepo/usr/bin/build-iso
```

Verify all of the following:

- the process remains running without a Python traceback;
- the Build ISO primary window is present and named;
- dashboard status, profiles, build, history, environment, and settings expose truthful roles, names, and state;
- Tab and Shift+Tab reach required controls in a coherent order;
- Ctrl+R and Ctrl+Q activate the documented actions;
- a screenshot shows readable text, visible focus, and no clipped startup state.

- [ ] **Step 4: Preserve evidence and clean the disposable session**

Copy the final screenshots, AT-SPI dumps, and process logs to the skill-provided private artifact root. Clean the exact disposable execution root with the repository-approved executable-temp-dir helper. Do not delete user-owned data.

Expected: both GUI checks pass. If a semantic or startup defect appears, invoke `superpowers:systematic-debugging`, add the smallest focused regression test, fix only the demonstrated in-scope defect, and repeat Tasks 7 and 8.

---

### Task 9: Final diff review and completion evidence

**Files:**
- Review all accepted files from Tasks 1–8.

**Interfaces:**
- Consumes: automated, packaging, screenshot, AT-SPI, keyboard, and runtime evidence.
- Produces: a handoff that distinguishes completed behavior, baseline limitations, and residual risk.

- [ ] **Step 1: Invoke verification-before-completion**

Invoke `superpowers:verification-before-completion` and follow its evidence requirements before making any success claim.

- [ ] **Step 2: Run the final proportional project gate**

```bash
node "${BIGAGENTS_TOOLS:-$HOME/.agents}/scripts/agent-check.mjs" "$PWD" --mode final
```

Expected: the final gate exits 0. Preserve its full log in the private temporary artifact root if the helper produces one.

- [ ] **Step 3: Review scope and whitespace**

```bash
git status --short
git diff --check
git diff --stat 707086b..HEAD
git log -6 --oneline --decorate
```

Confirm that no unrelated user work was overwritten, no secret appears in source/tests/logs/screenshots, no generated cache or build output is staged, and every dead-code claim matches the recorded evidence.

- [ ] **Step 4: Report the result**

Report:

- exact code and documentation outcomes;
- each command executed and whether it passed;
- the practical GUI and AT-SPI observations;
- official sources that affected implementation decisions;
- the explicit result that no dead code was removed in this slice because the 100-percent-confidence scan and consumer search found none;
- environmental limitations or residual risks, including any check that could not run.
