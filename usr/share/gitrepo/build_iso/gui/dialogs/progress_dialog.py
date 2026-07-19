#
# gui/dialogs/progress_dialog.py - Build progress dialog
#

import re
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gitrepo.build_iso.core.iso_builder import ISOBuilder
from gitrepo.common.translation import _
from gitrepo.common.diagnostic_redaction import redact_diagnostic
from gi.repository import Adw, GLib, GObject, Gtk


def build_step_states(active_index: int, step_count: int, outcome: str | None = None) -> tuple[str, ...]:
    """Return truthful visual states for a running or finished build."""
    if outcome == "succeeded":
        return ("complete",) * step_count
    terminal_state = outcome if outcome in {"failed", "cancelled"} else "active"
    return tuple(
        "complete" if index < active_index else terminal_state if index == active_index else "pending"
        for index in range(step_count)
    )


class BuildStepIndicator(Gtk.Box):
    """Compact visual and semantic state for one build step."""

    _STATE_LABELS = {
        "pending": _("Waiting"),
        "active": _("In progress"),
        "complete": _("Completed"),
        "failed": _("Failed"),
        "cancelled": _("Cancelled"),
    }

    def __init__(self, number: int, total: int, title: str) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._number = number
        self._total = total
        self._title = title
        self.set_halign(Gtk.Align.FILL)
        self.set_accessible_role(Gtk.AccessibleRole.GROUP)
        self.add_css_class("build-step")

        self.marker = Gtk.Label(label=str(number))
        self.marker.set_halign(Gtk.Align.CENTER)
        self.marker.add_css_class("build-step-marker")
        self.append(self.marker)

        title_label = Gtk.Label(label=title)
        title_label.set_justify(Gtk.Justification.CENTER)
        title_label.set_wrap(True)
        title_label.set_max_width_chars(16)
        title_label.add_css_class("caption")
        title_label.add_css_class("build-step-title")
        self.append(title_label)
        self.set_state("pending")

    def set_state(self, state: str) -> None:
        for css_class in ("step-pending", "step-active", "step-complete", "step-failed", "step-cancelled"):
            self.remove_css_class(css_class)
        self.add_css_class(f"step-{state}")
        self.marker.set_text(
            "✓" if state == "complete" else "!" if state in {"failed", "cancelled"} else str(self._number)
        )
        accessible_label = _("Step {0} of {1}: {2} — {3}").format(
            self._number,
            self._total,
            self._title,
            self._STATE_LABELS[state],
        )
        self.update_property([Gtk.AccessibleProperty.LABEL], [accessible_label])


class BuildSubstepIndicator(Gtk.Box):
    """Compact state for one observable part of the Build ISO stage."""

    def __init__(self, number: int, total: int, title: str) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        self._number = number
        self._total = total
        self._title = title
        self.set_halign(Gtk.Align.CENTER)
        self.set_accessible_role(Gtk.AccessibleRole.GROUP)
        self.add_css_class("build-substep")

        self.marker = Gtk.Label(label=str(number))
        self.marker.add_css_class("build-substep-marker")
        self.append(self.marker)

        title_label = Gtk.Label(label=title, xalign=0)
        title_label.set_wrap(True)
        title_label.set_max_width_chars(15)
        title_label.add_css_class("caption")
        title_label.add_css_class("build-substep-title")
        self.append(title_label)
        self.set_state("pending")

    def set_state(self, state: str) -> None:
        for css_class in ("step-pending", "step-active", "step-complete", "step-failed", "step-cancelled"):
            self.remove_css_class(css_class)
        self.add_css_class(f"step-{state}")
        self.marker.set_text(
            "✓" if state == "complete" else "!" if state in {"failed", "cancelled"} else str(self._number)
        )
        accessible_label = _("Build substep {0} of {1}: {2} — {3}").format(
            self._number,
            self._total,
            self._title,
            BuildStepIndicator._STATE_LABELS[state],
        )
        self.update_property([Gtk.AccessibleProperty.LABEL], [accessible_label])


class BuildProgressDialog(Adw.Window):
    """Dialog showing real-time build progress with terminal log"""

    __gsignals__ = {
        "build-completed": (GObject.SignalFlags.RUN_FIRST, None, (bool, str, str)),  # success, iso_path, error_msg
    }

    def __init__(self, parent, config):
        super().__init__(
            transient_for=parent,
            modal=True,
        )

        self.config = config
        self.builder = None
        self._start_time = 0
        self._timer_id = None
        self._tags_initialized = False
        self._live_log_mark = None
        self._active_step_index = None
        self._active_substep_index = None
        self._displayed_fraction = 0.0
        self.step_indicators = []
        self.substep_indicators = []

        self.set_title(_("Build Progress"))
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

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.set_margin_top(12)
        content.set_margin_bottom(16)
        content.set_margin_start(20)
        content.set_margin_end(20)
        toolbar_view.set_content(content)

        distro = self.config.get("distroname", "?")
        edition = self.config.get("edition", "?")
        summary_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        summary_label = Gtk.Label(label=_("{0} • {1}").format(distro, edition), xalign=0)
        summary_label.set_hexpand(True)
        summary_label.add_css_class("heading")
        summary_box.append(summary_label)

        self.elapsed_label = Gtk.Label()
        self.elapsed_label.set_text(_("Elapsed: 00:00"))
        self.elapsed_label.add_css_class("dim-label")
        summary_box.append(self.elapsed_label)
        content.append(summary_box)

        steps = (
            _("Prepare environment"),
            _("Update image"),
            _("Build ISO"),
            _("Publish files"),
            _("Finish"),
        )
        steps_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, homogeneous=True)
        steps_box.add_css_class("build-steps")
        for number, step_title in enumerate(steps, start=1):
            indicator = BuildStepIndicator(number, len(steps), step_title)
            self.step_indicators.append(indicator)
            steps_box.append(indicator)
        content.append(steps_box)

        substeps = (
            _("Prepare profile"),
            _("Install system"),
            _("Prepare boot"),
            _("Compress files"),
            _("Create ISO image"),
        )
        substeps_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, homogeneous=True)
        substeps_box.add_css_class("build-substeps")
        for number, substep_title in enumerate(substeps, start=1):
            indicator = BuildSubstepIndicator(number, len(substeps), substep_title)
            self.substep_indicators.append(indicator)
            substeps_box.append(indicator)
        self.substeps_revealer = Gtk.Revealer(child=substeps_box)
        self.substeps_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        content.append(self.substeps_revealer)

        progress_status = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.status_label = Gtk.Label(label=_("Waiting to start"), xalign=0)
        self.status_label.set_hexpand(True)
        progress_status.append(self.status_label)
        self.step_count_label = Gtk.Label(label=_("Step {0} of {1}").format(0, len(steps)))
        self.step_count_label.add_css_class("dim-label")
        progress_status.append(self.step_count_label)
        content.append(progress_status)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(True)
        self.progress_bar.set_text("0%")
        self.progress_bar.set_accessible_role(Gtk.AccessibleRole.PROGRESS_BAR)
        self.progress_bar.update_property([Gtk.AccessibleProperty.LABEL], [_("Overall build progress")])
        content.append(self.progress_bar)

        # Terminal log (expanded by default for build)
        log_expander = Gtk.Expander()
        log_expander.set_label(_("Terminal Log"))
        log_expander.set_expanded(True)
        log_expander.set_margin_top(4)
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
        self.log_view.update_property([Gtk.AccessibleProperty.LABEL], [_("Terminal Log")])

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
        styles = ("cyan", "green", "red", "yellow", "white", "dim", "blue", "magenta", "bold-white")
        for name in styles:
            if not tag_table.lookup(name):
                tag = Gtk.TextTag.new(name)
                if name in {"red", "yellow", "bold-white"}:
                    tag.set_property("weight", 700)
                if name == "dim":
                    tag.set_property("scale", 0.9)
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
    _ANSI_SPLIT_RE = re.compile(r"(\x1b\[[0-9;]*m)")

    # Map 256-color codes to tag names
    _COLOR_256_MAP = {
        33: "yellow",
        39: "blue",
        45: "cyan",
        41: "cyan",
        196: "red",
        160: "red",
        124: "red",
        46: "green",
        40: "green",
        34: "green",
        82: "green",
        226: "yellow",
        220: "yellow",
        214: "yellow",
        208: "yellow",
        202: "yellow",
        69: "blue",
        75: "blue",
        63: "blue",
        51: "cyan",
        87: "cyan",
        123: "cyan",
        213: "magenta",
        177: "magenta",
        141: "magenta",
        231: "bold-white",
        255: "white",
        254: "white",
        97: "magenta",
    }

    # Map basic ANSI colors (30-37) to tag names
    _COLOR_BASIC_MAP = {
        30: "dim",
        31: "red",
        32: "green",
        33: "yellow",
        34: "blue",
        35: "magenta",
        36: "cyan",
        37: "white",
        90: "dim",
        91: "red",
        92: "green",
        93: "yellow",
        94: "blue",
        95: "magenta",
        96: "cyan",
        97: "bold-white",
    }

    def _ansi_to_tag(self, code_str):
        """Convert ANSI escape code to GTK TextBuffer tag name"""
        # Parse the numeric params from \x1b[...m
        params = [int(p) for p in code_str[2:-1].split(";") if p.isdigit()]
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
        self._clear_live_log()
        message = redact_diagnostic(message)
        if not self._tags_initialized:
            self._setup_text_tags()

        # Check if message contains ANSI codes
        if "\x1b[" in message:
            parts = self._ANSI_SPLIT_RE.split(message)
            current_tag = color if color != "white" else None

            for part in parts:
                if not part:
                    continue
                if part.startswith("\x1b["):
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
            tag_name = (
                color
                if color in ("cyan", "green", "red", "yellow", "white", "dim", "blue", "magenta", "bold-white")
                else None
            )

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
        excess = self.log_buffer.get_char_count() - 200_000
        if excess > 0:
            self.log_buffer.delete(self.log_buffer.get_start_iter(), self.log_buffer.get_iter_at_offset(excess))
        end_iter = self.log_buffer.get_end_iter()
        self.log_view.scroll_to_iter(end_iter, 0.0, False, 0.0, 1.0)
        return False

    def _clear_live_log(self) -> None:
        if not self._live_log_mark:
            return
        start_iter = self.log_buffer.get_iter_at_mark(self._live_log_mark)
        self.log_buffer.delete(start_iter, self.log_buffer.get_end_iter())
        self.log_buffer.delete_mark(self._live_log_mark)
        self._live_log_mark = None

    def _replace_live_log(self, color, message):
        """Replace the unfinished terminal line produced through carriage return."""
        message = redact_diagnostic(message)
        if not self._tags_initialized:
            self._setup_text_tags()
        self._clear_live_log()

        end_iter = self.log_buffer.get_end_iter()
        self._live_log_mark = self.log_buffer.create_mark(None, end_iter, True)
        tag_name = color if self.log_buffer.get_tag_table().lookup(color) else "white"
        self.log_buffer.insert_with_tags_by_name(end_iter, message, tag_name)
        self.log_view.scroll_to_iter(self.log_buffer.get_end_iter(), 0.0, False, 0.0, 1.0)
        return False

    def start_build(self):
        """Start the ISO build"""
        self._start_time = time.time()

        # Timer for elapsed time
        self._timer_id = GLib.timeout_add(1000, self._update_elapsed)

        # Create ISOBuilder with GUI callbacks
        callbacks = {
            "on_log": lambda color, msg: GLib.idle_add(self._append_log, color, msg),
            "on_live_log": lambda color, msg: GLib.idle_add(self._replace_live_log, color, msg),
            "on_progress": lambda frac, text: GLib.idle_add(self._update_progress, frac, text),
            "on_phase": lambda name: GLib.idle_add(self._update_phase, name),
            "on_build_substep": lambda name, fraction: GLib.idle_add(self._update_build_substep, name, fraction),
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
        if fraction is None:
            return False
        bounded_fraction = min(1.0, max(0.0, fraction))
        if bounded_fraction < self._displayed_fraction:
            return False
        self._displayed_fraction = bounded_fraction
        self.progress_bar.set_fraction(bounded_fraction)
        self.progress_bar.set_text(f"{round(bounded_fraction * 100)}%")
        if text and text not in {phase for _step_id, phases in ISOBuilder.BUILD_STEPS for phase in phases}:
            self.status_label.set_text(text)
        return False

    def _update_phase(self, phase_name):
        phase_labels = {
            "check_engine": _("Checking the container engine"),
            "check_storage": _("Checking container storage"),
            "check_space": _("Checking available disk space"),
            "pull_image": _("Updating the build image"),
            "container_build": _("Building and compressing the ISO"),
            "move_files": _("Publishing the ISO and package list"),
            "cleanup": _("Removing temporary build resources"),
        }
        step_index = ISOBuilder.step_index_for_phase(phase_name)
        self._active_step_index = step_index
        self._apply_step_states(step_index)
        self.substeps_revealer.set_reveal_child(phase_name == "container_build")
        if step_index > ISOBuilder.step_index_for_phase("container_build"):
            self._apply_substep_states(len(self.substep_indicators) - 1, "succeeded")
        self.step_count_label.set_text(_("Step {0} of {1}").format(step_index + 1, len(self.step_indicators)))
        self.status_label.set_text(phase_labels[phase_name])
        return False

    def _update_build_substep(self, substep_name: str, _fraction: float):
        labels = {
            "profile": _("Preparing the build profile"),
            "system": _("Installing the system and desktop packages"),
            "boot": _("Preparing kernel and boot files"),
            "compress": _("Compressing system files"),
            "image": _("Creating the bootable ISO image"),
        }
        substep_index = ISOBuilder.BUILD_SUBSTEPS.index(substep_name)
        self._active_substep_index = substep_index
        self._apply_substep_states(substep_index)
        self.step_count_label.set_text(
            _("Step {0} of {1} • substep {2} of {3}").format(
                ISOBuilder.step_index_for_phase("container_build") + 1,
                len(self.step_indicators),
                substep_index + 1,
                len(self.substep_indicators),
            )
        )
        self.status_label.set_text(labels[substep_name])
        return False

    def _apply_step_states(self, active_index: int, outcome: str | None = None) -> None:
        states = build_step_states(active_index, len(self.step_indicators), outcome)
        for indicator, state in zip(self.step_indicators, states, strict=True):
            indicator.set_state(state)

    def _apply_substep_states(self, active_index: int, outcome: str | None = None) -> None:
        states = build_step_states(active_index, len(self.substep_indicators), outcome)
        for indicator, state in zip(self.substep_indicators, states, strict=True):
            indicator.set_state(state)

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
        status = result.get("status", "succeeded" if success else "failed")
        iso_path = result.get("iso_path", "")
        error_msg = result.get("error", "")
        duration = result.get("duration", 0)

        # Update UI
        if success:
            self._active_step_index = len(self.step_indicators) - 1
            self._apply_step_states(self._active_step_index, "succeeded")
            self._apply_substep_states(len(self.substep_indicators) - 1, "succeeded")
            self._displayed_fraction = 1.0
            self.progress_bar.set_fraction(1.0)
            self.progress_bar.set_text("100%")
            self.step_count_label.set_text(
                _("Step {0} of {1}").format(len(self.step_indicators), len(self.step_indicators))
            )
            self.status_label.set_text(_("ISO built and published successfully"))
            self.status_label.add_css_class("success")
        elif status == "cancelled":
            failed_index = self._active_step_index if self._active_step_index is not None else 0
            self._apply_step_states(failed_index, "cancelled")
            if failed_index == ISOBuilder.step_index_for_phase("container_build"):
                substep_index = self._active_substep_index if self._active_substep_index is not None else 0
                self._apply_substep_states(substep_index, "cancelled")
            self.status_label.set_text(_("Build cancelled"))
            self.status_label.add_css_class("warning")
        else:
            failed_index = self._active_step_index if self._active_step_index is not None else 0
            self._apply_step_states(failed_index, "failed")
            if failed_index == ISOBuilder.step_index_for_phase("container_build"):
                substep_index = self._active_substep_index if self._active_substep_index is not None else 0
                self._apply_substep_states(substep_index, "failed")
            self.status_label.set_text(_("Build failed: {0}").format(error_msg))
            self.status_label.add_css_class("error")

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
        from gitrepo.build_iso.gui.widgets.history_widget import HistoryWidget

        HistoryWidget.add_entry(
            {
                "distro": self.config.get("distroname", "?"),
                "edition": self.config.get("edition", "?"),
                "kernel": self.config.get("kernel", "?"),
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "success": success,
                "status": status,
                "iso_path": iso_path,
                "duration": duration,
                "error": error_msg,
            }
        )

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
            self.status_label.set_text(_("Cancelling the current step…"))

    def _on_close_clicked(self, button):
        self.close()

    def _open_folder(self, path):
        from gitrepo.common import child_process as subprocess

        subprocess.Popen(["xdg-open", path])
