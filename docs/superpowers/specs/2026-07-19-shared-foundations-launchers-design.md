# Shared Foundations and Launchers Design

## Goal

Review and improve GitRepo's shared Python foundations and four public launchers against the primary documentation of the projects they depend on. The result must be exemplary production code, remove only confirmed dead code, preserve public behavior, and be verified through static checks and practical execution.

This is the first owner slice of a broader product review. Build Package and Build ISO product internals remain separate follow-up slices except where a directly connected change is required to keep a shared contract or launcher correct.

## Public contracts

The following commands and their observable roles remain stable:

- `gitrepo [DIRECTORY]` opens the Build Package GTK application in the selected Git repository.
- `bpkg [OPTIONS]` exposes package, commit, branch, and AUR terminal workflows.
- `build-iso` opens the Build ISO GTK application.
- `biso [OPTIONS]` exposes local and remote ISO automation.

Their documented options, positional arguments, standard streams, exit statuses, Python destinations, and externally visible effects must be preserved. A contract may change only to correct a demonstrated defect, security issue, or conflict with an authoritative upstream specification.

## Architecture

`usr/share/gitrepo/common/` remains the shared Python foundation. It contains only contracts that are genuinely consumed by both products: subprocess execution, atomic persistence, credential storage, network boundary validation, diagnostic redaction, GTK render-environment handling, translations, logging, version display, and shared GTK presentation primitives.

`usr/bin/gitrepo`, `usr/bin/bpkg`, `usr/bin/build-iso`, and `usr/bin/biso` become Bash launchers. Each launcher has one primary responsibility: resolve the installed `usr/share` directory, prepare `PYTHONPATH`, and replace itself with the appropriate Python entrypoint using `exec`. Validation stays in a launcher only when it must happen before GTK or the product module is loaded. Product behavior stays in Python.

No new framework, service, or speculative shared abstraction will be introduced. A shared unit must have real consumers in both products and remove more complexity than it adds.

## Component contracts

### Atomic persistence

`atomic_file.py` owns same-directory temporary publication, restrictive permissions, file and directory synchronization, atomic replacement, symlink rejection, and preservation of the previous file on failure. Corrupt durable data remains available for recovery and must never be silently replaced by defaults.

### Child processes

`child_process.py` owns the common subprocess boundary. Commands use explicit argument sequences without shell interpretation. The boundary removes only GitRepo-owned environment injection, preserves caller intent otherwise, propagates subprocess results, and rejects destructive Git commands outside an explicit confirmed authorization scope.

### Trust boundaries

`token_store.py`, `network_url.py`, and `diagnostic_redaction.py` own credential persistence, allowlisted network destinations, and secret removal from diagnostics. Legacy cleartext credentials may be deleted only after a verified secret-service write. Errors must not expose credential values.

### GTK environment and shared presentation

`render_environment.py` owns any GitRepo-specific renderer selection and ensures that private renderer injection does not leak into child processes. `page_hero.py` and `premium_style.py` remain shared only while both applications use the same semantic and visual contract. Standard GTK controls retain their native accessible roles; decorative elements use presentation semantics; application-specific names, descriptions, relations, focus order, and keyboard paths must be explicit where GTK defaults are insufficient.

### Translation, versions, and logging

`translation.py`, `version_display.py`, and `rich_logger.py` own their narrow cross-product contracts. Configuration and persistent state follow the XDG Base Directory Specification. Terminal output and file logs preserve their distinct purposes, and diagnostic text is redacted before reaching either user-facing or persistent output.

## Runtime flow

```text
Bash launcher -> minimal validation -> PYTHONPATH -> exec python3
                                                    |
                                                    v
                                         product entrypoint
                                                    |
                                                    v
                                         gitrepo.common contracts
```

Launchers must forward arguments exactly, preserve signals and the Python process's exit status, and write usage failures to standard error with status 2. Operational failures return a nonzero status with an actionable explanation. Python exceptions for corruption, publication, trust-boundary violations, and destructive-operation authorization remain distinguishable and preserve their original cause.

## Semantic review

Semantics are reviewed at three levels:

1. Code names and module ownership must match the domain and expose one clear responsibility.
2. CLI options, messages, streams, exit statuses, argument forwarding, and effects must agree with the documented command contract.
3. GTK roles, accessible names and descriptions, relations, focus behavior, keyboard navigation, and action results must communicate the actual purpose and state of controls.

Readiness, success, health, and failure states must be derived from real observable state. Documentation and UI copy must not claim behavior that the implementation does not perform.

## Confirming dead code

Code is removed only when the relevant combination of evidence demonstrates that it has no live or compatibility contract:

- import, symbol, and call-site analysis;
- searches across Python, launchers, tests, desktop entries, packaging, and file-manager integrations;
- Ruff and type-checker results;
- import and entrypoint tests;
- practical execution of all four commands;
- review of user and maintenance documentation plus compatibility paths.

No new production dependency is added solely to find dead code. Confirmed dead code may be removed outside the primary directories when discovered, but unrelated refactoring remains out of scope.

## Validation strategy

Validation proceeds from narrow deterministic checks to practical flows:

1. Capture the current launcher behavior and add or adapt focused contract tests where a distinct behavior or regression needs ownership.
2. Run focused tests for shared modules after each coherent correction.
3. Run Ruff formatting and lint checks, Mypy, and Pyright at the repository's configured scope.
4. Parse and lint the four Bash launchers with Bash, ShellCheck, and Shfmt using an explicit accepted-file list.
5. Exercise `bpkg --help`, `bpkg --version`, `biso --help`, and `biso --version`, including invalid inputs, argument forwarding, standard streams, and exit statuses.
6. Start `gitrepo` and `build-iso` from the checkout in an isolated KDE/KWin session using the `linux-ui-a11y` skill. Inspect screenshots, the AT-SPI tree, keyboard reachability, process output, and the observable startup effect.
7. Validate the `PKGBUILD` without installing or changing the host system.
8. Run the proportional final repository gate and review the complete accepted diff.

A failing check is classified as a regression, a pre-existing defect, missing tooling, or an environmental limitation. Useful checks are not bypassed, deleted, or weakened to obtain a green result.

## Documentation deliverables

README and maintenance documentation will describe the maintained architecture, four public commands, Bash/Python boundary, supported direct-checkout workflow, validation commands, XDG paths, security contracts, troubleshooting, and known environmental requirements. Commands must be reproducible and claims must match tested behavior.

Implementation decisions will be checked against version-compatible primary sources, including:

- [Python subprocess documentation](https://docs.python.org/3/library/subprocess.html)
- [Python tempfile documentation](https://docs.python.org/3/library/tempfile.html)
- [Python os documentation](https://docs.python.org/3/library/os.html)
- [GNU Bash Reference Manual](https://www.gnu.org/software/bash/manual/)
- [GTK accessibility documentation](https://docs.gtk.org/gtk4/section-accessibility.html)
- [GtkApplication documentation](https://docs.gtk.org/gtk4/class.Application.html)
- [PyGObject threading guide](https://pygobject.gnome.org/guide/threading.html)
- [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/)
- official libsecret and Arch Linux packaging documentation relevant to the installed and declared versions

Secondary tooling guidance may supply additional checks but does not override upstream contracts.

## Acceptance criteria

- All four public commands and their documented behavior remain available.
- Touched Python and Bash code passes its focused checks without warnings.
- Every dead-code deletion has concrete evidence and removes no documented or external integration contract.
- Both GTK applications start through their public launchers and expose coherent AT-SPI semantics and keyboard paths in the isolated graphical session.
- `PKGBUILD` validation succeeds without host installation.
- README and maintenance documentation accurately reproduce architecture, operation, validation, troubleshooting, and residual limitations.
- The final report lists changes, exact checks and outcomes, primary references, assumptions, and residual risks.
