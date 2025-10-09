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

class ProgressDialog(Adw.MessageDialog):
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
        
        self.set_heading(title)
        self.set_body(message)
        
        self.cancellable = cancellable
        self.operation_thread = None
        self.operation_function = None
        self.operation_args = ()
        self.operation_kwargs = {}
        self.result = None
        self.error = None
        self.cancelled = False
        
        self.create_ui()
    
    def create_ui(self):
        """Create dialog UI"""
        
        # Progress bar
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_margin_top(12)
        self.progress_bar.set_margin_bottom(12)
        self.progress_bar.set_margin_start(12)
        self.progress_bar.set_margin_end(12)
        self.progress_bar.set_show_text(True)
        
        # Status label
        self.status_label = Gtk.Label()
        self.status_label.set_text(_("Preparing..."))
        self.status_label.set_margin_bottom(12)
        self.status_label.set_margin_start(12)
        self.status_label.set_margin_end(12)
        self.status_label.add_css_class("caption")
        
        # Details expander
        self.details_expander = Adw.ExpanderRow()
        self.details_expander.set_title(_("Details"))
        self.details_expander.set_margin_start(12)
        self.details_expander.set_margin_end(12)
        self.details_expander.set_margin_bottom(12)
        
        # Details text view
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_size_request(400, 150)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        
        self.details_buffer = Gtk.TextBuffer()
        self.details_view = Gtk.TextView()
        self.details_view.set_buffer(self.details_buffer)
        self.details_view.set_editable(False)
        self.details_view.add_css_class("monospace")
        
        scrolled.set_child(self.details_view)
        self.details_expander.add_row(Adw.PreferencesRow())
        
        # Add widgets to dialog (this is tricky with MessageDialog)
        # We'll use a custom approach
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content_box.append(self.progress_bar)
        content_box.append(self.status_label)
        content_box.append(self.details_expander)
        content_box.append(scrolled)
        
        # Add cancel button if cancellable
        if self.cancellable:
            self.add_response("cancel", _("Cancel"))
            self.set_response_appearance("cancel", Adw.ResponseAppearance.DESTRUCTIVE)
            self.connect("response", self.on_response)
        
        # Start with indeterminate progress
        self.set_progress_mode(indeterminate=True)
    
    def set_progress_mode(self, indeterminate=False):
        """Set progress bar mode"""
        if indeterminate:
            self.progress_bar.pulse()
            # Keep pulsing with a timer
            GLib.timeout_add(100, self.pulse_progress)
        else:
            self.progress_bar.set_fraction(0.0)
    
    def pulse_progress(self):
        """Pulse progress bar for indeterminate progress"""
        if self.get_visible() and not self.cancelled:
            self.progress_bar.pulse()
            return True  # Continue timer
        return False  # Stop timer
    
    def set_progress(self, fraction, text=None):
        """Set progress bar value"""
        def update():
            self.progress_bar.set_fraction(fraction)
            if text:
                self.progress_bar.set_text(text)
        
        GLib.idle_add(update)
    
    def set_status(self, text):
        """Set status text"""
        GLib.idle_add(lambda: self.status_label.set_text(text))
    
    def append_detail(self, text):
        """Append text to details"""
        def update():
            end_iter = self.details_buffer.get_end_iter()
            self.details_buffer.insert(end_iter, text + "\n")
            
            # Auto-scroll to bottom
            mark = self.details_buffer.get_insert()
            self.details_view.scroll_mark_onscreen(mark)
        
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
            self.result = self.operation_function(*self.operation_args, **self.operation_kwargs)
            
            # Signal completion on main thread
            GLib.idle_add(lambda: self.emit('operation-completed', True, self.result))
            
        except Exception as e:
            self.error = e
            
            # Signal completion with error on main thread  
            GLib.idle_add(lambda err=e: self.emit('operation-completed', False, err))
    
    def on_response(self, dialog, response_id):
        """Handle dialog response"""
        if response_id == "cancel":
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
        
        # Start pulsing
        self.progress_bar.pulse()
        GLib.timeout_add(100, self.pulse_progress)
    
    def pulse_progress(self):
        """Pulse progress bar"""
        if self.get_visible():
            self.progress_bar.pulse()
            return True
        return False

class OperationRunner:
    """Helper class to run operations with progress dialog"""
    
    def __init__(self, parent_window):
        self.parent = parent_window
    
    def run_with_progress(self, operation_func, title, message="", 
                         cancellable=True, *args, **kwargs):
        """Run operation with progress dialog"""
        
        dialog = ProgressDialog(self.parent, title, message, cancellable)
        
        def on_completed(dialog, success, result):
            dialog.close()
            if success:
                self.on_operation_success(result)
            else:
                self.on_operation_error(result)
        
        def on_cancelled(dialog):
            dialog.close()
            self.on_operation_cancelled()
        
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
    
    def on_operation_success(self, result):
        """Override in subclass to handle success"""
        pass
    
    def on_operation_error(self, error):
        """Override in subclass to handle error"""
        if self.parent:
            toast = Adw.Toast.new(_("Operation failed: {0}").format(str(error)))
            toast.set_timeout(5)
            # Show error toast if parent has toast overlay
            if hasattr(self.parent, 'toast_overlay'):
                self.parent.toast_overlay.add_toast(toast)
    
    def on_operation_cancelled(self):
        """Override in subclass to handle cancellation"""
        if self.parent:
            toast = Adw.Toast.new(_("Operation cancelled"))
            toast.set_timeout(3)
            if hasattr(self.parent, 'toast_overlay'):
                self.parent.toast_overlay.add_toast(toast)