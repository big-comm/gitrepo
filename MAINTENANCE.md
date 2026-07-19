# GitRepo maintenance

This document describes the maintained architecture and the shortest reliable validation path. It is product documentation; task plans and temporary progress ledgers do not belong in the repository.

## Design rules

- Preserve the four explicit user entrypoints: `gitrepo`, `bpkg`, `build-iso`, and `biso`.
- Keep GTK, API access, credential handling, and durable settings in Python. Keep launchers and packaging glue in Bash. The shared launcher helper resolves the adjacent `usr/share` tree and uses `exec /usr/bin/python3 -m ...` so signals and exit status remain truthful.
- Prefer direct argv subprocess calls. Never assemble a shell command from user input.
- Let Git, `makepkg`, Docker, and Podman own their formats and exit-status contracts.
- Share code only when both products have the same contract. Product-specific menus remain separate because their choices and confirmation defaults differ.
- Keep GTK work off the main loop and deliver completed snapshots with `GLib.idle_add`.
- Do not publish defaults over corrupt settings or history. Atomic writes and legacy migration are covered by tests.

## Architecture

### Shared code

`usr/share/gitrepo/common/` owns only contracts used by both applications:

- sanitized child-process execution and destructive-Git authorization;
- gettext setup;
- Rich version and logging output;
- adaptive GTK page headings;
- network URL and render-environment helpers.

The shared process boundary does not parse Git subcommands or options. Generic `run()` and `Popen()` calls fail closed when their argv invokes Git. Git callers must use `run_git()` with an explicit `ordinary` or `destructive` intent; destructive intent is accepted only inside an authorization scope tied to the user's confirmation.

Project-owned GTK icons live directly in `usr/share/gitrepo/icons/`. Keep that
private catalog flat and register it as an additional GTK search path. Only the
two desktop application icons mirror the system theme hierarchy under
`usr/share/icons/hicolor/scalable/apps/`.

### Build Package

`gitrepo.build_package.cli.main_cli` is the terminal entrypoint and `gitrepo.build_package.gui.main_gui` is the GTK entrypoint. Core Git operations expose one reviewed function per user action. `RepositorySnapshot` captures the repository state outside GTK's main loop and distributes one consistent result to the visible pages.

PKGBUILD names come from `makepkg --printsrcinfo`; do not add a second PKGBUILD parser. Destructive operations must use the existing confirmation and authorization boundary.

### Build ISO

`gitrepo.build_iso.cli` is the terminal entrypoint and `gitrepo.build_iso.gui.main_gui` is the GTK entrypoint. `Settings` owns the canonical atomic JSON store. `LocalConfig` is only the flat compatibility view used by the CLI/local builder.

`ContainerManager.capture_status()` runs one runtime/image probe. The main window sends that immutable snapshot to both Dashboard and Build Environment. Do not add independent Docker/Podman probes to either widget.

The `bigbruno` automatic profile intentionally preserves the existing compatibility combination: BigCommunity is the selected distribution name while the profile repository/build directory are BigLinux. Change those values only with an explicit product decision and a tested workflow update.

## Local commands

The launchers set `PYTHONPATH` themselves:

```bash
usr/bin/bpkg --help
usr/bin/bpkg --version
usr/bin/biso --help
usr/bin/biso --version
usr/bin/gitrepo /path/to/repository
usr/bin/build-iso
```

For direct module execution:

```bash
export PYTHONPATH="$PWD/usr/share${PYTHONPATH:+:$PYTHONPATH}"
python -m gitrepo.build_package.cli.main_cli --help
python -m gitrepo.build_iso.cli --help
```

For the simplest source-tree GUI startup, each interface directory has a small
`main.py` that resolves `usr/share` and delegates to the canonical package module:

```bash
(cd usr/share/gitrepo/build_package && python main.py)
(cd usr/share/gitrepo/build_iso && python main.py)
```

## Validation

Run focused checks while editing, then the complete set before a release:

```bash
ruff format --check usr/share tests
ruff check usr/share tests
pytest -q
mypy .
pyright

bash -n usr/lib/gitrepo/launcher.bash usr/bin/bpkg usr/bin/biso usr/bin/build-iso usr/bin/gitrepo
shellcheck -s bash usr/lib/gitrepo/launcher.bash usr/bin/bpkg usr/bin/biso usr/bin/build-iso usr/bin/gitrepo
shfmt -d -ln bash -i 4 -ci usr/lib/gitrepo/launcher.bash usr/bin/bpkg usr/bin/biso usr/bin/build-iso usr/bin/gitrepo
pytest -q tests/test_launchers.py

for catalog in locale/*.po; do msgfmt --check --output-file=/dev/null "$catalog"; done
desktop-file-validate usr/share/applications/*.desktop usr/share/thunar/sendto/*.desktop
appstreamcli validate --no-net usr/share/metainfo/*.metainfo.xml

bash -n pkgbuild/PKGBUILD
(cd pkgbuild && makepkg --printsrcinfo)
```

Use the repository's final agent gate at handoff:

```bash
node "${BIGAGENTS_TOOLS:-$HOME/.agents}/scripts/agent-check.mjs" "$PWD" --mode final
```

GTK changes additionally require a private KWin/Wayland run with screenshot review, AT-SPI inspection, and the changed action's observable side effect. Never validate by opening the application on the user's visible desktop.

Mypy and Pyright cover shared code and the typed Build ISO persistence/container boundary. Mypy remains strict there. Pyright narrowly disables `reportMissingModuleSource` because system PyGObject modules are available at runtime without importable Python source; `reportMissingImports` remains enabled so unresolved project imports still fail the check. Keep both sides of that contract reproducible:

```bash
PYTHONPATH="$PWD/usr/share" python3 -c 'import gi, rich; import gitrepo.common.page_hero; import gitrepo.common.rich_logger; import gitrepo.common.token_store'

probe=usr/share/gitrepo/common/_pyright_missing_import_probe.py
printf 'import gitrepo.common.module_that_does_not_exist\n' > "$probe"
if pyright "$probe"; then status=0; else status=$?; fi
unlink -- "$probe"
test "$status" -ne 0
```

The runtime smoke must exit zero without output, while the temporary probe must produce a `reportMissingImports` diagnostic and a nonzero exit. Dynamic legacy Build Package owners, GTK modules, and the ISO builder/catalog owners are explicitly outside the type gates until each can be typed as one coherent owner slice. Do not add scattered annotations merely to increase a type-count metric; Ruff, import smokes, and contract tests still cover the complete tree.

## Translations

English source strings live in Python. `locale/gitrepo.pot` is the template and `locale/*.po` are the editable catalogs. Runtime MOs live only under `usr/share/locale/<language>/LC_MESSAGES/gitrepo.mo`; do not recreate root-level `.mo` copies.

The four desktop integration files contain the same 29 languages shipped as
gettext catalogs. Keep `Name`, `GenericName`, and `Comment` complete where each
field applies; use `pt_BR` in desktop keys for the `pt-BR.po` catalog. The
desktop translation contract test rejects a missing or additional language.

Refresh and merge catalogs from the repository root:

```bash
find usr/share -name '*.py' -print0 | sort -z | \
  xargs -0 xgettext --language=Python --from-code=UTF-8 --keyword=_ \
  --package-name=GitRepo --package-version=3.7.8 \
  --copyright-holder='BigCommunity Team' --output=locale/gitrepo.pot

for catalog in locale/*.po; do
  msgmerge --update --backup=none --no-wrap "$catalog" locale/gitrepo.pot
  language=$(basename "$catalog" .po)
  installed_language=${language/-/_}
  mkdir -p "usr/share/locale/$installed_language/LC_MESSAGES"
  msgfmt --check --output-file="usr/share/locale/$installed_language/LC_MESSAGES/gitrepo.mo" "$catalog"
done
```

Preserve `%` placeholders, brace placeholders, and markup. A translated sentence must remain one complete message; do not translate whitespace fragments separately.

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

For dead-code review, use Ruff, Mypy, Pyright, Vulture at 100 percent confidence, repository-wide symbol searches, integration-file searches, tests, and practical entrypoint execution together. A tool finding alone is not deletion authority. The current combined review has no confirmed dead-code finding.

## Packaging and release

The component versions are independent:

- Build Package: `gitrepo.build_package.core.config.APP_VERSION`
- Build ISO: `gitrepo.build_iso.config.APP_VERSION`
- Arch package: calendar-style `pkgver` in `pkgbuild/PKGBUILD`

For a release:

1. Update the affected component version and AppStream release entry.
2. Refresh PO/POT/MO files and validate every catalog.
3. Run all static, test, launcher, desktop, AppStream, and GUI checks above.
4. Point `_commit` in `pkgbuild/PKGBUILD` to the reviewed release commit.
5. Build in a clean Arch environment and inspect the package with `namcap`.
6. Smoke the four installed commands from the built package.

Do not add install hooks for cache updates already owned by package-manager hooks. Do not add dynamic source-root detection: the VCS source is always extracted as `${srcdir}/gitrepo`.
