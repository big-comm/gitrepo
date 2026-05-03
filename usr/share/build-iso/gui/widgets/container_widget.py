#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/widgets/container_widget.py - Container management widget
#

import subprocess
import threading

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from core.config import CONTAINER_IMAGE
from core.container_manager import ContainerManager
from core.translation_utils import _
from gi.repository import Adw, GLib, GObject, Gtk


class ContainerWidget(Gtk.Box):
    """Container engine management page"""

    __gtype_name__ = "ContainerWidget"

    __gsignals__ = {
        'container-action': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, settings, logger):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.settings = settings
        self.logger = logger
        self.container_mgr = ContainerManager()

        self.set_margin_start(24)
        self.set_margin_end(24)
        self.set_margin_top(12)
        self.set_margin_bottom(24)

        self._create_ui()
        GLib.idle_add(self.refresh)

    def _create_ui(self):
        """Create container management UI"""

        # ── Engine Info ──
        info_group = Adw.PreferencesGroup()
        info_group.set_title(_("Container Engine"))
        info_group.set_description(_("Status of the container runtime"))
        self.append(info_group)

        self.engine_row = Adw.ActionRow()
        self.engine_row.set_title(_("Engine"))
        self.engine_row.set_subtitle(_("Detecting..."))
        info_group.add(self.engine_row)

        self.driver_row = Adw.ActionRow()
        self.driver_row.set_title(_("Storage Driver"))
        self.driver_row.set_subtitle(_("Checking..."))
        info_group.add(self.driver_row)

        self.version_row = Adw.ActionRow()
        self.version_row.set_title(_("Version"))
        self.version_row.set_subtitle(_("Checking..."))
        info_group.add(self.version_row)

        # ── Image Management ──
        image_group = Adw.PreferencesGroup()
        image_group.set_title(_("Build Image"))
        image_group.set_description(CONTAINER_IMAGE)
        image_group.set_margin_top(24)
        self.append(image_group)

        self.image_status_row = Adw.ActionRow()
        self.image_status_row.set_title(_("Image Status"))
        self.image_status_row.set_subtitle(_("Checking..."))
        image_group.add(self.image_status_row)

        # Pull image button
        pull_row = Adw.ActionRow()
        pull_row.set_title(_("Pull Latest Image"))
        pull_row.set_subtitle(_("Download or update the build container image"))
        pull_row.set_activatable(True)

        self.pull_button = Gtk.Button()
        self.pull_button.set_icon_name("emblem-synchronizing-symbolic")
        self.pull_button.set_valign(Gtk.Align.CENTER)
        self.pull_button.set_tooltip_text(_("Pull Image"))
        self.pull_button.add_css_class("suggested-action")
        self.pull_button.connect("clicked", self._on_pull_clicked)
        pull_row.add_suffix(self.pull_button)
        image_group.add(pull_row)

        # ── Maintenance ──
        maint_group = Adw.PreferencesGroup()
        maint_group.set_title(_("Maintenance"))
        maint_group.set_margin_top(24)
        self.append(maint_group)

        # Cleanup containers
        cleanup_row = Adw.ActionRow()
        cleanup_row.set_title(_("Cleanup Old Containers"))
        cleanup_row.set_subtitle(_("Remove stopped build containers"))
        cleanup_btn = Gtk.Button()
        cleanup_btn.set_label(_("Clean"))
        cleanup_btn.set_valign(Gtk.Align.CENTER)
        cleanup_btn.connect("clicked", self._on_cleanup_clicked)
        cleanup_row.add_suffix(cleanup_btn)
        maint_group.add(cleanup_row)

        # Fix storage driver
        self.fix_driver_row = Adw.ActionRow()
        self.fix_driver_row.set_title(_("Fix Storage Driver"))
        self.fix_driver_row.set_subtitle(_("Switch from btrfs to overlay2 (Docker only)"))
        fix_btn = Gtk.Button()
        fix_btn.set_label(_("Fix"))
        fix_btn.set_valign(Gtk.Align.CENTER)
        fix_btn.add_css_class("destructive-action")
        fix_btn.connect("clicked", self._on_fix_driver_clicked)
        self.fix_driver_row.add_suffix(fix_btn)
        maint_group.add(self.fix_driver_row)

        # Pull progress
        self.pull_progress_group = Adw.PreferencesGroup()
        self.pull_progress_group.set_title(_("Pull Progress"))
        self.pull_progress_group.set_margin_top(24)
        self.pull_progress_group.set_visible(False)
        self.append(self.pull_progress_group)

        self.pull_progress_bar = Gtk.ProgressBar()
        self.pull_progress_bar.set_show_text(True)
        self.pull_progress_group.add(self.pull_progress_bar)

        self.pull_log_label = Gtk.Label()
        self.pull_log_label.set_halign(Gtk.Align.START)
        self.pull_log_label.add_css_class("dim-label")
        self.pull_log_label.add_css_class("caption")
        self.pull_log_label.set_wrap(True)
        self.pull_log_label.set_max_width_chars(80)
        self.pull_progress_group.add(self.pull_log_label)

    def refresh(self):
        """Refresh container status"""
        thread = threading.Thread(target=self._refresh_worker, daemon=True)
        thread.start()

    def _refresh_worker(self):
        engine = self.container_mgr.detect_engine()
        version = ""
        driver = ""
        image_info = None

        if engine:
            try:
                r = subprocess.run([engine, "--version"], capture_output=True, text=True, timeout=5, check=False)
                version = r.stdout.strip().split("\n")[0] if r.returncode == 0 else _("Unknown")
            except Exception:
                version = _("Unknown")

            driver = self.container_mgr.get_storage_driver()
            if self.container_mgr.image_exists(CONTAINER_IMAGE):
                image_info = self.container_mgr.get_image_info(CONTAINER_IMAGE)

        GLib.idle_add(self._update_ui, engine, version, driver, image_info)

    def _update_ui(self, engine, version, driver, image_info):
        if engine:
            self.engine_row.set_subtitle(engine.capitalize())
            self.version_row.set_subtitle(version)
        else:
            self.engine_row.set_subtitle(_("Not found"))
            self.version_row.set_subtitle(_("N/A"))

        if driver:
            self.driver_row.set_subtitle(driver)
            if driver == "btrfs":
                self.driver_row.add_css_class("error")
                self.fix_driver_row.set_visible(True)
            else:
                self.fix_driver_row.set_visible(engine == "docker")
        else:
            self.driver_row.set_subtitle(_("N/A"))

        if image_info:
            size_gb = image_info.get("size_gb", 0)
            self.image_status_row.set_subtitle(
                _("Available ({0:.1f} GB) - {1}").format(size_gb, image_info.get("created", "?")[:10])
            )
        else:
            self.image_status_row.set_subtitle(_("Not downloaded"))

        return False

    def _on_pull_clicked(self, button):
        """Start pulling container image"""
        self.pull_button.set_sensitive(False)
        self.pull_progress_group.set_visible(True)
        self.pull_progress_bar.set_fraction(0.0)
        self.pull_progress_bar.set_text(_("Starting download..."))

        thread = threading.Thread(target=self._pull_worker, daemon=True)
        thread.start()

    def _pull_worker(self):
        def progress_callback(line):
            GLib.idle_add(self._update_pull_progress, line)

        success = self.container_mgr.pull_image(CONTAINER_IMAGE, progress_callback)
        GLib.idle_add(self._pull_completed, success)

    def _update_pull_progress(self, line):
        self.pull_log_label.set_text(line)
        self.pull_progress_bar.pulse()
        return False

    def _pull_completed(self, success):
        self.pull_button.set_sensitive(True)
        if success:
            self.pull_progress_bar.set_fraction(1.0)
            self.pull_progress_bar.set_text(_("Image pulled successfully"))
        else:
            self.pull_progress_bar.set_text(_("Pull failed"))
        self.refresh()
        return False

    def _on_cleanup_clicked(self, button):
        thread = threading.Thread(target=self._cleanup_worker, daemon=True)
        thread.start()

    def _cleanup_worker(self):
        self.container_mgr.cleanup_old_containers(CONTAINER_IMAGE)
        GLib.idle_add(self.refresh)

    def _on_fix_driver_clicked(self, button):
        """Fix Docker storage driver (btrfs → overlay2)"""
        dialog = Adw.AlertDialog(
            heading=_("Switch to overlay2?"),
            body=_("This will stop Docker, remove all Docker data, and restart with overlay2. All images and containers will be lost. Continue?"),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("fix", _("Switch to overlay2"))
        dialog.set_response_appearance("fix", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_fix_confirmed)
        dialog.present(self.get_root())

    def _on_fix_confirmed(self, dialog, response):
        if response == "fix":
            thread = threading.Thread(target=self._fix_driver_worker, daemon=True)
            thread.start()

    def _fix_driver_worker(self):
        """Run storage driver fix in background"""
        from core.iso_builder import ISOBuilder

        builder = ISOBuilder(
            {"container_engine": "docker"},
            callbacks={"on_log": lambda c, m: GLib.idle_add(self.logger.log, c, m)},
        )
        success = builder._check_and_fix_storage()
        GLib.idle_add(self.refresh)
