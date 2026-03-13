#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/widgets/settings_widget.py - Settings page widget
#

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from core.config import CONTAINER_IMAGE, DEFAULT_OUTPUT_DIR, VALID_BRANCHES
from core.translation_utils import _
from gi.repository import Adw, GLib, GObject, Gtk


class SettingsWidget(Gtk.Box):
    """Application settings page"""

    __gtype_name__ = "SettingsWidget"

    __gsignals__ = {
        'settings-saved': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, settings):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.settings = settings
        self._loading = False

        self.set_margin_start(24)
        self.set_margin_end(24)
        self.set_margin_top(12)
        self.set_margin_bottom(24)

        self._create_ui()
        self._load_settings()

    def _create_ui(self):
        """Create settings UI"""

        # ── General ──
        general_group = Adw.PreferencesGroup()
        general_group.set_title(_("General"))
        self.append(general_group)

        self.output_row = Adw.EntryRow()
        self.output_row.set_title(_("Default Output Directory"))
        self.output_row.connect("changed", self._on_output_dir_changed)
        browse_btn = Gtk.Button()
        browse_btn.set_icon_name("folder-open-symbolic")
        browse_btn.set_valign(Gtk.Align.CENTER)
        browse_btn.connect("clicked", self._on_browse_output)
        self.output_row.add_suffix(browse_btn)
        general_group.add(self.output_row)

        # ── Container ──
        container_group = Adw.PreferencesGroup()
        container_group.set_title(_("Container"))
        container_group.set_margin_top(24)
        self.append(container_group)

        self.engine_row = Adw.ComboRow()
        self.engine_row.set_title(_("Container Engine"))
        self.engine_row.set_subtitle(_("Preferred container engine"))
        engine_model = Gtk.StringList()
        engine_model.append("Docker")
        engine_model.append("Podman")
        self.engine_row.set_model(engine_model)
        container_group.add(self.engine_row)

        self.image_row = Adw.EntryRow()
        self.image_row.set_title(_("Container Image"))
        container_group.add(self.image_row)

        # ── Defaults ──
        defaults_group = Adw.PreferencesGroup()
        defaults_group.set_title(_("Build Defaults"))
        defaults_group.set_margin_top(24)
        self.append(defaults_group)

        branch_model = Gtk.StringList()
        for b in VALID_BRANCHES:
            branch_model.append(b.capitalize())

        self.default_manjaro_branch = Adw.ComboRow()
        self.default_manjaro_branch.set_title(_("Default Manjaro Branch"))
        self.default_manjaro_branch.set_model(branch_model)
        defaults_group.add(self.default_manjaro_branch)

        branch_model2 = Gtk.StringList()
        for b in VALID_BRANCHES:
            branch_model2.append(b.capitalize())

        self.default_biglinux_branch = Adw.ComboRow()
        self.default_biglinux_branch.set_title(_("Default BigLinux Branch"))
        self.default_biglinux_branch.set_model(branch_model2)
        defaults_group.add(self.default_biglinux_branch)

        branch_model3 = Gtk.StringList()
        for b in VALID_BRANCHES:
            branch_model3.append(b.capitalize())

        self.default_community_branch = Adw.ComboRow()
        self.default_community_branch.set_title(_("Default BigCommunity Branch"))
        self.default_community_branch.set_model(branch_model3)
        defaults_group.add(self.default_community_branch)

        # ── Notifications ──
        notif_group = Adw.PreferencesGroup()
        notif_group.set_title(_("Notifications"))
        notif_group.set_margin_top(24)
        self.append(notif_group)

        self.notify_complete_row = Adw.SwitchRow()
        self.notify_complete_row.set_title(_("Notify on build completion"))
        self.notify_complete_row.set_subtitle(_("Show desktop notification when build finishes"))
        notif_group.add(self.notify_complete_row)

        self.notify_sound_row = Adw.SwitchRow()
        self.notify_sound_row.set_title(_("Play sound on completion"))
        notif_group.add(self.notify_sound_row)

        # ── Advanced ──
        advanced_group = Adw.PreferencesGroup()
        advanced_group.set_title(_("Advanced"))
        advanced_group.set_margin_top(24)
        self.append(advanced_group)

        self.auto_cleanup_row = Adw.SwitchRow()
        self.auto_cleanup_row.set_title(_("Auto-cleanup old containers"))
        self.auto_cleanup_row.set_subtitle(_("Remove stopped build containers automatically"))
        advanced_group.add(self.auto_cleanup_row)

        # ── Save/Reset ──
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_top(24)

        save_btn = Gtk.Button()
        save_btn.set_label(_("Save Settings"))
        save_btn.add_css_class("suggested-action")
        save_btn.add_css_class("pill")
        save_btn.set_size_request(150, -1)
        save_btn.connect("clicked", self._on_save_clicked)
        button_box.append(save_btn)

        reset_btn = Gtk.Button()
        reset_btn.set_label(_("Reset to Defaults"))
        reset_btn.add_css_class("pill")
        reset_btn.set_size_request(150, -1)
        reset_btn.connect("clicked", self._on_reset_clicked)
        button_box.append(reset_btn)

        self.append(button_box)

    def _load_settings(self):
        """Load current settings into UI"""
        self._loading = True
        self.output_row.set_text(self.settings.output_dir)
        self.image_row.set_text(self.settings.container_image)

        engine = self.settings.get("container", "engine", default="auto")
        self.engine_row.set_selected(0 if engine in ("docker", "auto") else 1)

        branches = self.settings.branches
        for i, b in enumerate(VALID_BRANCHES):
            if b == branches.get("manjaro", "stable"):
                self.default_manjaro_branch.set_selected(i)
            if b == branches.get("biglinux", "stable"):
                self.default_biglinux_branch.set_selected(i)
            if b == branches.get("community", "stable"):
                self.default_community_branch.set_selected(i)

        self.notify_complete_row.set_active(self.settings.get("notifications", "desktop", default=True))
        self.notify_sound_row.set_active(self.settings.get("notifications", "sound", default=False))
        self.auto_cleanup_row.set_active(self.settings.get("build", "clean_cache_after", default=False))
        self._loading = False

    def _on_browse_output(self, button):
        dialog = Gtk.FileDialog()
        dialog.set_title(_("Select Output Directory"))
        dialog.select_folder(self.get_root(), None, self._on_folder_selected)

    def _on_folder_selected(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                self.output_row.set_text(folder.get_path())
        except Exception:
            pass

    def _on_output_dir_changed(self, entry):
        """Auto-save output dir when changed with debounce"""
        if self._loading:
            return
        if hasattr(self, '_output_dir_timeout'):
            GLib.source_remove(self._output_dir_timeout)
        self._output_dir_timeout = GLib.timeout_add(800, self._save_output_dir)

    def _save_output_dir(self):
        """Save output dir and notify"""
        text = self.output_row.get_text().strip()
        if text:
            self.settings.output_dir = text
            self.emit("settings-saved")
        return False

    def _on_save_clicked(self, button):
        """Save settings"""
        self.settings.output_dir = self.output_row.get_text()
        self.settings.container_image = self.image_row.get_text()
        self.settings.set("container", "engine", "docker" if self.engine_row.get_selected() == 0 else "podman")

        branches = {
            "manjaro": VALID_BRANCHES[self.default_manjaro_branch.get_selected()],
            "biglinux": VALID_BRANCHES[self.default_biglinux_branch.get_selected()],
            "community": VALID_BRANCHES[self.default_community_branch.get_selected()],
        }
        self.settings.branches = branches

        self.settings.set("notifications", "desktop", self.notify_complete_row.get_active())
        self.settings.set("notifications", "sound", self.notify_sound_row.get_active())
        self.settings.set("build", "clean_cache_after", self.auto_cleanup_row.get_active())

        self.settings.save()

        self.emit("settings-saved")

        # Show toast via parent window
        root = self.get_root()
        if root and hasattr(root, "show_toast"):
            root.show_toast(_("Settings saved"))

    def _on_reset_clicked(self, button):
        dialog = Adw.AlertDialog(
            heading=_("Reset Settings?"),
            body=_("This will reset all settings to their default values."),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("reset", _("Reset"))
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_reset_confirmed)
        dialog.present(self.get_root())

    def _on_reset_confirmed(self, dialog, response):
        if response == "reset":
            self.settings.reset()
            self._load_settings()
