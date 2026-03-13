#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/widgets/profiles_widget.py - ISO profiles browser widget
#

import json
import os
import shutil
import subprocess
import tempfile
import threading
import urllib.request

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from core.config import (
    API_PROFILES,
    DEFAULT_EDITIONS,
    EXCLUDED_EDITIONS,
    ISO_PROFILES_REPOS,
    VALID_DISTROS,
)
from core.translation_utils import _
from gi.repository import Adw, GLib, GObject, Gtk


class ProfilesWidget(Gtk.Box):
    """Browse and select ISO profiles for each distribution"""

    __gtype_name__ = "ProfilesWidget"

    __gsignals__ = {
        "navigate-to": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "profile-selected": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),  # distro, edition
    }

    def __init__(self, settings):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.settings = settings
        self._profiles_data = {}

        self.set_margin_start(24)
        self.set_margin_end(24)
        self.set_margin_top(12)
        self.set_margin_bottom(24)

        self._create_ui()
        GLib.idle_add(self._fetch_all_profiles)

    def _create_ui(self):
        """Create profiles browser UI"""

        # Header with source info
        self.header_group = Adw.PreferencesGroup()
        self.header_group.set_title(_("ISO Profiles"))
        self.header_group.set_description(_("Click an edition to configure and build"))
        self.append(self.header_group)

        # Source info row
        self.source_row = Adw.ActionRow()
        self.source_row.set_title(_("Profiles Source"))
        self._update_source_label()
        source_icon = Gtk.Image.new_from_icon_name("folder-remote-symbolic")
        self.source_row.add_prefix(source_icon)

        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.set_valign(Gtk.Align.CENTER)
        refresh_btn.set_tooltip_text(_("Refresh profiles"))
        refresh_btn.connect("clicked", self._on_refresh_clicked)
        self.source_row.add_suffix(refresh_btn)
        self.header_group.add(self.source_row)

        # Spinner for loading
        self.spinner = Gtk.Spinner()
        self.spinner.set_size_request(32, 32)
        self.spinner.set_halign(Gtk.Align.CENTER)
        self.spinner.set_margin_top(24)
        self.spinner.start()
        self.append(self.spinner)

        # Container for profile groups
        self.profiles_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.profiles_box.set_margin_top(12)
        self.append(self.profiles_box)

    def _update_source_label(self):
        """Update the source description based on current settings"""
        source = self.settings.get("build", "iso_profiles_source", default="remote")
        if source == "local":
            path = self.settings.get("build", "iso_profiles_local_path", default="")
            self.source_row.set_subtitle(_("Local: {0}").format(path or _("not configured")))
        elif source == "custom_url":
            url = self.settings.get("build", "iso_profiles_custom_url", default="")
            self.source_row.set_subtitle(_("Custom: {0}").format(url or _("not configured")))
        else:
            self.source_row.set_subtitle(_("Official GitHub repositories"))

    def _on_refresh_clicked(self, button):
        """Refresh profiles list"""
        self._profiles_data.clear()
        # Clear existing content
        child = self.profiles_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.profiles_box.remove(child)
            child = next_child
        self._update_source_label()
        self.spinner.set_visible(True)
        self.spinner.start()
        self._fetch_all_profiles()

    def refresh(self):
        """Public refresh method"""
        self._on_refresh_clicked(None)

    def _fetch_all_profiles(self):
        thread = threading.Thread(target=self._fetch_worker, daemon=True)
        thread.start()

    def _fetch_worker(self):
        source = self.settings.get("build", "iso_profiles_source", default="remote")
        source_url = self.settings.get("build", "iso_profiles_custom_url", default="")
        source_local = self.settings.get("build", "iso_profiles_local_path", default="")

        results = {}
        for distro_key in VALID_DISTROS:
            editions = []

            if source == "local" and source_local:
                editions = self._read_local_editions(source_local, distro_key)
            elif source == "custom_url" and source_url:
                editions = self._fetch_custom_url_editions(source_url, distro_key)
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
                editions = DEFAULT_EDITIONS.get(distro_key, [])

            # Apply exclusion filter
            editions = [e for e in editions if e.lower() not in EXCLUDED_EDITIONS]
            results[distro_key] = editions

        GLib.idle_add(self._populate_profiles, results)

    def _read_local_editions(self, local_path, distro_key):
        """Read editions from local iso-profiles directory"""
        editions = []
        distro_path = os.path.join(local_path, distro_key)
        if not os.path.isdir(distro_path):
            distro_path = local_path

        if os.path.isdir(distro_path):
            for entry in sorted(os.listdir(distro_path)):
                full = os.path.join(distro_path, entry)
                if os.path.isdir(full) and not entry.startswith("."):
                    editions.append(entry)
        return editions

    def _fetch_custom_url_editions(self, url, distro_key):
        """Fetch editions from a custom git URL"""
        editions = []

        if "github.com" in url:
            try:
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

        if not editions:
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
                shutil.rmtree(tmpdir, ignore_errors=True)

        return editions

    def _populate_profiles(self, results):
        self.spinner.stop()
        self.spinner.set_visible(False)

        self._profiles_data = results

        for distro_key, editions in results.items():
            distro_name = VALID_DISTROS.get(distro_key, distro_key)

            group = Adw.PreferencesGroup()
            group.set_title(distro_name)
            group.set_description(_("{0} editions available").format(len(editions)))

            for edition in editions:
                row = Adw.ActionRow()
                row.set_title(edition.capitalize())
                row.set_subtitle(f"{distro_name} - {edition}")
                row.set_activatable(True)

                icon = Gtk.Image.new_from_icon_name("media-optical-symbolic")
                row.add_prefix(icon)

                arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
                arrow.set_valign(Gtk.Align.CENTER)
                row.add_suffix(arrow)

                row._distro_key = distro_key
                row._edition = edition
                row.connect("activated", self._on_profile_activated)

                group.add(row)

            self.profiles_box.append(group)

        return False

    def _on_profile_activated(self, row):
        """Handle profile row click - emit signal to navigate to build with this profile"""
        self.emit("profile-selected", row._distro_key, row._edition)
        self.emit("navigate-to", "build")
