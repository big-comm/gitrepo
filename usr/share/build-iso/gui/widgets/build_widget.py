#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/widgets/build_widget.py - Build configuration and execution widget
#

import json
import os
import shutil
import threading
import urllib.request
import urllib.error

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from core.config import (
    API_PROFILES,
    DEFAULT_EDITIONS,
    EXCLUDED_EDITIONS,
    ISO_PROFILES_REPOS,
    VALID_BRANCHES,
    VALID_DISTROS,
    VALID_KERNELS,
)
from core.translation_utils import _
from gi.repository import Adw, GLib, GObject, Gtk


class BuildWidget(Gtk.Box):
    """Build ISO configuration page"""

    __gtype_name__ = "BuildWidget"

    __gsignals__ = {
        'build-requested': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, settings, logger):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.settings = settings
        self.logger = logger
        self._editions_cache = {}
        self._loading_editions = False

        self.set_margin_start(24)
        self.set_margin_end(24)
        self.set_margin_top(12)
        self.set_margin_bottom(24)

        self._create_ui()
        self._load_from_settings()

        # Fetch editions on startup
        GLib.idle_add(self._fetch_editions_async)

    def _create_ui(self):
        """Create the build configuration UI"""

        # ── Distribution Section ──
        distro_group = Adw.PreferencesGroup()
        distro_group.set_title(_("Distribution"))
        distro_group.set_description(_("Select the distribution to build"))
        self.append(distro_group)

        self.distro_row = Adw.ComboRow()
        self.distro_row.set_title(_("Distribution"))
        self.distro_row.set_subtitle(_("Choose the target distribution"))

        distro_model = Gtk.StringList()
        self._distro_keys = list(VALID_DISTROS.keys())
        for key in self._distro_keys:
            distro_model.append(VALID_DISTROS[key])
        self.distro_row.set_model(distro_model)
        self.distro_row.connect("notify::selected", self._on_distro_changed)
        distro_group.add(self.distro_row)

        # ── Edition Section ──
        edition_group = Adw.PreferencesGroup()
        edition_group.set_title(_("Edition"))
        edition_group.set_description(_("Select the desktop environment or edition"))
        edition_group.set_margin_top(18)
        self.append(edition_group)

        self.edition_row = Adw.ComboRow()
        self.edition_row.set_title(_("Edition"))
        self.edition_row.set_subtitle(_("Desktop environment"))
        self._edition_model = Gtk.StringList()
        self.edition_row.set_model(self._edition_model)
        edition_group.add(self.edition_row)

        self.edition_spinner = Gtk.Spinner()
        self.edition_spinner.set_visible(False)
        self.edition_row.add_suffix(self.edition_spinner)

        # ── ISO Profiles Source Section ──
        profiles_group = Adw.PreferencesGroup()
        profiles_group.set_title(_("ISO Profiles Source"))
        profiles_group.set_description(_("Where to get iso-profiles (editions and configurations)"))
        profiles_group.set_margin_top(18)
        self.append(profiles_group)

        # Source selector: Official / Custom URL / Local folder
        self.profiles_source_row = Adw.ComboRow()
        self.profiles_source_row.set_title(_("Source"))
        self.profiles_source_row.set_subtitle(_("Choose where to load iso-profiles from"))
        source_model = Gtk.StringList()
        source_model.append(_("Official (GitHub)"))
        source_model.append(_("Custom Repository URL"))
        source_model.append(_("Local Folder"))
        self.profiles_source_row.set_model(source_model)
        self.profiles_source_row.connect("notify::selected", self._on_profiles_source_changed)
        profiles_group.add(self.profiles_source_row)

        # Custom URL entry (hidden by default)
        self.custom_url_row = Adw.EntryRow()
        self.custom_url_row.set_title(_("Repository URL"))
        self.custom_url_row.set_text("")
        self.custom_url_row.set_visible(False)
        self.custom_url_row.connect("changed", self._on_custom_source_changed)
        profiles_group.add(self.custom_url_row)

        # Local folder entry (hidden by default)
        self.local_path_row = Adw.EntryRow()
        self.local_path_row.set_title(_("Local Folder Path"))
        self.local_path_row.set_text("")
        self.local_path_row.set_visible(False)

        local_browse_btn = Gtk.Button()
        local_browse_btn.set_icon_name("folder-open-symbolic")
        local_browse_btn.set_valign(Gtk.Align.CENTER)
        local_browse_btn.set_tooltip_text(_("Browse..."))
        local_browse_btn.connect("clicked", self._on_browse_local_profiles)
        self.local_path_row.add_suffix(local_browse_btn)
        self.local_path_row.connect("changed", self._on_custom_source_changed)
        profiles_group.add(self.local_path_row)

        # Profiles info label
        self.profiles_info_label = Gtk.Label()
        self.profiles_info_label.set_halign(Gtk.Align.START)
        self.profiles_info_label.add_css_class("dim-label")
        self.profiles_info_label.add_css_class("caption")
        self.profiles_info_label.set_margin_top(4)
        self.profiles_info_label.set_margin_start(12)
        profiles_group.add(self.profiles_info_label)

        # ── Kernel Section ──
        kernel_group = Adw.PreferencesGroup()
        kernel_group.set_title(_("Kernel"))
        kernel_group.set_margin_top(18)
        self.append(kernel_group)

        self.kernel_row = Adw.ComboRow()
        self.kernel_row.set_title(_("Kernel"))
        self.kernel_row.set_subtitle(_("Linux kernel version"))

        kernel_model = Gtk.StringList()
        self._kernel_keys = list(VALID_KERNELS.keys())
        for key in self._kernel_keys:
            kernel_model.append(VALID_KERNELS[key])
        self.kernel_row.set_model(kernel_model)
        kernel_group.add(self.kernel_row)

        # ── Branches Section ──
        branches_group = Adw.PreferencesGroup()
        branches_group.set_title(_("Repository Branches"))
        branches_group.set_description(_("Select package repository branches"))
        branches_group.set_margin_top(18)
        self.append(branches_group)

        branch_model = Gtk.StringList()
        for b in VALID_BRANCHES:
            branch_model.append(b.capitalize())

        self.manjaro_branch_row = Adw.ComboRow()
        self.manjaro_branch_row.set_title(_("Manjaro Branch"))
        self.manjaro_branch_row.set_subtitle(_("Base repository branch"))
        self.manjaro_branch_row.set_model(branch_model)
        branches_group.add(self.manjaro_branch_row)

        branch_model2 = Gtk.StringList()
        for b in VALID_BRANCHES:
            branch_model2.append(b.capitalize())

        self.biglinux_branch_row = Adw.ComboRow()
        self.biglinux_branch_row.set_title(_("BigLinux Branch"))
        self.biglinux_branch_row.set_subtitle(_("BigLinux repository branch"))
        self.biglinux_branch_row.set_model(branch_model2)
        branches_group.add(self.biglinux_branch_row)

        branch_model3 = Gtk.StringList()
        for b in VALID_BRANCHES:
            branch_model3.append(b.capitalize())

        self.community_branch_row = Adw.ComboRow()
        self.community_branch_row.set_title(_("Community Branch"))
        self.community_branch_row.set_subtitle(_("Community repository branch"))
        self.community_branch_row.set_model(branch_model3)
        branches_group.add(self.community_branch_row)

        # ── Output Section ──
        output_group = Adw.PreferencesGroup()
        output_group.set_title(_("Output"))
        output_group.set_margin_top(18)
        self.append(output_group)

        self.output_row = Adw.EntryRow()
        self.output_row.set_title(_("Output Directory"))
        self.output_row.set_text(self.settings.output_dir)

        browse_btn = Gtk.Button()
        browse_btn.set_icon_name("folder-open-symbolic")
        browse_btn.set_valign(Gtk.Align.CENTER)
        browse_btn.set_tooltip_text(_("Browse..."))
        browse_btn.connect("clicked", self._on_browse_output)
        self.output_row.add_suffix(browse_btn)
        output_group.add(self.output_row)

        # Disk space info
        self.disk_label = Gtk.Label()
        self.disk_label.set_halign(Gtk.Align.START)
        self.disk_label.add_css_class("dim-label")
        self.disk_label.add_css_class("caption")
        self.disk_label.set_margin_top(4)
        self.disk_label.set_margin_start(12)
        output_group.add(self.disk_label)
        self._update_disk_space()

        # ── Options Section ──
        options_group = Adw.PreferencesGroup()
        options_group.set_title(_("Options"))
        options_group.set_margin_top(18)
        self.append(options_group)

        self.clean_cache_row = Adw.SwitchRow()
        self.clean_cache_row.set_title(_("Clean cache before build"))
        self.clean_cache_row.set_subtitle(_("Removes cached packages - increases build time"))
        options_group.add(self.clean_cache_row)

        self.clean_after_row = Adw.SwitchRow()
        self.clean_after_row.set_title(_("Clean cache after build"))
        self.clean_after_row.set_subtitle(_("Free disk space after successful build"))
        options_group.add(self.clean_after_row)

        # ── Build Button ──
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_top(24)
        button_box.set_margin_bottom(12)

        self.build_button = Gtk.Button()
        self.build_button.set_label(_("Start Build"))
        self.build_button.add_css_class("suggested-action")
        self.build_button.add_css_class("pill")
        self.build_button.connect("clicked", self._on_build_clicked)
        button_box.append(self.build_button)

        self.append(button_box)

    def _load_from_settings(self):
        """Load settings into UI"""
        # Distro
        distro = self.settings.distribution
        if distro in self._distro_keys:
            self.distro_row.set_selected(self._distro_keys.index(distro))

        # Kernel
        kernel = self.settings.kernel
        if kernel in self._kernel_keys:
            self.kernel_row.set_selected(self._kernel_keys.index(kernel))

        # Branches
        branches = self.settings.branches
        for i, b in enumerate(VALID_BRANCHES):
            if b == branches.get("manjaro", "stable"):
                self.manjaro_branch_row.set_selected(i)
            if b == branches.get("biglinux", "stable"):
                self.biglinux_branch_row.set_selected(i)
            if b == branches.get("community", "stable"):
                self.community_branch_row.set_selected(i)

        # Output dir
        self.output_row.set_text(self.settings.output_dir)

        # Options
        self.clean_cache_row.set_active(self.settings.get("build", "clean_cache_before", default=False))
        self.clean_after_row.set_active(self.settings.get("build", "clean_cache_after", default=False))

        # ISO Profiles source
        source = self.settings.get("build", "iso_profiles_source", default="remote")
        if source == "remote":
            self.profiles_source_row.set_selected(0)
        elif source == "custom_url":
            self.profiles_source_row.set_selected(1)
            self.custom_url_row.set_text(self.settings.get("build", "iso_profiles_custom_url", default=""))
        elif source == "local":
            self.profiles_source_row.set_selected(2)
            self.local_path_row.set_text(self.settings.get("build", "iso_profiles_local_path", default=""))
        self._on_profiles_source_changed(self.profiles_source_row, None)

    def _on_profiles_source_changed(self, row, pspec):
        """Handle profiles source change"""
        idx = self.profiles_source_row.get_selected()
        self.custom_url_row.set_visible(idx == 1)
        self.local_path_row.set_visible(idx == 2)

        if idx == 0:
            self.profiles_info_label.set_text(_("Editions fetched from official GitHub repositories"))
        elif idx == 1:
            self.profiles_info_label.set_text(_("Provide a git URL to your iso-profiles fork"))
        elif idx == 2:
            self.profiles_info_label.set_text(_("Select a local folder containing iso-profiles"))

        # Clear cache to force refetch
        self._editions_cache.clear()
        self._fetch_editions_async()

    def _on_custom_source_changed(self, row):
        """Handle custom URL or local path change - refresh editions"""
        self._editions_cache.clear()
        self._fetch_editions_async()

    def _on_browse_local_profiles(self, button):
        """Open folder chooser for local iso-profiles"""
        dialog = Gtk.FileDialog()
        dialog.set_title(_("Select iso-profiles Folder"))
        dialog.select_folder(self.get_root(), None, self._on_local_profiles_selected)

    def _on_local_profiles_selected(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                self.local_path_row.set_text(folder.get_path())
                self._editions_cache.clear()
                self._fetch_editions_async()
        except Exception:
            pass

    def _get_profiles_source(self):
        """Get current profiles source type and value"""
        idx = self.profiles_source_row.get_selected()
        if idx == 0:
            return "remote", ""
        elif idx == 1:
            return "custom_url", self.custom_url_row.get_text().strip()
        elif idx == 2:
            return "local", self.local_path_row.get_text().strip()
        return "remote", ""

    def _on_distro_changed(self, row, pspec):
        """Handle distribution change - refresh editions"""
        self._editions_cache.clear()
        self._fetch_editions_async()

    def _fetch_editions_async(self):
        """Fetch available editions based on selected source"""
        distro_key = self._get_selected_distro()
        source_type, source_value = self._get_profiles_source()
        cache_key = f"{distro_key}:{source_type}:{source_value}"

        if cache_key in self._editions_cache:
            self._populate_editions(self._editions_cache[cache_key])
            return

        self.edition_spinner.set_visible(True)
        self.edition_spinner.start()
        self._loading_editions = True

        thread = threading.Thread(
            target=self._fetch_editions_worker,
            args=(distro_key, source_type, source_value, cache_key),
            daemon=True,
        )
        thread.start()

    def _fetch_editions_worker(self, distro_key, source_type, source_value, cache_key):
        """Worker thread to fetch editions from configured source"""
        editions = []

        if source_type == "local" and source_value:
            # Read editions from local folder
            editions = self._read_local_editions(source_value, distro_key)
        elif source_type == "custom_url" and source_value:
            # Try GitHub API for the custom URL, or list from clone
            editions = self._fetch_custom_url_editions(source_value, distro_key)
        else:
            # Official GitHub API
            try:
                url = API_PROFILES.get(distro_key, "")
                if url:
                    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.v3+json"})
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        data = json.loads(resp.read().decode())
                        editions = sorted([
                            item["name"] for item in data
                            if item.get("type") == "dir" and not item["name"].startswith(".")
                        ])
            except Exception:
                pass

        if not editions:
            editions = DEFAULT_EDITIONS.get(distro_key, ["gnome"])

        # Filter out excluded editions (development/incomplete profiles)
        editions = [e for e in editions if e.lower() not in EXCLUDED_EDITIONS]

        self._editions_cache[cache_key] = editions
        GLib.idle_add(self._populate_editions, editions)

    def _read_local_editions(self, local_path, distro_key):
        """Read available editions from a local iso-profiles directory"""
        editions = []
        # iso-profiles structure: <path>/<distro>/<edition>/
        distro_path = os.path.join(local_path, distro_key)
        if not os.path.isdir(distro_path):
            # Maybe the path IS the distro folder directly
            distro_path = local_path

        if os.path.isdir(distro_path):
            for entry in sorted(os.listdir(distro_path)):
                full = os.path.join(distro_path, entry)
                if os.path.isdir(full) and not entry.startswith("."):
                    # Verify it looks like a profile (has profiledef or packages files)
                    if any(os.path.exists(os.path.join(full, f)) for f in [
                        "profiledef.sh", "Packages-Desktop", "packages.x86_64", "packages-desktop"
                    ]) or True:  # Accept any subdirectory as potential edition
                        editions.append(entry)
        return editions

    def _fetch_custom_url_editions(self, url, distro_key):
        """Fetch editions from a custom git URL via GitHub API or shallow clone"""
        editions = []

        # Try GitHub API if it's a GitHub URL
        # e.g. https://github.com/user/iso-profiles → API: https://api.github.com/repos/user/iso-profiles/contents/<distro>
        if "github.com" in url:
            try:
                # Extract owner/repo from URL
                parts = url.rstrip("/").rstrip(".git").split("github.com/")[-1].split("/")
                if len(parts) >= 2:
                    owner, repo = parts[0], parts[1]
                    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{distro_key}"
                    req = urllib.request.Request(api_url, headers={"Accept": "application/vnd.github.v3+json"})
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        data = json.loads(resp.read().decode())
                        editions = sorted([
                            item["name"] for item in data
                            if item.get("type") == "dir" and not item["name"].startswith(".")
                        ])
            except Exception:
                pass

        # Fallback: try shallow clone to temp dir if API fails
        if not editions:
            import tempfile
            import subprocess
            tmpdir = tempfile.mkdtemp(prefix="iso-profiles-")
            try:
                subprocess.run(
                    ["git", "clone", "--depth", "1", url, tmpdir],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=30, check=True,
                )
                editions = self._read_local_editions(tmpdir, distro_key)
            except Exception:
                pass
            finally:
                import shutil
                shutil.rmtree(tmpdir, ignore_errors=True)

        return editions

    def _populate_editions(self, editions):
        """Populate edition combo with fetched data (main thread)"""
        self.edition_spinner.stop()
        self.edition_spinner.set_visible(False)
        self._loading_editions = False

        # Check if there's a pending edition from profile selection
        pending = getattr(self, "_pending_edition", None)
        current_edition = pending if pending else self.settings.edition
        if pending:
            self._pending_edition = None

        # Clear and repopulate
        self._edition_model = Gtk.StringList()
        for e in editions:
            self._edition_model.append(e)
        self.edition_row.set_model(self._edition_model)

        # Restore selection
        if current_edition in editions:
            self.edition_row.set_selected(editions.index(current_edition))
        else:
            self.edition_row.set_selected(0)

    def _get_selected_distro(self):
        idx = self.distro_row.get_selected()
        if 0 <= idx < len(self._distro_keys):
            return self._distro_keys[idx]
        return self._distro_keys[0]

    def _get_selected_edition(self):
        model = self.edition_row.get_model()
        idx = self.edition_row.get_selected()
        if model and 0 <= idx < model.get_n_items():
            return model.get_string(idx)
        return "gnome"

    def _get_selected_kernel(self):
        idx = self.kernel_row.get_selected()
        if 0 <= idx < len(self._kernel_keys):
            return self._kernel_keys[idx]
        return "lts"

    def _get_selected_branch(self, row):
        idx = row.get_selected()
        if 0 <= idx < len(VALID_BRANCHES):
            return VALID_BRANCHES[idx]
        return "stable"

    def _on_browse_output(self, button):
        """Open folder chooser for output directory"""
        dialog = Gtk.FileDialog()
        dialog.set_title(_("Select Output Directory"))
        dialog.select_folder(self.get_root(), None, self._on_folder_selected)

    def _on_folder_selected(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                path = folder.get_path()
                self.output_row.set_text(path)
                self._update_disk_space()
        except Exception:
            pass

    def _update_disk_space(self):
        """Update disk space label"""
        path = self.output_row.get_text()
        if path and os.path.exists(path):
            usage = shutil.disk_usage(path)
            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)
            if free_gb < 20:
                self.disk_label.remove_css_class("dim-label")
                self.disk_label.add_css_class("status-warning")
            self.disk_label.set_text(
                _("Disk space: {0:.1f} GB free of {1:.1f} GB").format(free_gb, total_gb)
            )
        else:
            self.disk_label.set_text(_("Output directory does not exist yet"))

    def set_build_config(self, distro_key, edition):
        """Set distro and edition from external source (e.g. profiles page)"""
        self._pending_edition = edition

        # Check if distro is already selected
        current_distro = self._get_selected_distro()
        if current_distro == distro_key:
            # Distro already selected - try to set edition directly from current model
            model = self.edition_row.get_model()
            if model:
                for i in range(model.get_n_items()):
                    if model.get_string(i) == edition:
                        self.edition_row.set_selected(i)
                        self._pending_edition = None
                        return
            # Edition not in model yet, force re-fetch
            self._fetch_editions_async()
        else:
            # Set distro - this triggers _on_distro_changed which fetches editions
            for i, key in enumerate(VALID_DISTROS):
                if key == distro_key:
                    self.distro_row.set_selected(i)
                    break

    def _on_build_clicked(self, button):
        """Handle Start Build button click"""
        distro = self._get_selected_distro()
        source_type, source_value = self._get_profiles_source()

        # Determine iso_profiles_repo based on source
        if source_type == "custom_url" and source_value:
            iso_profiles_repo = source_value
        elif source_type == "local":
            iso_profiles_repo = ISO_PROFILES_REPOS.get(distro, "")
        else:
            iso_profiles_repo = ISO_PROFILES_REPOS.get(distro, "")

        config = {
            "distroname": distro,
            "edition": self._get_selected_edition(),
            "kernel": self._get_selected_kernel(),
            "branches": {
                "manjaro": self._get_selected_branch(self.manjaro_branch_row),
                "biglinux": self._get_selected_branch(self.biglinux_branch_row),
                "community": self._get_selected_branch(self.community_branch_row),
            },
            "iso_profiles_repo": iso_profiles_repo,
            "iso_profiles_source": source_type,
            "iso_profiles_local_path": source_value if source_type == "local" else "",
            "build_dir": distro,
            "output_dir": self.output_row.get_text(),
            "clean_cache": self.clean_cache_row.get_active(),
            "clean_cache_after_build": self.clean_after_row.get_active(),
            "container_engine": self.settings.get("container", "engine", default="docker"),
            "container_image": self.settings.container_image,
        }

        # Save selections to settings
        self.settings.distribution = distro
        self.settings.edition = config["edition"]
        self.settings.kernel = config["kernel"]
        self.settings.branches = config["branches"]
        self.settings.output_dir = config["output_dir"]
        self.settings.set("build", "clean_cache_before", config["clean_cache"])
        self.settings.set("build", "clean_cache_after", config["clean_cache_after_build"])
        self.settings.set("build", "iso_profiles_source", source_type)
        if source_type == "custom_url":
            self.settings.set("build", "iso_profiles_custom_url", source_value)
        elif source_type == "local":
            self.settings.set("build", "iso_profiles_local_path", source_value)
        self.settings.save()

        self.emit("build-requested", config)

    def refresh(self):
        """Refresh widget state"""
        self._update_disk_space()
