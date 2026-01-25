#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/dialogs/progress_dialog.py - Progress dialog for long operations
#

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject, GLib
from core.translation_utils import _
import threading
import time

class ProgressDialog(Adw.Window):
    """Dialog for showing progress of long-running operations"""
    
    __gsignals__ = {
        'operation-completed': (GObject.SignalFlags.RUN_FIRST, None, (bool, object)),  # success, result
        'operation-cancelled': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }
    
    def __init__(self, parent, title, message="", cancellable=True):
        super().__init__(
            transient_for=parent,
            modal=True
        )
        
        self.set_title(title)
        self.set_default_size(660, 480)
        self.set_resizable(False)  # Fixed size - terminal log uses scrollbar
        
        self.operation_title = title
        self.operation_message = message
        self.cancellable = cancellable
        self.operation_thread = None
        self.operation_function = None
        self.operation_args = ()
        self.operation_kwargs = {}
        self.result = None
        self.error = None
        self.cancelled = False
        self._pulse_timeout_id = None
        
        self.create_ui()
    
    def create_ui(self):
        """Create dialog UI"""
        
        # Main box with toolbar view
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)
        
        # Header bar
        header_bar = Adw.HeaderBar()
        header_bar.set_show_end_title_buttons(False)
        header_bar.set_show_start_title_buttons(False)
        toolbar_view.add_top_bar(header_bar)
        
        # Content box
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_top(24)
        content_box.set_margin_bottom(24)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)
        toolbar_view.set_content(content_box)
        
        # Title label
        title_label = Gtk.Label()
        title_label.set_text(self.operation_title)
        title_label.add_css_class("title-2")
        content_box.append(title_label)
        
        # Message label
        if self.operation_message:
            message_label = Gtk.Label()
            message_label.set_text(self.operation_message)
            message_label.add_css_class("dim-label")
            message_label.set_wrap(True)
            content_box.append(message_label)
        
        # Spinner + Progress area
        progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        progress_box.set_margin_top(12)
        progress_box.set_vexpand(False)
        
        # Spinner (visible during indeterminate progress)
        self.spinner = Gtk.Spinner()
        self.spinner.set_size_request(32, 32)
        self.spinner.set_halign(Gtk.Align.CENTER)
        progress_box.append(self.spinner)
        
        # Current step label - ABOVE progress bar
        self.status_label = Gtk.Label()
        self.status_label.set_text(_("Initializing..."))
        self.status_label.add_css_class("title-4")
        self.status_label.set_wrap(True)
        self.status_label.set_halign(Gtk.Align.CENTER)
        self.status_label.set_margin_top(8)
        progress_box.append(self.status_label)
        
        # Progress bar - in the middle
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(True)
        self.progress_bar.set_text(_("Starting..."))
        self.progress_bar.set_margin_top(8)
        progress_box.append(self.progress_bar)
        
        # Substatus label - below progress bar
        self.substatus_label = Gtk.Label()
        self.substatus_label.set_text("")
        self.substatus_label.add_css_class("dim-label")
        self.substatus_label.add_css_class("caption")
        self.substatus_label.set_wrap(True)
        self.substatus_label.set_halign(Gtk.Align.CENTER)
        progress_box.append(self.substatus_label)
        
        content_box.append(progress_box)
        
        # Terminal log - COLLAPSED by default (dropdown)
        details_expander = Gtk.Expander()
        details_expander.set_label(_("Terminal Log"))
        details_expander.set_margin_top(16)
        details_expander.set_expanded(False)  # Start collapsed
        
        # Scrolled window for terminal-style log
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(150)
        scrolled.set_max_content_height(250)
        
        # Details text view (terminal style)
        self.details_buffer = Gtk.TextBuffer()
        self.details_view = Gtk.TextView()
        self.details_view.set_buffer(self.details_buffer)
        self.details_view.set_editable(False)
        self.details_view.set_monospace(True)
        self.details_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.details_view.set_left_margin(8)
        self.details_view.set_right_margin(8)
        self.details_view.set_top_margin(8)
        self.details_view.set_bottom_margin(8)
        self.details_view.add_css_class("card")
        
        scrolled.set_child(self.details_view)
        details_expander.set_child(scrolled)
        content_box.append(details_expander)
        
        # Cancel button (if cancellable)
        if self.cancellable:
            button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            button_box.set_halign(Gtk.Align.CENTER)
            button_box.set_margin_top(12)
            
            self.cancel_button = Gtk.Button()
            self.cancel_button.set_label(_("Cancel"))
            self.cancel_button.add_css_class("destructive-action")
            self.cancel_button.connect('clicked', self.on_cancel_clicked)
            button_box.append(self.cancel_button)
            
            content_box.append(button_box)
        
        # Start with indeterminate progress
        self.set_progress_mode(indeterminate=True)
    
    def set_progress_mode(self, indeterminate=False):
        """Set progress bar mode"""
        if indeterminate:
            self.spinner.start()
            self.progress_bar.pulse()
            # Keep pulsing with a timer
            self._pulse_timeout_id = GLib.timeout_add(100, self._pulse_progress)
        else:
            self.spinner.stop()
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
            self.progress_bar.set_fraction(min(1.0, max(0.0, fraction)))
            if text:
                self.progress_bar.set_text(text)
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
        
        # Color mappings
        colors = {
            "cyan": "#00CED1",
            "green": "#32CD32", 
            "red": "#FF6B6B",
            "yellow": "#FFD93D",
            "white": "#FFFFFF",
            "dim": "#888888",
            "blue": "#4A90D9",
            "purple": "#B19CD9",
            "orange": "#FFA500",
        }
        
        for name, color in colors.items():
            tag = Gtk.TextTag.new(name)
            tag.set_property("foreground", color)
            tag_table.add(tag)
        
        # Bold tag
        bold_tag = Gtk.TextTag.new("bold")
        bold_tag.set_property("weight", 700)
        tag_table.add(bold_tag)
        
        self._tags_initialized = True
    
    def append_detail(self, text, style=None):
        """Append text to details with optional color (thread-safe)"""
        def update():
            # Initialize tags if needed
            if not hasattr(self, '_tags_initialized') or not self._tags_initialized:
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
        self.operation_thread = threading.Thread(
            target=self._operation_worker,
            daemon=True
        )
        self.operation_thread.start()
        
        # Show dialog
        self.present()
    
    def _operation_worker(self):
        """Worker thread for the operation"""
        try:
            result = self.operation_function(*self.operation_args, **self.operation_kwargs)
            self.result = result
            
            # Check if result is explicitly False (operation failed)
            # Operations that return False indicate failure without exception
            if result is False:
                GLib.idle_add(lambda: self._complete_operation(False, _("Operation returned failure status")))
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
        # Stop progress animation
        if self._pulse_timeout_id:
            GLib.source_remove(self._pulse_timeout_id)
            self._pulse_timeout_id = None
        self.spinner.stop()
        self.spinner.set_visible(False)
        
        # Update progress bar
        if success:
            self.progress_bar.set_fraction(1.0)
            self.progress_bar.set_text(_("Completed"))
            self.status_label.set_text(_("✓ Operation completed successfully"))
            self.status_label.remove_css_class("title-4")
            self.status_label.add_css_class("success")
        else:
            self.progress_bar.set_text(_("Failed"))
            self.status_label.set_text(_("✗ Operation failed: {0}").format(str(result)))
            self.status_label.remove_css_class("title-4")
            self.status_label.add_css_class("error")
        
        # Add "Open in GitHub" button if this was a build operation
        if success and hasattr(self, 'details_buffer'):
            # Extract GitHub Actions URL from terminal log
            github_url = self._extract_github_url()
            if github_url:
                self._add_github_button(github_url)
        
        # Change cancel button to "Done" button
        if hasattr(self, 'cancel_button'):
            self.cancel_button.set_label(_("Done"))
            self.cancel_button.remove_css_class("destructive-action")
            if success:
                self.cancel_button.add_css_class("suggested-action")
            else:
                self.cancel_button.add_css_class("destructive-action")
            
            # Disconnect old handler and connect close handler
            self.cancel_button.disconnect_by_func(self.on_cancel_clicked)
            self.cancel_button.connect('clicked', self.on_done_clicked)
        
        # Store result for later access
        self._operation_success = success
        self._operation_result = result
        
        return False
    
    def _extract_github_url(self):
        """Extract GitHub Actions URL from terminal log"""
        import re
        start_iter = self.details_buffer.get_start_iter()
        end_iter = self.details_buffer.get_end_iter()
        text = self.details_buffer.get_text(start_iter, end_iter, False)
        
        # Look for GitHub Actions URL pattern
        pattern = r'https://github\.com/[^/]+/[^/]+/actions'
        match = re.search(pattern, text)
        if match:
            return match.group(0)
        return None
    
    def _add_github_button(self, url):
        """Add 'Open in GitHub' button"""
        import subprocess
        
        # Create button box if it doesn't exist
        github_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        github_box.set_halign(Gtk.Align.CENTER)
        github_box.set_margin_top(12)
        
        # Create the button with icon
        github_button = Gtk.Button()
        github_button.set_label(_("Open in GitHub"))
        github_button.add_css_class("pill")
        
        # Add icon
        icon = Gtk.Image.new_from_icon_name("web-browser-symbolic")
        github_button.set_child(
            self._create_button_content(icon, _("Open in GitHub"))
        )
        
        def on_github_clicked(button):
            try:
                subprocess.Popen(["xdg-open", url])
            except Exception:
                pass
        
        github_button.connect('clicked', on_github_clicked)
        github_box.append(github_button)
        
        # Insert before the button box
        # Get the content box (parent of cancel_button's parent)
        if hasattr(self, 'cancel_button'):
            button_parent = self.cancel_button.get_parent()
            if button_parent:
                content = button_parent.get_parent()
                if content:
                    # Find index of button_parent
                    child = content.get_first_child()
                    index = 0
                    while child:
                        if child == button_parent:
                            break
                        child = child.get_next_sibling()
                        index += 1
                    # Insert github box before button box
                    content.insert_child_after(github_box, button_parent.get_prev_sibling())
    
    def _create_button_content(self, icon, label_text):
        """Create button content with icon and label"""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_halign(Gtk.Align.CENTER)
        box.append(icon)
        label = Gtk.Label(label=label_text)
        box.append(label)
        return box
    
    def on_done_clicked(self, button):
        """Handle done button click after operation completes"""
        # Emit signal then close
        self.emit('operation-completed', self._operation_success, self._operation_result)
        self.close()
    
    def on_cancel_clicked(self, button):
        """Handle cancel button click"""
        self.cancelled = True
        self.emit('operation-cancelled')
        self.close()


class SimpleProgressDialog(Adw.MessageDialog):
    """Simpler progress dialog for quick operations"""
    
    def __init__(self, parent, title, message=""):
        super().__init__(
            transient_for=parent,
            modal=True
        )
        
        self.set_heading(title)
        self.set_body(message)
        
        # Simple progress bar
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_margin_top(12)
        self.progress_bar.set_margin_bottom(12)
        self.progress_bar.set_margin_start(12)
        self.progress_bar.set_margin_end(12)
        
        self._pulse_timeout_id = None
        
        # Start pulsing
        self.progress_bar.pulse()
        self._pulse_timeout_id = GLib.timeout_add(100, self._pulse_progress)
    
    def _pulse_progress(self):
        """Pulse progress bar"""
        if self.get_visible():
            self.progress_bar.pulse()
            return True
        return False
    
    def close(self):
        """Override close to cleanup timer"""
        if self._pulse_timeout_id:
            GLib.source_remove(self._pulse_timeout_id)
            self._pulse_timeout_id = None
        super().close()


class OperationRunner:
    """Helper class to run operations with progress dialog"""
    
    def __init__(self, parent_window):
        self.parent = parent_window
        self.current_dialog = None
    
    def run_with_progress(self, operation_func, title, message="", 
                         cancellable=True, *args, **kwargs):
        """Run operation with progress dialog"""
        
        dialog = ProgressDialog(self.parent, title, message, cancellable)
        self.current_dialog = dialog
        
        # Connect logger to dialog so log messages go there
        if hasattr(self.parent, 'build_package') and hasattr(self.parent.build_package, 'logger'):
            self.parent.build_package.logger.set_progress_dialog(dialog)
        
        def on_completed(dialog, success, result):
            # Disconnect logger
            if hasattr(self.parent, 'build_package') and hasattr(self.parent.build_package, 'logger'):
                self.parent.build_package.logger.clear_progress_dialog()
            
            self.current_dialog = None
            # Small delay before closing to show final status
            GLib.timeout_add(800, lambda: self._finish_operation(dialog, success, result))
        
        def on_cancelled(dialog):
            # Disconnect logger
            if hasattr(self.parent, 'build_package') and hasattr(self.parent.build_package, 'logger'):
                self.parent.build_package.logger.clear_progress_dialog()
            
            self.current_dialog = None
            dialog.close()
            self._on_operation_cancelled()
        
        dialog.connect('operation-completed', on_completed)
        dialog.connect('operation-cancelled', on_cancelled)
        
        # Setup progress callbacks if operation supports them
        if hasattr(operation_func, '__self__'):  # Bound method
            obj = operation_func.__self__
            if hasattr(obj, 'set_progress_callback'):
                obj.set_progress_callback(dialog.set_progress)
            if hasattr(obj, 'set_status_callback'):
                obj.set_status_callback(dialog.set_status)
        
        dialog.run_operation(operation_func, *args, **kwargs)
        
        return dialog
    
    def _finish_operation(self, dialog, success, result):
        """Finish operation and close dialog"""
        dialog.close()
        
        if success:
            self._on_operation_success(result)
        else:
            self._on_operation_error(result)
        
        return False  # Don't repeat timeout
    
    def _on_operation_success(self, _result):
        """Handle successful operation"""
        if self.parent:
            # Show success toast
            self.parent.show_toast(_("Operation completed successfully"))
            
            # Send system notification if window is not focused
            if not self.parent.is_active():
                if hasattr(self.parent, 'send_system_notification'):
                    self.parent.send_system_notification(
                        _("Build Package"),
                        _("Operation completed successfully"),
                        "emblem-ok-symbolic"
                    )
            
            # Refresh all widgets
            if hasattr(self.parent, 'refresh_all_widgets'):
                self.parent.refresh_all_widgets()
    
    def _on_operation_error(self, error):
        """Handle operation error"""
        if self.parent:
            toast = Adw.Toast.new(_("Operation failed: {0}").format(str(error)))
            toast.set_timeout(5)
            if hasattr(self.parent, 'toast_overlay'):
                self.parent.toast_overlay.add_toast(toast)
            
            # Send system notification if window is not focused
            if not self.parent.is_active():
                if hasattr(self.parent, 'send_system_notification'):
                    self.parent.send_system_notification(
                        _("Build Package"),
                        _("Operation failed: {0}").format(str(error)),
                        "dialog-error-symbolic"
                    )
    
    def _on_operation_cancelled(self):
        """Handle operation cancellation"""
        if self.parent:
            toast = Adw.Toast.new(_("Operation cancelled"))
            toast.set_timeout(3)
            if hasattr(self.parent, 'toast_overlay'):
                self.parent.toast_overlay.add_toast(toast)