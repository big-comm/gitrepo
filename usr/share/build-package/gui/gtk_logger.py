#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/gtk_logger.py - GTK Logger implementation for GUI interface
#

import os
import sys
from datetime import datetime

from core.translation_utils import _
from core.config import APP_NAME, APP_DESC, LOG_DIR_BASE

class GTKLogger:
    """Logger implementation for GTK4 GUI interface"""
    
    def __init__(self, main_window):
        self.main_window = main_window
        self.log_file = None
        self.use_colors = True  # GUI always supports "colors" via styling
        self.progress_dialog = None  # When set, log messages go here
        
    def set_progress_dialog(self, dialog):
        """Set active progress dialog to receive log messages"""
        self.progress_dialog = dialog
        
    def clear_progress_dialog(self):
        """Clear active progress dialog"""
        self.progress_dialog = None
        
    def setup_log_file(self, get_repo_name_func):
        """Sets up the log file"""
        repo_name = get_repo_name_func()
        if repo_name:
            log_dir = os.path.join(LOG_DIR_BASE, repo_name)
            os.makedirs(log_dir, exist_ok=True)
            self.log_file = os.path.join(log_dir, f"{APP_NAME}.log")
    
    def log(self, style: str, message: str):
        """Displays message in GUI and saves to log"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # If progress dialog is active, send messages there with color
        if self.progress_dialog:
            # Update status and append to details with style for coloring
            self.progress_dialog.set_status(message)
            self.progress_dialog.append_detail(message, style=style)
            # Print to console for debugging
            print("[{0}] {1}".format(style.upper(), message))
        else:
            # Map styles to toast types and terminal output
            style_map = {
                "cyan": "info",
                "blue_dark": "info", 
                "medium_blue": "info",
                "light_blue": "info",
                "white": "info",
                "red": "error",
                "yellow": "warning",
                "green": "success",
                "orange": "warning",
                "purple": "info",
                "black": "info",
                "bold": "info"
            }
            
            toast_type = style_map.get(style, "info")
            
            # Show message in GUI
            if toast_type == "error":
                self.main_window.show_error_toast(message)
            elif toast_type == "warning":
                self.main_window.show_info_toast(message)
            elif toast_type == "success":
                self.main_window.show_toast(message)
            else:
                self.main_window.show_info_toast(message)
            
            # Also print to console for debugging
            print("[{0}] {1}".format(style.upper(), message))
        
        # Save to log file (without colors)
        if self.log_file:
            with open(self.log_file, 'a') as f:
                f.write(f"[{timestamp}] [{style.upper()}] {message}\n")
    
    def die(self, style: str, message: str, exit_code: int = 1):
        """Displays error message in GUI and exits"""
        error_msg = f"{_('ERROR')}: {message}"
        
        # Also show in console for debugging
        print("[FATAL] {0}".format(error_msg))
        
        if self.progress_dialog:
            # When ProgressDialog is active, route through it instead of showing
            # toasts behind the dialog (which causes visual clutter)
            self.progress_dialog.set_status(error_msg)
            self.progress_dialog.append_detail(error_msg, style="red")
        else:
            # No ProgressDialog - show toast and fatal dialog as usual
            self.main_window.show_error_toast(error_msg)
            # Show modal dialog for fatal errors
            self._show_fatal_error_dialog(error_msg, exit_code)
    
    def draw_app_header(self):
        """For GUI, this updates the window title instead of drawing terminal header"""
        # Set window title
        self.main_window.set_title(APP_NAME)
        # Subtitle removed - now shown in Welcome dialog only
    
    def display_summary(self, title: str, data: list):
        """Display summary information in GUI format"""
        summary_text = f"{title}:\n"
        for key, value in data:
            summary_text += f"• {key}: {value}\n"
        
        # Show in console for debugging
        print("=== {0} ===".format(title))
        for key, value in data:
            print(f"{key}: {value}")
        
        if self.progress_dialog:
            # When ProgressDialog is active, send summary to embedded terminal
            self.progress_dialog.append_detail("", style="cyan")
            self.progress_dialog.append_detail(f"═══ {title} ═══", style="cyan")
            for key, value in data:
                self.progress_dialog.append_detail(f"  {key}: {value}", style="white")
            self.progress_dialog.append_detail("", style="cyan")
        else:
            # Show notification only when no dialog is active
            self.main_window.show_info_toast(_("Summary: {0}").format(title))
    
    def format_branch_name(self, branch_name: str) -> str:
        """Format branch names for display (GUI doesn't need markup)"""
        # Return plain text since GUI will handle styling differently
        return branch_name
    
    def _show_fatal_error_dialog(self, message: str, exit_code: int):
        """Show fatal error dialog and handle application exit"""
        try:
            import gi
            gi.require_version('Gtk', '4.0')
            gi.require_version('Adw', '1')
            from gi.repository import Gtk, Adw
            
            # Create error dialog
            dialog = Adw.MessageDialog.new(
                self.main_window,
                _("Fatal Error"),
                message
            )
            dialog.add_response("ok", _("OK"))
            dialog.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.set_default_response("ok")
            
            def on_response(dialog, response):
                if response == "ok":
                    dialog.close()
                    # Exit application
                    self.main_window.get_application().quit()
            
            dialog.connect("response", on_response)
            dialog.present()
            
        except Exception as e:
            # Fallback to console exit if dialog fails
            print(_("Dialog error: {0}").format(e))
            print(_("Fatal error: {0}").format(message))
            sys.exit(exit_code)