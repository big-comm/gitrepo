#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/widgets/history_widget.py - Build history widget
#

import json
import os

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from core.config import HISTORY_FILE
from core.translation_utils import _
from gi.repository import Adw, GLib, GObject, Gtk


class HistoryWidget(Gtk.Box):
    """Build history page"""

    __gtype_name__ = "HistoryWidget"

    def __init__(self, settings):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.settings = settings

        self.set_margin_start(24)
        self.set_margin_end(24)
        self.set_margin_top(12)
        self.set_margin_bottom(24)

        self._create_ui()
        self.refresh()

    def _create_ui(self):
        """Create history UI"""

        self.history_group = Adw.PreferencesGroup()
        self.history_group.set_title(_("Build History"))
        self.history_group.set_description(_("Previous ISO builds and their results"))
        self.append(self.history_group)

        # Empty state
        self.empty_row = Adw.ActionRow()
        self.empty_row.set_title(_("No builds yet"))
        self.empty_row.set_subtitle(_("Build history will appear here after your first build"))
        icon = Gtk.Image.new_from_icon_name("document-open-recent-symbolic")
        self.empty_row.add_prefix(icon)
        self.history_group.add(self.empty_row)

        # Clear history button
        clear_group = Adw.PreferencesGroup()
        clear_group.set_margin_top(24)
        self.append(clear_group)

        clear_row = Adw.ActionRow()
        clear_row.set_title(_("Clear History"))
        clear_row.set_subtitle(_("Remove all build history entries"))
        clear_btn = Gtk.Button()
        clear_btn.set_label(_("Clear"))
        clear_btn.set_valign(Gtk.Align.CENTER)
        clear_btn.add_css_class("destructive-action")
        clear_btn.connect("clicked", self._on_clear_clicked)
        clear_row.add_suffix(clear_btn)
        clear_group.add(clear_row)

    def refresh(self):
        """Reload history from file"""
        history = self._load_history()

        # Remove existing rows (except empty_row)
        child = self.history_group.get_first_child()
        rows_to_remove = []
        while child:
            if child != self.empty_row and isinstance(child, Adw.ActionRow):
                rows_to_remove.append(child)
            child = child.get_next_sibling()
        for row in rows_to_remove:
            self.history_group.remove(row)

        if not history:
            self.empty_row.set_visible(True)
            return

        self.empty_row.set_visible(False)

        # Add history entries (newest first)
        for entry in reversed(history[-50:]):
            row = Adw.ActionRow()
            distro = entry.get("distro", "?")
            edition = entry.get("edition", "?")
            kernel = entry.get("kernel", "?")
            row.set_title(f"{distro} - {edition} ({kernel})")

            date = entry.get("date", "?")
            success = entry.get("success", False)
            duration_s = entry.get("duration", 0)
            duration_min = duration_s // 60
            status = _("Success") if success else _("Failed")
            row.set_subtitle(f"{date} | {status} | {duration_min} min")

            if success:
                icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
                icon.add_css_class("status-ok")
            else:
                icon = Gtk.Image.new_from_icon_name("dialog-error-symbolic")
                icon.add_css_class("status-error")
            row.add_prefix(icon)

            iso_path = entry.get("iso_path", "")
            if iso_path and os.path.exists(iso_path):
                open_btn = Gtk.Button()
                open_btn.set_icon_name("folder-open-symbolic")
                open_btn.set_valign(Gtk.Align.CENTER)
                open_btn.set_tooltip_text(_("Open folder"))
                open_btn.connect("clicked", self._on_open_folder, os.path.dirname(iso_path))
                row.add_suffix(open_btn)

            self.history_group.add(row)

    def _load_history(self):
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, "r") as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def _on_clear_clicked(self, button):
        dialog = Adw.AlertDialog(
            heading=_("Clear Build History?"),
            body=_("This will remove all build history entries. This cannot be undone."),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("clear", _("Clear"))
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_clear_confirmed)
        dialog.present(self.get_root())

    def _on_clear_confirmed(self, dialog, response):
        if response == "clear":
            try:
                if os.path.exists(HISTORY_FILE):
                    os.remove(HISTORY_FILE)
            except Exception:
                pass
            self.refresh()

    def _on_open_folder(self, button, folder_path):
        import subprocess
        subprocess.Popen(["xdg-open", folder_path])

    @staticmethod
    def add_entry(entry: dict):
        """Add a build entry to history"""
        history = []
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, "r") as f:
                    history = json.load(f)
        except Exception:
            pass

        history.append(entry)

        # Keep last 100 entries
        history = history[-100:]

        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
