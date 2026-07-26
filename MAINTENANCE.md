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

`common/premium_style.py` owns the visual tokens (card radius, border, shadow,
hero gradient) plus `hero_css()` and `card_css()`, which render those tokens for
one product prefix. Both applications call them from `_setup_css()`; keep only
genuinely product-specific rules in each `main_gui`. `common/page_layout.py`
provides `page_body()`: every page appends the returned `Adw.Clamp` so body text
stops growing at a readable measure while the hero still spans the window.
`common/terminal_palette.py` owns the terminal-log foregrounds used by both
progress dialogs, and `common/help_popover.py` owns the contextual `?` button
that explains one configuration group without lengthening its description.

The shared process boundary does not parse Git subcommands or options. Generic `run()` and `Popen()` calls fail closed when their argv invokes Git. Git callers must use `run_git()` with an explicit `ordinary` or `destructive` intent; destructive intent is accepted only inside an authorization scope tied to the user's confirmation.

Project-owned GTK icons live directly in `usr/share/gitrepo/icons/`. Keep that
private catalog flat and register it as an additional GTK search path. Only the
two desktop application icons mirror the system theme hierarchy under
`usr/share/icons/hicolor/scalable/apps/`.

### Build Package

`gitrepo.build_package.cli.main_cli` is the terminal entrypoint and `gitrepo.build_package.gui.main_gui` is the GTK entrypoint. Core Git operations expose one reviewed function per user action. `RepositorySnapshot` captures the repository state outside GTK's main loop and distributes one consistent result to the visible pages.

Build Package has four destinations: **Publish Changes** (the workspace facts and
the commit they describe, in one page), **Organize Branches**, **Packages**, and
**Settings**. Packaging hosts two mutually exclusive workflows — this repository or the AUR —
through `TabbedPage`, an inline `Adw.ViewSwitcher`. Settings do the opposite:
`StackedPage` keeps behavior, GitHub access, and destructive maintenance in one
scroll, because settings are scanned rather than navigated. Use a switcher only
for an either/or; never to split one page of settings. Buttons keep the platform
metrics: no custom heights or font sizes. Both applications share the same page grammar: hero, clamped body,
`?` help on a configuration group, state pills instead of bare colour, and a
`page_footer` widget for the page's primary action. The Publish Changes footer
states what the commit will contain and what is still missing before it can run.

Keep destinations shaped by user goals, not by module layout: a page that only
links to other pages, or a second page owning the same decision, belongs merged.

PKGBUILD names come from `makepkg --printsrcinfo`; do not add a second PKGBUILD parser. Destructive operations must use the existing confirmation and authorization boundary.

Stable and extra packages are published only from `main`: `_merge_to_main()`
preserves local-only `main` commits in `backup/main-before-stable-*`, syncs the
working branch with `origin/<branch>` and `origin/main`, and publishes both
remote refs in one `git push --atomic`. A remote race is fetched and retried;
local `main` is aligned only after publication succeeds, and the branch the user
started from is restored. When the journey already starts on `main`,
`_publish_main()` synchronizes and publishes it before dispatch.
`_package_workflow_dispatch()` always sends `main` for stable and extra.
Testing resolves the repository-local `gitrepo.personalBranch`, the current
`dev-*` branch, or `dev-<github-user>` in that order, then publishes that exact
ref before dispatch. Commit journeys honor an explicit `gitrepo.personalBranch`;
without that override, repositories with history remain on their current branch
instead of moving work implicitly.
A merge that needs conflict resolution is never resolved silently. The automatic
path exists — `resolve_divergence(branch, "merge-keep-current", ...)` and
`ConflictResolver.resolve_keeping_current()` merge with `-X ours` like upstream —
but both first list the files that lose their incoming lines, name the branch the
lines come from, and require confirmation; afterwards they report what was
discarded and that `git diff HEAD^2 -- FILE` still shows it. Branch sync tries
rebase, then merge, and only then offers this announced resolution; the pull flow
offers it once before falling back to the per-file review.

`_locate_app_version_entry()` bumps `APP_VERSION` only when one candidate file
declares an `APP_NAME` matching the repository directory or `pkgname`. A tie
means the repository ships several applications and the bump is skipped instead
of guessing. The bump is a two-step contract: `plan_version_bump()` prepares the
new bytes and validates that the target is a regular file inside the repository —
a symlink candidate is refused, never followed — and `publish_version_bump()`
writes it through `common/atomic_file`, preserving the file's own permissions.
`commit_and_push()` plans before confirming, shows the exact version change and
adds the file to the reviewed list, and stops publication when the approved bump
cannot be written. Nothing reaches a commit that the user did not see.

Rewriting the working tree requires a clean starting point. `execute_revert()`
refuses when `git status --porcelain -z` reports any path or when a sequencer
operation (`MERGE_HEAD`, `REVERT_HEAD`, `CHERRY_PICK_HEAD`, `BISECT_LOG`,
`rebase-merge`, `rebase-apply`) is unfinished; a Git failure there reads as
unknown and also blocks, never as clean. Restore uses
`git read-tree -u --reset COMMIT`, not `git checkout COMMIT -- .`, so files added
after the target commit are removed and the promised state is the real one.
On failure nothing is aborted — the entry revision is reported as
`git reset --hard <sha>`, because `--abort` could cancel work started elsewhere.

Remote rewrites use `--force-with-lease=refs/heads/BRANCH:OID` with the OID read
from `origin` immediately before the confirmation, which also names it. A lease
rejection means someone published in between: the remote is left untouched and
the outcome is recorded as `lease_rejected`. Plain `--force` must not come back.

A branch is only offered for deletion when Git proves its tip is already
reachable from the merge base. `merge_base_reference()` picks `origin/main`,
`origin/master`, or their local equivalents, `merged_branches()` delegates to
`git branch --merged`, and cleanup refuses outright when no base exists. Branch
names never decide this: `feature-*` may hold the only copy of a commit. The
preview shows each tip OID, and the branches kept because their commits are not
in the base are reported rather than silently omitted.

`_keep_both_versions()` reads both sides straight from index stages 2 and 3 and
writes them through `O_CREAT | O_EXCL | O_NOFOLLOW`, so an existing `file.ours`
or a symlink under that name is never replaced — the companion becomes
`file.ours.1` instead. Which side resolves the file is then a separate,
explicit choice; cancelling leaves the conflict recorded instead of silently
keeping the incoming version.

`core/git_status.py` is the one reader of Git path lists. `STATUS_COMMAND` and
`CONFLICT_COMMAND` always use `-z`, and `parse_status_records()` /
`parse_path_records()` decode with `os.fsdecode`, because line-oriented
porcelain quotes any path holding a newline, a quote, or non-UTF-8 bytes and
turns it into an unusable pathspec. Its three consumers — the changed-file
inventory, `RepositorySnapshot`, and conflict enumeration — justify one local
parser and nothing wider. Paths shown in a confirmation go through
`display_path()`, so a crafted filename cannot forge extra lines in a list the
user is about to approve. `has_changes()` fails closed: an unreadable status
answers "there is work here", never "clean".

`core/repository_lock.py` gives one journey exclusive ownership of the
repository. Git's index lock protects a single command, not a sequence of
stash, checkout, commit and push. The `@journey(...)` decorator wraps
`commit_and_push`, `pull_latest`, `commit_and_generate_package`,
`execute_revert` and `create_branch_and_push`; the owning thread re-enters
(publishing a package commits first) while another thread or another process
is refused with the holder's name. `OperationRunner` refuses a second GUI
operation for the same reason.

A journey that fails after doing recoverable work says what survived.
`bp.last_operation_details` carries `local_commit_created` /
`local_branch_created`, `remote_unchanged` and `retry_command`, and the
progress dialog turns that into the failure headline. Never delete a local
commit or branch during rollback: it is the most recoverable state there is.

GitHub bulk deletions paginate the complete candidate set before confirming,
state how many items the confirmation covers, and return False when any
deletion failed — a partial deletion reported as success is worse than a
reported failure.

Only a validated GitHub origin may address the GitHub API. `parse_github_remote()`
accepts HTTPS, SSH, git and SCP-style remotes, requires a host in `GITHUB_HOSTS`
and exactly two valid path segments, and returns nothing otherwise — a repository
on another forge with the same `owner/name` must never be reached because the
token happens to have access. Destructive GitHub confirmations name the canonical
`host/owner/repository` from `get_canonical_repository()`.

The diff viewer (`gui/dialogs/diff_viewer_dialog.py`) is the one surface for
reviewing changes: pending files from the workspace and commit pages, and the
files a completed pull brought in.

### Build ISO

`gitrepo.build_iso.cli` is the terminal entrypoint and `gitrepo.build_iso.gui.main_gui` is the GTK entrypoint. `Settings` owns the canonical atomic JSON store. `LocalConfig` is only the flat compatibility view used by the CLI/local builder.

`ContainerManager.capture_status()` runs one runtime/image probe. The main window sends that immutable snapshot to both Dashboard and Build Environment. Do not add independent Docker/Podman probes to either widget.

Build ISO has three destinations: **Create ISO**, **Generated ISOs**, and
**Settings**. Creating an image is one page in decision order — what the image
installs (distribution plus edition cards), where it is saved, then an
`Adw.ExpanderRow` holding kernel, package channels, and the profile source, which
all have defaults worth ignoring. The container environment is a prerequisite,
not a destination: it lives as a section of Settings, is announced by an
`Adw.Banner` on the build page when it breaks, and is otherwise reduced to one
quiet line. A page may publish a `page_footer` widget: the main window moves it
into the content `Adw.ToolbarView` bottom bar when that page becomes visible,
which is how the Create ISO summary and its primary action stay outside the
scrolled form. The sidebar badge on Settings counts the probe items that block a
build.

Every build writes its terminal output to `BuildLogFile`
(`$XDG_STATE_HOME/gitrepo/build-iso/<timestamp>_<distro>-<edition>.log`, mode
0600, newest 20 kept). Profile names come from remote catalogs, so the file name
keeps only `[A-Za-z0-9_-]`. The history entry stores `log_path` and `iso_size`,
which is what the history page and the desktop notification report. Remaining
time comes from `build_estimate`: it projects from elapsed/fraction only after
15% of the build and otherwise falls back to the median duration of comparable
successful builds. The terminal log tags carry explicit foregrounds from
`log_palette()` and follow `Adw.StyleManager`'s dark state.

Cancellation owns exactly one running child at a time. `_own_process()` and
`_release_process()` register the current `Popen` under `_process_lock`, so
`cancel()` can terminate and reap a phase that is blocked reading a stalled
child — a hung `docker pull` produces no further line and would otherwise never
notice. A child spawned after cancellation is killed by `_own_process()` itself.
The progress dialog refuses to close while a build runs: `close-request` routes
through the same confirmation as the Cancel button and keeps the window until
the build reports back, so no daemon thread survives to queue updates into a
closed window. Closing also stops the elapsed timer and disconnects the
`Adw.StyleManager` handler, which is a process-wide singleton and would
otherwise retain every finished dialog and its log buffer.

Every build records what it was actually made from. The container prints
`GITREPO-MANIFEST <name> <sha>` for the `build-iso` and `iso-profiles` clones,
`resolve_image_digest()` pins the image that ran, and both land in
`result["manifest"]`, the retained log, and the history entry. Without that, a
release built from `:latest` plus default branch tips cannot be reconstructed
from the record that describes it.

Artifacts are published with `os.link()`, never `os.replace()`: a name check
followed by a replace silently overwrites a file another process created in
between, and rollback would then delete it. Linking fails instead, and only on
a name we do not own. The ISO checksum comes from `hashlib`, so publication
cannot fail because `md5sum` is missing after an hour of building.

`ISOBuilder._live_setup_guard_commands()` patches `build-iso.sh` so `manjaro-tools`'s `configure_live_image()` only chroots into `/usr/bin/manjaro-live-setup` when the livefs actually ships it. `manjaro-tools-iso-git` always calls it, while stable-branch `manjaro-live-base` (20241119) still performs that setup at live boot. Remove the guard only when every supported branch ships `manjaro-live-base` 20260722 or newer.

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
shfmt -d -ln bash -ci usr/lib/gitrepo/launcher.bash usr/bin/bpkg usr/bin/biso usr/bin/build-iso usr/bin/gitrepo
pytest -q tests/test_launchers.py

for catalog in locale/*.po; do msgfmt --check --output-file=/dev/null "$catalog"; done
desktop-file-validate usr/share/applications/*.desktop usr/share/thunar/sendto/*.desktop
appstreamcli validate --no-net usr/share/metainfo/*.metainfo.xml

bash -n pkgbuild/PKGBUILD
(cd pkgbuild && makepkg --printsrcinfo)
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

Always recompile the MOs after touching a catalog: a stale
`usr/share/locale/<language>/LC_MESSAGES/gitrepo.mo` shows a mixed-language
interface even when the PO is complete. `pt-BR` is the reference catalog and is
kept at 100%; the other 28 languages still have untranslated entries, so
interface strings must stay short and translatable.

Refresh and merge catalogs from the repository root:

```bash
find usr/share -name '*.py' -print0 | sort -z | \
  xargs -0 xgettext --language=Python --from-code=UTF-8 --keyword=_ \
  --package-name=GitRepo --package-version=3.8.1 \
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
