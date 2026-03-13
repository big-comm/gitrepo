#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/widgets/dashboard_widget.py - Dashboard/overview widget
#

import os
import shutil
import subprocess
import threading

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from core.config import CONTAINER_IMAGE, DEFAULT_OUTPUT_DIR
from core.translation_utils import _
from gi.repository import Adw, GLib, GObject, Gtk


class DashboardWidget(Gtk.Box):
    """Dashboard with status cards and quick actions"""

    __gtype_name__ = "DashboardWidget"

    __gsignals__ = {
        'navigate-to': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'start-build': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, settings, logger):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.settings = settings
        self.logger = logger

        self.set_margin_start(24)
        self.set_margin_end(24)
        self.set_margin_top(12)
        self.set_margin_bottom(24)

        self._create_ui()
        GLib.idle_add(self.refresh)

    def _create_ui(self):
        """Create dashboard UI"""

        # ── Status Cards ──
        status_group = Adw.PreferencesGroup()
        status_group.set_title(_("System Status"))
        status_group.set_description(_("Current environment status"))
        self.append(status_group)

        # Container engine status
        self.engine_row = Adw.ActionRow()
        self.engine_row.set_title(_("Container Engine"))
        self.engine_row.set_subtitle(_("Checking..."))
        self.engine_icon = Gtk.Image.new_from_icon_name("system-run-symbolic")
        self.engine_row.add_prefix(self.engine_icon)
        self.engine_status = Gtk.Image.new_from_icon_name("emblem-synchronizing-symbolic")
        self.engine_status.set_valign(Gtk.Align.CENTER)
        self.engine_row.add_suffix(self.engine_status)
        status_group.add(self.engine_row)

        # Container image status
        self.image_row = Adw.ActionRow()
        self.image_row.set_title(_("Build Image"))
        self.image_row.set_subtitle(CONTAINER_IMAGE)
        image_icon = Gtk.Image.new_from_icon_name("drive-harddisk-symbolic")
        self.image_row.add_prefix(image_icon)
        self.image_status = Gtk.Image.new_from_icon_name("emblem-synchronizing-symbolic")
        self.image_status.set_valign(Gtk.Align.CENTER)
        self.image_row.add_suffix(self.image_status)
        status_group.add(self.image_row)

        # Disk space
        self.disk_row = Adw.ActionRow()
        self.disk_row.set_title(_("Disk Space"))
        self.disk_row.set_subtitle(_("Checking..."))
        disk_icon = Gtk.Image.new_from_icon_name("drive-harddisk-symbolic")
        self.disk_row.add_prefix(disk_icon)
        self.disk_status = Gtk.Image.new_from_icon_name("emblem-synchronizing-symbolic")
        self.disk_status.set_valign(Gtk.Align.CENTER)
        self.disk_row.add_suffix(self.disk_status)
        status_group.add(self.disk_row)

        # ── Quick Actions ──
        actions_group = Adw.PreferencesGroup()
        actions_group.set_title(_("Quick Actions"))
        actions_group.set_margin_top(24)
        self.append(actions_group)

        # Build ISO action
        build_row = Adw.ActionRow()
        build_row.set_title(_("Build ISO"))
        build_row.set_subtitle(_("Configure and start a new ISO build"))
        build_row.set_activatable(True)
        build_icon = Gtk.Image.new_from_icon_name("media-optical-symbolic")
        build_row.add_prefix(build_icon)
        arrow1 = Gtk.Image.new_from_icon_name("go-next-symbolic")
        arrow1.set_valign(Gtk.Align.CENTER)
        build_row.add_suffix(arrow1)
        build_row.connect("activated", lambda r: self.emit("navigate-to", "build"))
        actions_group.add(build_row)

        # Container management action
        container_row = Adw.ActionRow()
        container_row.set_title(_("Manage Container"))
        container_row.set_subtitle(_("Pull images, check storage, manage engine"))
        container_row.set_activatable(True)
        container_icon = Gtk.Image.new_from_icon_name("system-run-symbolic")
        container_row.add_prefix(container_icon)
        arrow2 = Gtk.Image.new_from_icon_name("go-next-symbolic")
        arrow2.set_valign(Gtk.Align.CENTER)
        container_row.add_suffix(arrow2)
        container_row.connect("activated", lambda r: self.emit("navigate-to", "container"))
        actions_group.add(container_row)

        # View history action
        history_row = Adw.ActionRow()
        history_row.set_title(_("Build History"))
        history_row.set_subtitle(_("View previous builds and results"))
        history_row.set_activatable(True)
        history_icon = Gtk.Image.new_from_icon_name("document-open-recent-symbolic")
        history_row.add_prefix(history_icon)
        arrow3 = Gtk.Image.new_from_icon_name("go-next-symbolic")
        arrow3.set_valign(Gtk.Align.CENTER)
        history_row.add_suffix(arrow3)
        history_row.connect("activated", lambda r: self.emit("navigate-to", "history"))
        actions_group.add(history_row)

        # ── Recent Build ──
        self.recent_group = Adw.PreferencesGroup()
        self.recent_group.set_title(_("Last Build"))
        self.recent_group.set_margin_top(24)
        self.append(self.recent_group)

        self.last_build_row = Adw.ActionRow()
        self.last_build_row.set_title(_("No builds yet"))
        self.last_build_row.set_subtitle(_("Start your first build from the Build ISO page"))
        self.recent_group.add(self.last_build_row)

    def refresh(self):
        """Refresh all status cards"""
        thread = threading.Thread(target=self._refresh_worker, daemon=True)
        thread.start()

    def _refresh_worker(self):
        """Worker thread to gather system status"""
        # Check container engine
        engine = "none"
        engine_version = ""
        for eng in ["docker", "podman"]:
            try:
                result = subprocess.run(
                    [eng, "--version"], capture_output=True, text=True, timeout=5, check=False,
                )
                if result.returncode == 0:
                    engine = eng
                    engine_version = result.stdout.strip().split("\n")[0]
                    break
            except Exception:
                continue

        # Check image
        image_exists = False
        if engine != "none":
            try:
                result = subprocess.run(
                    [engine, "image", "inspect", CONTAINER_IMAGE],
                    capture_output=True, text=True, timeout=10, check=False,
                )
                image_exists = result.returncode == 0
            except Exception:
                pass

        # Check disk space
        output_dir = self.settings.output_dir
        free_gb = 0
        total_gb = 0
        # Check output dir or nearest existing parent for disk space
        check_dir = output_dir
        while check_dir and not os.path.exists(check_dir):
            check_dir = os.path.dirname(check_dir)
        if check_dir:
            usage = shutil.disk_usage(check_dir)
            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)

        dir_exists = os.path.exists(output_dir)

        # Update UI on main thread
        GLib.idle_add(self._update_status, engine, engine_version, image_exists, free_gb, total_gb, dir_exists)

    def _update_status(self, engine, engine_version, image_exists, free_gb, total_gb, dir_exists):
        """Update status cards on main thread"""
        # Engine
        if engine != "none":
            self.engine_row.set_subtitle(engine_version)
            self.engine_status.set_from_icon_name("emblem-ok-symbolic")
            self.engine_status.add_css_class("status-ok")
        else:
            self.engine_row.set_subtitle(_("No container engine found"))
            self.engine_status.set_from_icon_name("dialog-error-symbolic")
            self.engine_status.add_css_class("status-error")

        # Image
        if image_exists:
            self.image_row.set_subtitle(_("{0} (available)").format(CONTAINER_IMAGE))
            self.image_status.set_from_icon_name("emblem-ok-symbolic")
            self.image_status.add_css_class("status-ok")
        else:
            self.image_row.set_subtitle(_("{0} (not downloaded)").format(CONTAINER_IMAGE))
            self.image_status.set_from_icon_name("dialog-warning-symbolic")
            self.image_status.add_css_class("status-warning")

        # Disk
        if total_gb > 0:
            subtitle = _("{0:.1f} GB free of {1:.1f} GB").format(free_gb, total_gb)
            if not dir_exists:
                subtitle += " " + _("(directory will be created)")
            self.disk_row.set_subtitle(subtitle)
            if free_gb >= 20:
                self.disk_status.set_from_icon_name("emblem-ok-symbolic")
                self.disk_status.add_css_class("status-ok")
            else:
                self.disk_status.set_from_icon_name("dialog-warning-symbolic")
                self.disk_status.add_css_class("status-warning")
        else:
            self.disk_row.set_subtitle(_("Output directory not accessible"))
            self.disk_status.set_from_icon_name("dialog-error-symbolic")
            self.disk_status.add_css_class("status-error")

        # Last build from history
        self._update_last_build()
        return False

    def _update_last_build(self):
        """Update last build info from history"""
        try:
            from core.config import HISTORY_FILE
            if os.path.exists(HISTORY_FILE):
                import json
                with open(HISTORY_FILE, "r") as f:
                    history = json.load(f)
                if history:
                    last = history[-1]
                    self.last_build_row.set_title(
                        f"{last.get('distro', '?')} - {last.get('edition', '?')}"
                    )
                    status = _("Success") if last.get("success") else _("Failed")
                    self.last_build_row.set_subtitle(
                        f"{last.get('date', '?')} | {status}"
                    )
        except Exception:
            pass
