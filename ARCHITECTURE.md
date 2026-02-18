# Architecture — GitRepo Tools

## Overview

GitRepo Tools provides two command-line/GUI tools for BigCommunity Linux distribution development:

- **`bpkg`** (Build Package) — package build, commit, and GitHub Actions dispatch
- **`biso`** (Build ISO) — ISO image creation via GitHub Actions

Both are Python 3 applications. `bpkg` also has a GTK4/libadwaita GUI.

---

## Build Package (`usr/share/build-package/`)

### Layer Diagram

```
 ┌──────────────────────────────────────────────┐
 │               Entry point                    │
 │         usr/bin/bpkg (shell wrapper)         │
 └─────────────────┬────────────────────────────┘
                   │
                   ▼
 ┌──────────────────────────────────────────────┐
 │            Dispatcher: main.py               │
 │  Detects CLI / GUI mode from:                │
 │  • argv flags (--cli, --gui, --no-gui)       │
 │  • presence of positional args → CLI         │
 │  • DISPLAY/WAYLAND_DISPLAY presence → GUI    │
 │  • GTK4/Adw import success → GUI fallback    │
 └──────────┬───────────────────┬───────────────┘
            │                   │
            ▼                   ▼
 ┌──────────────────┐  ┌────────────────────────┐
 │   cli/ (TUI)     │  │    gui/ (GTK4)         │
 │  main_cli.py     │  │  main_gui.py           │
 │  menu_system.py  │  │  main_window.py        │
 │  logger.py       │  │  gtk_menu.py           │
 │                  │  │  gtk_logger.py         │
 │                  │  │  gtk_adapters.py       │
 │                  │  │  widgets/  dialogs/    │
 └────────┬─────────┘  └───────────┬────────────┘
          │                        │
          └────────────┬───────────┘
                       │ Both use core/
                       ▼
 ┌──────────────────────────────────────────────┐
 │                 core/ (shared)               │
 │  BuildPackage      — main business logic     │
 │  git_utils.py      — Git CLI wrappers        │
 │  github_api.py     — REST API + token mgmt   │
 │  token_store.py    — ~/.config/gitrepo/...   │
 │  config.py         — constants               │
 │  commit_operations.py  pull_operations.py    │
 │  package_operations.py conflict_resolver.py  │
 │  settings.py / settings_menu.py             │
 │  translation_utils.py                        │
 └──────────────────────────────────────────────┘
```

### Key Design Decisions

**Dual-interface**: CLI and GUI share 100% of business logic in `core/`. Neither interface imports from the other.

**Async pattern (GUI)**: Long-running operations use `threading.Thread(daemon=True)` + `GLib.idle_add()` callbacks to keep the GTK main loop responsive.

**Token storage** (`core/token_store.py`): Single source of truth for `~/.config/gitrepo/github_token`. Supports multi-org format (`org=token` per line). Handles one-time migration from the legacy `~/.GITHUB_TOKEN` location. Permissions: `chmod 600`.

**Settings** (`core/settings.py`): JSON file at `~/.config/gitrepo/settings.json`. GTK-independent; read and written by both interfaces.

**Operation modules**: Large operations extracted from `BuildPackage` into dedicated modules (`commit_operations`, `pull_operations`, `package_operations`, `conflict_resolver`). These are plain functions that receive a `BuildPackage` instance.

---

## GUI Structure (`gui/`)

| File / Dir | Responsibility |
|---|---|
| `main_gui.py` | `GtkApplication` subclass; single-instance lifecycle, `GAction` registration |
| `main_window.py` | `AdwApplicationWindow`; sidebar nav, `Adw.OverlaySplitView`, content stack |
| `gtk_menu.py` | `MenuSystem` adapter — translates rich-menu calls to `Adw.AlertDialog` |
| `gtk_logger.py` | Logger adapter — bridges `BuildPackage` log calls to GTK widgets |
| `gtk_adapters.py` | Adapter shims for CLI → GUI redirection |
| `widgets/` | Per-page `Gtk.Widget` subclasses (overview, commit, branch, package, aur, advanced) |
| `dialogs/` | Modal dialogs: preferences, settings, progress, conflict, about |

### Navigation model

The sidebar uses `Gtk.ListBox` with `Adw.ActionRow` rows (prefix icon + title + optional badge). Page content lives in an `Adw.ViewStack`. The active page is driven by `on_nav_row_selected`.

Icon prefixes are marked `Gtk.AccessibleRole.PRESENTATION` (decorative). The row title is the AT-SPI accessible label. When the Commit badge shows a count, `update_property(LABEL)` broadcasts the count to screen readers.

---

## Build ISO (`usr/share/build-iso/`)

Simpler architecture — CLI only, no GUI layer.

```
usr/bin/biso → main.py → build_iso.py
                           ├── config.py        (org defaults, ISO profiles URLs)
                           ├── git_utils.py     (Git ops)
                           ├── github_api.py    (workflow dispatch)
                           ├── menu_system.py   (Rich TUI)
                           ├── logger.py
                           ├── local_builder.py (optional local build path)
                           └── translation_utils.py
```

**Plug-and-play orgs**: Adding a new organization requires editing only `config.py` — `VALID_ORGANIZATIONS`, `ORG_DEFAULT_CONFIGS`, and the profile URL maps. No logic changes needed.

---

## Token File Format

Path: `~/.config/gitrepo/github_token`  Permissions: `0o600`

```
# Single generic token
ghp_yourtoken

# Or per-organisation tokens
big-comm=ghp_token_for_big_comm
biglinux=ghp_token_for_biglinux
```

`TokenStore.get(org)` tries the org-specific key first, then falls back to a bare token on the first line. `TokenStore._migrate_if_needed()` runs once on first access to copy `~/.GITHUB_TOKEN` to the new location.

---

## Threading & Safety

- **GUI thread**: only GTK widget calls; driven by `GLib.idle_add` callbacks
- **Worker threads**: `threading.Thread(daemon=True)` — no GTK calls inside
- **Exception capture**: worker catches to a string *before* the lambda to avoid Python 3 scoping issue with `except Exception as e` (the variable is deleted after the block)

---

## Internationalisation

- `gettext`-based via `translation_utils.py` in each subtree
- Marker: `_("String")`
- Template: `locale/gitrepo.pot`
- Compiled `.mo` files per language in `usr/share/locale/<lang>/LC_MESSAGES/`
- 30+ languages supported

---

## Linting

`pyproject.toml` at repo root configures **ruff** with rules `E` + `F` (E501 excluded). Per-file ignores cover structural `E402` (module-level imports after `gi.require_version()` calls).

Run: `ruff check usr/share/build-package/ usr/share/build-iso/`
