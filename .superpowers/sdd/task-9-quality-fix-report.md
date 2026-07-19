# Task 9 quality-gate fix report

Date: 2026-07-19 (America/Sao_Paulo)
Base: `d999e7fd30721d14e09a8e5e31acef372e7e7679`

## Accepted-file allowlist

- `tests/test_render_environment.py`
- `usr/lib/gitrepo/launcher.bash`
- `usr/bin/biso`
- `usr/bin/bpkg`
- `usr/bin/build-iso`
- `usr/bin/gitrepo`
- `MAINTENANCE.md`
- `docs/superpowers/plans/2026-07-19-shared-foundations-launchers.md`
- `.superpowers/sdd/task-9-quality-fix-report.md`

The five Bash paths were all passed explicitly to default Shfmt. Only
`launcher.bash` and `gitrepo` needed textual indentation changes; the other
three were already canonical.

## Changes

- Split the Git-boundary AST audit into named symbol-collection, call-resolution,
  assignment-resolution, argument, and literal-intent helpers. The production
  audit and its rejection of generic Git calls are unchanged.
- Retained alias, keyword-argument, bytes, variable-resolution, generic Git,
  and production-source coverage, and added explicit safe/unsafe literal-intent
  examples.
- Formatted exactly the five accepted Bash launcher paths with
  `shfmt -w -ln bash -ci`.
- Updated maintenance documentation and the implementation plan to prescribe
  default Shfmt indentation rather than four spaces.

## Verification

- Baseline RED: `ruff check --select C901 tests/test_render_environment.py`
  reported `_git_boundary_violations` at complexity 15 (limit 10).
- Focused Git-boundary pytest: `2 passed, 17 deselected`.
- Focused Ruff format/check and explicit C901 check: passed.
- Explicit one-file `agent-fmt` Python harness: passed.
- Five-file `bash -n`, ShellCheck, and default `shfmt -d -ln bash -ci`: passed.
- Launcher harness: `12 passed`.
- Linux-system harness: passed for all five Bash paths.
- Python-quality harness: Ruff C901 and format, Vulture, Mypy, the single full
  pytest run (`175 passed`), Pip-audit, and Bandit passed before the known KIO
  validator limitation described below.

## KIO validator limitation

`usr/share/kio/servicemenus/gitrepo.desktop` remains byte-for-byte unchanged
(`sha256: 252dc6cf40dfaf74c00ccc2c598756d11cf4858d68ea03b6e750e5399b64b7b1`).
The generic `desktop-file-validate` invocation applies the freedesktop
`Application` schema to this KDE `Type=Service` service menu and rejects its
required `MimeType` and `Actions` keys. The Python-quality harness therefore
exits 1 only at that validator step after its Python gates pass. Changing the
valid KIO contract to satisfy this false positive is intentionally out of
scope.
