#
# gui/dialogs/progress_dialog.py - Progress dialog for long operations
#

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import threading

from gitrepo.common.desktop_launch import open_uri
from gitrepo.common.translation import _
from gitrepo.common.diagnostic_redaction import redact_diagnostic
from gitrepo.common.terminal_palette import apply_log_palette, log_palette
from gi.repository import Adw, Gdk, GLib, GObject, Gtk


class ProgressDialog(Adw.Window):
    """Dialog for showing progress of long-running operations"""

    __gsignals__ = {
        "operation-completed": (GObject.SignalFlags.RUN_FIRST, None, (bool, object)),  # success, result
        "operation-cancelled": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, parent, title, message="", cancellable=False, auto_advance=False):
        super().__init__(transient_for=parent, modal=True)

        self.set_title(_("Operation Progress"))
        self.set_default_size(680, 520)
        self.set_resizable(True)

        self.operation_title = title
        self.operation_message = message
        self.cancellable = cancellable
        self.auto_advance = auto_advance
        self.operation_thread = None
        self.operation_function = None
        self.operation_args = ()
        self.operation_kwargs = {}
        self.result = None
        self.error = None
        self.cancelled = False
        self._operation_running = False
        self._pulse_timeout_id = None
        self._style_manager = Adw.StyleManager.get_default()
        self._style_handler = 0

        self.create_ui()
        self.connect("close-request", self._on_close_request)

    def _on_close_request(self, _window) -> bool:
        """Refuse to close while the operation is still running.

        Returning False let a compositor close (Alt+F4 -- the titlebar buttons
        are hidden, so it is the only way out) destroy the window while git and
        GitHub work continued. The log and the result went with it, and because
        operation-completed never fired, OperationRunner._busy stayed True: every
        later action was refused with "One operation at a time" until the process
        was restarted.
        """
        if self._operation_running:
            self._report_still_running()
            return True
        if self._style_handler:
            self._style_manager.disconnect(self._style_handler)
            self._style_handler = 0
        return False

    def _report_still_running(self) -> None:
        """Say why the window will not close, and what the user can do."""
        dialog = Adw.AlertDialog(
            heading=_("The operation is still running"),
            body=_("“{0}” has to finish before this window can be closed.").format(self.operation_title),
        )
        dialog.add_response("close", _("Keep waiting"))
        dialog.present(self)

    def create_ui(self):
        """Create dialog UI"""

        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        header_bar = Adw.HeaderBar()
        header_bar.set_show_end_title_buttons(False)
        header_bar.set_show_start_title_buttons(False)
        header_bar.set_title_widget(
            Adw.WindowTitle(title=self.operation_title, subtitle=self.operation_message or _("Running"))
        )
        toolbar_view.add_top_bar(header_bar)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        content_box.set_margin_top(16)
        content_box.set_margin_bottom(16)
        content_box.set_margin_start(20)
        content_box.set_margin_end(20)
        toolbar_view.set_content(content_box)

        content_box.append(self._create_status_card())
        content_box.append(self._create_log_card())
        toolbar_view.add_bottom_bar(self._create_action_bar())

        # Start with indeterminate progress
        self.set_progress_mode(indeterminate=True)

    def _create_status_card(self) -> Gtk.Widget:
        """Build the headline card describing what the operation is doing."""
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.add_css_class("build-package-progress-card")

        headline = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)

        self.spinner = Gtk.Spinner()
        self.spinner.set_size_request(24, 24)
        self.spinner.set_valign(Gtk.Align.CENTER)
        self.spinner.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        headline.append(self.spinner)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)
        self.status_label = Gtk.Label(label=_("Initializing..."), xalign=0)
        self.status_label.add_css_class("build-package-progress-status")
        self.status_label.set_wrap(True)
        self.status_label.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        self.status_label.set_width_chars(1)
        text_box.append(self.status_label)

        self.substatus_label = Gtk.Label(label="", xalign=0)
        self.substatus_label.add_css_class("dim-label")
        self.substatus_label.add_css_class("caption")
        self.substatus_label.set_wrap(True)
        self.substatus_label.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        self.substatus_label.set_width_chars(1)
        text_box.append(self.substatus_label)
        headline.append(text_box)
        card.append(headline)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(False)
        self.progress_bar.add_css_class("build-package-progress-bar")
        self.progress_bar.set_accessible_role(Gtk.AccessibleRole.PROGRESS_BAR)
        self.progress_bar.update_property([Gtk.AccessibleProperty.LABEL], [_("Operation progress")])
        card.append(self.progress_bar)
        return card

    def _create_log_card(self) -> Gtk.Widget:
        """Build the terminal log surface with its own copy action."""
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        card.add_css_class("build-package-log-card")
        card.set_vexpand(True)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.add_css_class("build-package-log-header")
        title = Gtk.Label(label=_("Terminal Log"), xalign=0)
        title.add_css_class("heading")
        title.set_hexpand(True)
        header.append(title)

        copy_button = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        copy_button.add_css_class("flat")
        copy_button.set_tooltip_text(_("Copy the whole terminal log to the clipboard"))
        copy_button.update_property([Gtk.AccessibleProperty.LABEL], [_("Copy Log")])
        copy_button.connect("clicked", self.on_copy_log_clicked)
        header.append(copy_button)
        card.append(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(180)
        scrolled.set_vexpand(True)

        self.details_buffer = Gtk.TextBuffer()
        self.details_view = Gtk.TextView()
        self.details_view.set_buffer(self.details_buffer)
        self.details_view.set_editable(False)
        self.details_view.set_cursor_visible(False)
        self.details_view.set_monospace(True)
        self.details_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.details_view.set_left_margin(14)
        self.details_view.set_right_margin(14)
        self.details_view.set_top_margin(6)
        self.details_view.set_bottom_margin(12)
        self.details_view.add_css_class("build-package-log-view")
        self.details_view.update_property([Gtk.AccessibleProperty.LABEL], [_("Terminal Log")])

        scrolled.set_child(self.details_view)
        card.append(scrolled)
        return card

    def _create_action_bar(self) -> Gtk.Widget:
        """Build the bottom action area; a running step offers only Cancel."""
        action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        action_bar.add_css_class("build-package-action-bar")
        action_bar.set_halign(Gtk.Align.END)

        self.cancel_button = Gtk.Button()
        if self.cancellable:
            self.cancel_button.set_label(_("Cancel"))
            self.cancel_button.add_css_class("destructive-action")
            self.cancel_button.connect("clicked", self.on_cancel_clicked)
        else:
            # A non-cancellable step has no decision to offer yet, so the button
            # stays out of the way instead of posing as a disabled action.
            self.cancel_button.set_label(_("Close"))
            self.cancel_button.set_visible(False)
        action_bar.append(self.cancel_button)
        return action_bar

    def on_copy_log_clicked(self, _button):
        """Copy the terminal log so a failure can be reported verbatim."""
        display = Gdk.Display.get_default()
        if display is None:
            return
        text = self.details_buffer.get_text(
            self.details_buffer.get_start_iter(), self.details_buffer.get_end_iter(), False
        )
        display.get_clipboard().set(text)

    def set_progress_mode(self, indeterminate=False):
        """Set progress bar mode"""
        if indeterminate:
            self.spinner.start()
            self.progress_bar.pulse()
            # Keep pulsing with a timer
            self._pulse_timeout_id = GLib.timeout_add(100, self._pulse_progress)
        else:
            self.spinner.stop()
            self.spinner.set_visible(False)
            if self._pulse_timeout_id:
                GLib.source_remove(self._pulse_timeout_id)
                self._pulse_timeout_id = None
            self.progress_bar.set_fraction(0.0)

    def _pulse_progress(self):
        """Pulse progress bar for indeterminate progress"""
        if self.get_visible() and not self.cancelled:
            self.progress_bar.pulse()
            return True  # Continue timer
        return False  # Stop timer

    def set_progress(self, fraction, text=None):
        """Set progress bar value (thread-safe)"""

        def update():
            if self._pulse_timeout_id:
                GLib.source_remove(self._pulse_timeout_id)
                self._pulse_timeout_id = None
            self.spinner.stop()
            self.spinner.set_visible(False)
            self.progress_bar.set_fraction(min(1.0, max(0.0, fraction)))
            if text:
                self.substatus_label.set_text(text)
            return False

        GLib.idle_add(update)

    def set_status(self, text):
        """Set status text (thread-safe)"""

        def update():
            self.status_label.set_text(text)
            return False

        GLib.idle_add(update)

    def _setup_text_tags(self):
        """Setup color tags for terminal log"""
        tag_table = self.details_buffer.get_tag_table()

        for name in log_palette(False):
            if tag_table.lookup(name):
                continue
            tag = Gtk.TextTag.new(name)
            if name in {"red", "yellow", "orange"}:
                tag.set_property("weight", 700)
            if name == "dim":
                tag.set_property("scale", 0.9)
            tag_table.add(tag)

        # Bold tag
        if not tag_table.lookup("bold"):
            bold_tag = Gtk.TextTag.new("bold")
            bold_tag.set_property("weight", 700)
            tag_table.add(bold_tag)

        self._tags_initialized = True
        self._apply_log_palette()
        self._style_handler = self._style_manager.connect("notify::dark", lambda *_args: self._apply_log_palette())

    def _apply_log_palette(self):
        """Repaint the log tags for the active light or dark colour scheme."""
        apply_log_palette(self.details_buffer, self._style_manager.get_dark())

    def append_detail(self, text, style=None):
        """Append text to details with optional color (thread-safe)"""
        text = redact_diagnostic(text)

        def update():
            # Initialize tags if needed
            if not hasattr(self, "_tags_initialized") or not self._tags_initialized:
                self._setup_text_tags()

            end_iter = self.details_buffer.get_end_iter()

            if style and self.details_buffer.get_tag_table().lookup(style):
                # Insert with tag
                start_mark = self.details_buffer.create_mark(None, end_iter, True)
                self.details_buffer.insert(end_iter, text + "\n")
                start_iter = self.details_buffer.get_iter_at_mark(start_mark)
                end_iter = self.details_buffer.get_end_iter()
                self.details_buffer.apply_tag_by_name(style, start_iter, end_iter)
                self.details_buffer.delete_mark(start_mark)
            else:
                self.details_buffer.insert(end_iter, text + "\n")

            # Auto-scroll to bottom
            excess = self.details_buffer.get_char_count() - 200_000
            if excess > 0:
                self.details_buffer.delete(
                    self.details_buffer.get_start_iter(), self.details_buffer.get_iter_at_offset(excess)
                )
            end_iter = self.details_buffer.get_end_iter()
            self.details_view.scroll_to_iter(end_iter, 0.0, False, 0.0, 1.0)
            return False

        GLib.idle_add(update)

    def run_operation(self, operation_func, *args, **kwargs):
        """Run operation in background thread"""
        self.operation_function = operation_func
        self.operation_args = args
        self.operation_kwargs = kwargs

        # Start operation thread
        self._operation_running = True
        self.operation_thread = threading.Thread(target=self._operation_worker, daemon=True)
        self.operation_thread.start()

        # Show dialog
        self.present()

    def _operation_worker(self):
        """Worker thread for the operation"""
        try:
            result = self.operation_function(*self.operation_args, **self.operation_kwargs)
            self.result = result

            # Check for failure conditions:
            # 1. Explicit False
            # 2. Empty dict {} (many operations return {} on failure)
            # 3. None when it shouldn't be
            operation_failed = False

            if result is False:
                operation_failed = True
            elif isinstance(result, dict) and len(result) == 0:
                # Empty dict typically means failure in our APIs
                operation_failed = True

            if operation_failed:
                GLib.idle_add(
                    lambda: self._complete_operation(
                        False, _("The operation did not complete. The log below states the cause and what to do next.")
                    )
                )
            else:
                # Signal completion on main thread (capture result by default arg)
                GLib.idle_add(lambda r=result: self._complete_operation(True, r))

        except Exception as ex:
            self.error = ex
            error_msg = str(ex)

            # Signal completion with error on main thread (capture by default arg)
            GLib.idle_add(lambda err=error_msg: self._complete_operation(False, err))

    def _complete_operation(self, success, result):
        """Complete operation on main thread"""
        # The window may be closed from here on: nothing is running behind it.
        self._operation_running = False
        # Stop progress animation
        if self._pulse_timeout_id:
            GLib.source_remove(self._pulse_timeout_id)
            self._pulse_timeout_id = None
        self.spinner.stop()
        self.spinner.set_visible(False)

        # Update progress bar
        if success:
            self.progress_bar.set_fraction(1.0)
            self.substatus_label.set_text(_("Completed"))
            self.status_label.set_text(_("Operation completed successfully"))
            self.status_label.add_css_class("success")
        else:
            self.substatus_label.set_text(_("Failed"))
            self.status_label.set_text(_("Operation failed: {0}").format(str(result)))
            self.status_label.add_css_class("error")

        # Add "Open in GitHub" button if this was a build operation
        if success and hasattr(self, "details_buffer"):
            # Extract GitHub Actions URL from terminal log
            github_url = self._extract_github_url()
            if github_url:
                self._add_github_button(github_url)

        # Change cancel button to "Done" button
        if hasattr(self, "cancel_button"):
            self.cancel_button.set_sensitive(True)
            self.cancel_button.set_visible(True)
            self.cancel_button.set_label(_("Done"))
            self.cancel_button.remove_css_class("destructive-action")
            self.cancel_button.add_css_class("suggested-action")

            # Disconnect old handler and connect close handler
            if self.cancellable:
                self.cancel_button.disconnect_by_func(self.on_cancel_clicked)
            self.cancel_button.connect("clicked", self.on_done_clicked)

        # Store result for later access
        self._operation_success = success
        self._operation_result = result
        if success and self.auto_advance:
            self.cancel_button.set_visible(False)
            self.emit("operation-completed", success, result)

        return False

    def _extract_github_url(self):
        """Extract GitHub Actions URL from terminal log"""
        import re

        start_iter = self.details_buffer.get_start_iter()
        end_iter = self.details_buffer.get_end_iter()
        text = self.details_buffer.get_text(start_iter, end_iter, False)

        # Look for GitHub Actions URL pattern
        pattern = r"https://github\.com/[^/]+/[^/]+/actions"
        match = re.search(pattern, text)
        if match:
            return match.group(0)
        return None

    def _add_github_button(self, url):
        """Add 'Open in GitHub' button"""
        # Create button box if it doesn't exist
        github_button = Gtk.Button()
        github_button.set_label(_("Open in GitHub"))
        github_button.add_css_class("suggested-action")

        def on_github_clicked(button):
            open_uri(button, url)

        github_button.connect("clicked", on_github_clicked)

        action_bar = self.cancel_button.get_parent()
        if action_bar is not None:
            self.cancel_button.remove_css_class("suggested-action")
            action_bar.append(github_button)

    def on_done_clicked(self, button):
        """Handle done button click after operation completes"""
        # Emit signal then close
        self.emit("operation-completed", self._operation_success, self._operation_result)
        self.close()

    def on_cancel_clicked(self, button):
        """Handle cancel button click"""
        self.cancelled = True
        self.emit("operation-cancelled")
        self.close()


class OperationRunner:
    """Helper class to run operations with progress dialog"""

    def __init__(self, parent_window):
        self.parent = parent_window
        self.current_dialog = None
        self._completion_callback = None
        self._busy = False

    def _refuse_second_operation(self, title: str) -> None:
        """Say why a second operation is not starting, and where the first is."""
        dialog = Adw.AlertDialog(
            heading=_("One operation at a time"),
            body=_("“{0}” cannot start while another operation is still running.").format(title),
        )
        dialog.add_response("close", _("Close"))
        dialog.present(self.parent)

    def run_with_progress(
        self, operation_func, title, message="", cancellable=False, completion_callback=None, *args, **kwargs
    ):
        """Run operation with progress dialog.

        *completion_callback* receives the operation result once it succeeds, so
        a caller can present what the operation produced.
        """
        # A repository journey spans several Git commands. Letting a second one
        # start would interleave them and route its log into the wrong dialog.
        if self._busy:
            self._refuse_second_operation(title)
            return None
        self._busy = True
        self._completion_callback = completion_callback

        dialog = ProgressDialog(self.parent, title, message, cancellable, auto_advance=completion_callback is not None)
        self.current_dialog = dialog

        # Connect logger to dialog so log messages go there
        if hasattr(self.parent, "build_package") and hasattr(self.parent.build_package, "logger"):
            self.parent.build_package.logger.set_progress_dialog(dialog)

        def on_completed(dialog, success, result):
            # Disconnect logger
            if hasattr(self.parent, "build_package") and hasattr(self.parent.build_package, "logger"):
                self.parent.build_package.logger.clear_progress_dialog()

            self.current_dialog = None
            # Small delay before closing to show final status
            GLib.timeout_add(800, lambda: self._finish_operation(dialog, success, result))

        def on_cancelled(dialog):
            # Disconnect logger
            if hasattr(self.parent, "build_package") and hasattr(self.parent.build_package, "logger"):
                self.parent.build_package.logger.clear_progress_dialog()

            self.current_dialog = None
            dialog.close()
            self._on_operation_cancelled()

        dialog.connect("operation-completed", on_completed)
        dialog.connect("operation-cancelled", on_cancelled)

        # Setup progress callbacks if operation supports them
        if hasattr(operation_func, "__self__"):  # Bound method
            obj = operation_func.__self__
            if hasattr(obj, "set_progress_callback"):
                obj.set_progress_callback(dialog.set_progress)
            if hasattr(obj, "set_status_callback"):
                obj.set_status_callback(dialog.set_status)

        dialog.run_operation(operation_func, *args, **kwargs)

        return dialog

    def _finish_operation(self, dialog, success, result):
        """Finish operation and close dialog"""
        dialog.close()
        self._busy = False

        if success:
            self._on_operation_success(result)
        else:
            self._on_operation_error(self._partial_outcome() or result)

        return False  # Don't repeat timeout

    def _partial_outcome(self) -> str:
        """Describe what an incomplete journey did leave behind, if anything.

        A journey that created a local commit or branch and then failed to
        publish it must not read as "nothing happened"; the recoverable part
        is exactly what the user needs to know about.
        """
        build_package = getattr(self.parent, "build_package", None)
        details = getattr(build_package, "last_operation_details", None) or {}
        if not details.get("remote_unchanged"):
            return ""
        if build_package is not None:
            build_package.last_operation_details = {}
        if details.get("local_commit_created"):
            kept = _("The commit {0} exists locally on {1}.").format(
                details["local_commit_created"][:12], details.get("current_branch", "")
            )
        elif details.get("local_branch_created"):
            kept = _("The branch {0} exists locally.").format(details["local_branch_created"])
        else:
            kept = _("The local part of this operation was kept.")
        return _("{0}\nThe remote was not changed. Retry with: {1}").format(kept, details.get("retry_command", ""))

    def _on_operation_success(self, result):
        """Handle successful operation"""
        callback = getattr(self, "_completion_callback", None)
        continues_to_review = callback is not None
        if callback:
            self._completion_callback = None
            callback(result)
        if self.parent:
            if not continues_to_review:
                self.parent.show_toast(_("Operation completed successfully"))

            if not continues_to_review and not self.parent.is_active():
                if hasattr(self.parent, "send_system_notification"):
                    self.parent.send_system_notification(
                        _("Build Package"), _("Operation completed successfully"), "emblem-ok-symbolic"
                    )

            # Refresh all widgets
            if hasattr(self.parent, "refresh_all_widgets"):
                self.parent.refresh_all_widgets()

    def _on_operation_error(self, error):
        """Notify about a failure already acknowledged in the progress dialog."""
        if self.parent:
            # Send system notification if window is not focused
            if not self.parent.is_active():
                if hasattr(self.parent, "send_system_notification"):
                    self.parent.send_system_notification(
                        _("Build Package"), _("Operation failed: {0}").format(str(error)), "dialog-error-symbolic"
                    )

    def _on_operation_cancelled(self):
        """Handle operation cancellation"""
        self._busy = False
        if self.parent:
            toast = Adw.Toast.new(_("Operation cancelled"))
            toast.set_timeout(3)
            if hasattr(self.parent, "toast_overlay"):
                self.parent.toast_overlay.add_toast(toast)
