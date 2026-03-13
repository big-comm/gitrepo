#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/dialogs/progress_dialog.py - Build progress dialog
#

import re
import threading
import time

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from core.iso_builder import ISOBuilder
from core.translation_utils import _
from gi.repository import Adw, GLib, GObject, Gtk


class BuildProgressDialog(Adw.Window):
    """Dialog showing real-time build progress with terminal log"""

    __gsignals__ = {
        'build-completed': (GObject.SignalFlags.RUN_FIRST, None, (bool, str, str)),  # success, iso_path, error_msg
    }

    def __init__(self, parent, config, logger):
        super().__init__(
            transient_for=parent,
            modal=True,
        )

        self.config = config
        self.logger = logger
        self.builder = None
        self._start_time = 0
        self._timer_id = None
        self._tags_initialized = False

        distro = config.get("distroname", "?")
        edition = config.get("edition", "?")

        self.set_title(_("Building {0} - {1}").format(distro, edition))
        self.set_default_size(750, 600)
        self.set_resizable(True)

        self._create_ui()

    def _create_ui(self):
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.set_show_start_title_buttons(False)

        # Maximize toggle button
        maximize_btn = Gtk.Button()
        maximize_btn.set_icon_name("view-fullscreen-symbolic")
        maximize_btn.set_tooltip_text(_("Maximize"))
        maximize_btn.connect("clicked", self._on_toggle_maximize)
        header.pack_end(maximize_btn)

        toolbar_view.add_top_bar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        toolbar_view.set_content(content)

        # Title
        title = Gtk.Label()
        distro = self.config.get("distroname", "?")
        edition = self.config.get("edition", "?")
        title.set_markup(f"<b>{_('Building ISO')}</b>: {distro} - {edition}")
        title.add_css_class("title-2")
        content.append(title)

        # Phase label
        self.phase_label = Gtk.Label()
        self.phase_label.set_text(_("Initializing..."))
        self.phase_label.add_css_class("title-4")
        self.phase_label.set_halign(Gtk.Align.CENTER)
        self.phase_label.set_margin_top(8)
        content.append(self.phase_label)

        # Progress bar
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(True)
        self.progress_bar.set_text(_("Starting..."))
        self.progress_bar.set_margin_top(8)
        content.append(self.progress_bar)

        # Time info
        time_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        time_box.set_halign(Gtk.Align.CENTER)
        time_box.set_margin_top(4)

        self.elapsed_label = Gtk.Label()
        self.elapsed_label.set_text(_("Elapsed: 00:00"))
        self.elapsed_label.add_css_class("dim-label")
        time_box.append(self.elapsed_label)

        content.append(time_box)

        # Terminal log (expanded by default for build)
        log_expander = Gtk.Expander()
        log_expander.set_label(_("Terminal Log"))
        log_expander.set_expanded(True)
        log_expander.set_margin_top(16)
        log_expander.set_vexpand(True)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(200)
        scrolled.set_vexpand(True)

        self.log_buffer = Gtk.TextBuffer()
        self.log_view = Gtk.TextView()
        self.log_view.set_buffer(self.log_buffer)
        self.log_view.set_editable(False)
        self.log_view.set_monospace(True)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.log_view.set_left_margin(8)
        self.log_view.set_right_margin(8)
        self.log_view.set_top_margin(8)
        self.log_view.set_bottom_margin(8)
        self.log_view.add_css_class("card")

        scrolled.set_child(self.log_view)
        log_expander.set_child(scrolled)
        content.append(log_expander)

        # Buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_top(12)

        self.cancel_button = Gtk.Button()
        self.cancel_button.set_label(_("Cancel Build"))
        self.cancel_button.add_css_class("destructive-action")
        self.cancel_button.connect("clicked", self._on_cancel_clicked)
        button_box.append(self.cancel_button)

        content.append(button_box)

    def _setup_text_tags(self):
        tag_table = self.log_buffer.get_tag_table()
        colors = {
            "cyan": "#00CED1", "green": "#32CD32", "red": "#FF6B6B",
            "yellow": "#FFD93D", "white": "#CCCCCC", "dim": "#888888",
            "blue": "#4A90D9", "magenta": "#C678DD", "bold-white": "#FFFFFF",
        }
        for name, color in colors.items():
            if not tag_table.lookup(name):
                tag = Gtk.TextTag.new(name)
                tag.set_property("foreground", color)
                if name.startswith("bold"):
                    tag.set_property("weight", 700)
                tag_table.add(tag)

        # Bold tag
        if not tag_table.lookup("bold"):
            tag = Gtk.TextTag.new("bold")
            tag.set_property("weight", 700)
            tag_table.add(tag)

        self._tags_initialized = True

    def _on_toggle_maximize(self, button):
        if self.is_maximized():
            self.unmaximize()
        else:
            self.maximize()

    # Regex to split text on ANSI escape sequences
    _ANSI_SPLIT_RE = re.compile(r'(\x1b\[[0-9;]*m)')

    # Map 256-color codes to tag names
    _COLOR_256_MAP = {
        33: "yellow", 39: "blue", 45: "cyan", 41: "cyan",
        196: "red", 160: "red", 124: "red",
        46: "green", 40: "green", 34: "green", 82: "green",
        226: "yellow", 220: "yellow", 214: "yellow",
        208: "yellow", 202: "yellow",
        69: "blue", 75: "blue", 63: "blue",
        51: "cyan", 87: "cyan", 123: "cyan",
        213: "magenta", 177: "magenta", 141: "magenta",
        231: "bold-white", 255: "white", 254: "white",
        97: "magenta",
    }

    # Map basic ANSI colors (30-37) to tag names
    _COLOR_BASIC_MAP = {
        30: "dim", 31: "red", 32: "green", 33: "yellow",
        34: "blue", 35: "magenta", 36: "cyan", 37: "white",
        90: "dim", 91: "red", 92: "green", 93: "yellow",
        94: "blue", 95: "magenta", 96: "cyan", 97: "bold-white",
    }

    def _ansi_to_tag(self, code_str):
        """Convert ANSI escape code to GTK TextBuffer tag name"""
        # Parse the numeric params from \x1b[...m
        params = [int(p) for p in code_str[2:-1].split(';') if p.isdigit()]
        if not params or params == [0]:
            return None  # reset

        tag = None
        i = 0
        while i < len(params):
            p = params[i]
            if p == 38 and i + 2 < len(params) and params[i + 1] == 5:
                # 256-color: \x1b[38;5;Nm
                color_num = params[i + 2]
                tag = self._COLOR_256_MAP.get(color_num, "white")
                i += 3
            elif 30 <= p <= 37 or 90 <= p <= 97:
                tag = self._COLOR_BASIC_MAP.get(p, "white")
                i += 1
            elif p == 1:
                # Bold - use bold-white or combine later
                if not tag:
                    tag = "bold-white"
                i += 1
            else:
                i += 1
        return tag

    def _append_log(self, color, message):
        """Append text to terminal log, parsing ANSI codes for colors"""
        if not self._tags_initialized:
            self._setup_text_tags()

        # Check if message contains ANSI codes
        if '\x1b[' in message:
            parts = self._ANSI_SPLIT_RE.split(message)
            current_tag = color if color != "white" else None

            for part in parts:
                if not part:
                    continue
                if part.startswith('\x1b['):
                    parsed = self._ansi_to_tag(part)
                    current_tag = parsed  # None means reset
                else:
                    end_iter = self.log_buffer.get_end_iter()
                    tag_name = current_tag or "white"
                    if self.log_buffer.get_tag_table().lookup(tag_name):
                        start_mark = self.log_buffer.create_mark(None, end_iter, True)
                        self.log_buffer.insert(end_iter, part)
                        start_iter = self.log_buffer.get_iter_at_mark(start_mark)
                        end_iter = self.log_buffer.get_end_iter()
                        self.log_buffer.apply_tag_by_name(tag_name, start_iter, end_iter)
                        self.log_buffer.delete_mark(start_mark)
                    else:
                        self.log_buffer.insert(end_iter, part)

            # Add newline
            end_iter = self.log_buffer.get_end_iter()
            self.log_buffer.insert(end_iter, "\n")
        else:
            # No ANSI codes - use the specified color
            end_iter = self.log_buffer.get_end_iter()
            tag_name = color if color in ("cyan", "green", "red", "yellow", "white", "dim", "blue", "magenta", "bold-white") else None

            if tag_name and self.log_buffer.get_tag_table().lookup(tag_name):
                start_mark = self.log_buffer.create_mark(None, end_iter, True)
                self.log_buffer.insert(end_iter, message + "\n")
                start_iter = self.log_buffer.get_iter_at_mark(start_mark)
                end_iter = self.log_buffer.get_end_iter()
                self.log_buffer.apply_tag_by_name(tag_name, start_iter, end_iter)
                self.log_buffer.delete_mark(start_mark)
            else:
                self.log_buffer.insert(end_iter, message + "\n")

        # Auto-scroll
        end_iter = self.log_buffer.get_end_iter()
        self.log_view.scroll_to_iter(end_iter, 0.0, False, 0.0, 1.0)
        return False

    def start_build(self):
        """Start the ISO build"""
        self._start_time = time.time()

        # Timer for elapsed time
        self._timer_id = GLib.timeout_add(1000, self._update_elapsed)

        # Create ISOBuilder with GUI callbacks
        callbacks = {
            "on_log": lambda color, msg: GLib.idle_add(self._append_log, color, msg),
            "on_progress": lambda frac, text: GLib.idle_add(self._update_progress, frac, text),
            "on_phase": lambda name: GLib.idle_add(self._update_phase, name),
        }
        self.builder = ISOBuilder(self.config, callbacks)

        # Start build in background thread
        thread = threading.Thread(target=self._build_worker, daemon=True)
        thread.start()

        self.present()

    def _build_worker(self):
        result = self.builder.execute()
        GLib.idle_add(self._on_build_finished, result)

    def _update_progress(self, fraction, text):
        self.progress_bar.set_fraction(min(1.0, max(0.0, fraction)))
        if text:
            self.progress_bar.set_text(text)
        return False

    def _update_phase(self, phase_name):
        phase_labels = {
            "check_engine": _("Checking container engine..."),
            "check_storage": _("Checking storage driver..."),
            "pull_image": _("Pulling container image..."),
            "prepare_dirs": _("Preparing directories..."),
            "clone_build_repo": _("Cloning build repository..."),
            "container_build": _("Building ISO in container..."),
            "move_files": _("Moving ISO files..."),
            "cleanup": _("Cleaning up..."),
        }
        label = phase_labels.get(phase_name, phase_name)
        self.phase_label.set_text(label)
        return False

    def _update_elapsed(self):
        if self._start_time:
            elapsed = int(time.time() - self._start_time)
            mins = elapsed // 60
            secs = elapsed % 60
            self.elapsed_label.set_text(_("Elapsed: {0:02d}:{1:02d}").format(mins, secs))
        return True  # Keep timer running

    def _on_build_finished(self, result):
        # Stop timer
        if self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = None

        success = result.get("success", False)
        iso_path = result.get("iso_path", "")
        error_msg = result.get("error", "")
        duration = result.get("duration", 0)

        # Update UI
        if success:
            self.progress_bar.set_fraction(1.0)
            self.progress_bar.set_text(_("Completed"))
            self.phase_label.set_text(_("Build completed successfully!"))
            self.phase_label.add_css_class("success")
        else:
            self.progress_bar.set_text(_("Failed"))
            self.phase_label.set_text(_("Build failed: {0}").format(error_msg))
            self.phase_label.add_css_class("error")

        # Change cancel to close
        self.cancel_button.set_label(_("Close"))
        self.cancel_button.remove_css_class("destructive-action")
        if success:
            self.cancel_button.add_css_class("suggested-action")

            # Add "Open Folder" button if ISO exists
            if iso_path:
                import os
                open_btn = Gtk.Button()
                open_btn.set_label(_("Open ISO Folder"))
                open_btn.add_css_class("suggested-action")
                open_btn.connect("clicked", lambda b: self._open_folder(os.path.dirname(iso_path)))
                parent_box = self.cancel_button.get_parent()
                if parent_box:
                    parent_box.append(open_btn)

        self.cancel_button.disconnect_by_func(self._on_cancel_clicked)
        self.cancel_button.connect("clicked", self._on_close_clicked)

        # Save to history
        from datetime import datetime
        from gui.widgets.history_widget import HistoryWidget
        HistoryWidget.add_entry({
            "distro": self.config.get("distroname", "?"),
            "edition": self.config.get("edition", "?"),
            "kernel": self.config.get("kernel", "?"),
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "success": success,
            "iso_path": iso_path,
            "duration": duration,
            "error": error_msg,
        })

        # Emit signal
        self.emit("build-completed", success, iso_path, error_msg)
        return False

    def _on_cancel_clicked(self, button):
        """Cancel the build"""
        dialog = Adw.AlertDialog(
            heading=_("Cancel Build?"),
            body=_("The current build will be terminated. Any progress will be lost."),
        )
        dialog.add_response("continue", _("Continue Building"))
        dialog.add_response("cancel", _("Cancel Build"))
        dialog.set_response_appearance("cancel", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_cancel_confirmed)
        dialog.present(self)

    def _on_cancel_confirmed(self, dialog, response):
        if response == "cancel" and self.builder:
            self.builder.cancel()
            self.phase_label.set_text(_("Cancelling..."))

    def _on_close_clicked(self, button):
        self.close()

    def _open_folder(self, path):
        import subprocess
        subprocess.Popen(["xdg-open", path])
