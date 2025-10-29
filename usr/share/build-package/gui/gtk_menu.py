#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/gtk_menu.py - GTK Menu system implementation for GUI interface
#

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GLib
from typing import Optional, Tuple, List
from core.translation_utils import _

class GTKMenu:
    """Menu system implementation for GTK4 GUI interface"""
    
    def __init__(self, main_window):
        self.main_window = main_window
        self.current_dialog = None
        self.selected_option = None
        
    def show_menu(self, title: str, options: List[str], default_index: int = 0, additional_content: str = None) -> Optional[Tuple[int, str]]:
        """
        Shows an interactive menu using GTK dialogs.
        
        This method blocks until user makes a selection, similar to CLI version.
        """
        self.selected_option = None
        
        # Create the menu dialog
        dialog = Adw.MessageDialog.new(
            self.main_window,
            title,
            additional_content if additional_content else ""
        )
        
        # Add options as responses
        for i, option in enumerate(options):
            response_id = f"option_{i}"
            dialog.add_response(response_id, option)
            
            # Set default response
            if i == default_index:
                dialog.set_default_response(response_id)
            
            # Style special options
            if _("Exit") in option or _("Back") in option:
                dialog.set_response_appearance(response_id, Adw.ResponseAppearance.DESTRUCTIVE)
            elif "AUR" in option:
                dialog.set_response_appearance(response_id, Adw.ResponseAppearance.SUGGESTED)
        
        # Add cancel option
        dialog.add_response("cancel", _("Cancel"))
        dialog.set_response_appearance("cancel", Adw.ResponseAppearance.DEFAULT)
        
        # Connect response handler
        def on_response(dialog, response_id):
            if response_id == "cancel":
                self.selected_option = None
            elif response_id.startswith("option_"):
                try:
                    index = int(response_id.split("_")[1])
                    self.selected_option = (index, options[index])
                except (IndexError, ValueError):
                    self.selected_option = None
            
            dialog.close()
        
        dialog.connect("response", on_response)
        self.current_dialog = dialog
        
        # Show dialog and wait for response
        dialog.present()
        
        # Run nested event loop to make this synchronous like CLI version
        main_context = GLib.MainContext.default()
        while self.current_dialog and not self.current_dialog.is_destroyed():
            main_context.iteration(True)
        
        self.current_dialog = None
        return self.selected_option
    
    def confirm(self, title: str, message: str = None) -> bool:
        """
        Shows a confirmation dialog.
        
        Returns True if confirmed, False otherwise.
        """
        dialog = Adw.MessageDialog.new(
            self.main_window,
            title,
            message if message else ""
        )
        
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("confirm", _("Confirm"))
        
        dialog.set_response_appearance("cancel", Adw.ResponseAppearance.DEFAULT)
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("confirm")
        
        result = False
        
        def on_response(dialog, response_id):
            nonlocal result
            result = (response_id == "confirm")
            dialog.close()
        
        dialog.connect("response", on_response)
        dialog.present()
        
        # Wait for response
        main_context = GLib.MainContext.default()
        while not dialog.is_destroyed():
            main_context.iteration(True)
        
        return result
    
    def show_input_dialog(self, title: str, message: str, placeholder: str = "") -> Optional[str]:
        """
        Shows an input dialog for text entry.
        
        Returns the entered text or None if cancelled.
        """
        dialog = Gtk.Dialog()
        dialog.set_transient_for(self.main_window)
        dialog.set_modal(True)
        dialog.set_title(title)
        dialog.set_default_size(400, 200)
        
        # Add buttons
        dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(_("OK"), Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        
        # Create content
        content_area = dialog.get_content_area()
        content_area.set_spacing(12)
        content_area.set_margin_top(12)
        content_area.set_margin_bottom(12)
        content_area.set_margin_start(12)
        content_area.set_margin_end(12)
        
        if message:
            label = Gtk.Label()
            label.set_text(message)
            label.set_wrap(True)
            content_area.append(label)
        
        entry = Gtk.Entry()
        entry.set_placeholder_text(placeholder)
        entry.set_activates_default(True)
        content_area.append(entry)
        
        # Focus the entry
        entry.grab_focus()
        
        dialog.present()
        response = dialog.run()
        
        result = None
        if response == Gtk.ResponseType.OK:
            result = entry.get_text().strip()
            if not result:  # Empty string
                result = None
        
        dialog.destroy()
        return result
    
    def show_selection_dialog(self, title: str, options: List[str], message: str = None) -> Optional[str]:
        """
        Shows a selection dialog with radio buttons.
        
        Returns the selected option or None if cancelled.
        """
        dialog = Gtk.Dialog()
        dialog.set_transient_for(self.main_window)
        dialog.set_modal(True)
        dialog.set_title(title)
        dialog.set_default_size(400, 300)
        
        # Add buttons
        dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(_("OK"), Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        
        # Create content
        content_area = dialog.get_content_area()
        content_area.set_spacing(12)
        content_area.set_margin_top(12)
        content_area.set_margin_bottom(12)
        content_area.set_margin_start(12)
        content_area.set_margin_end(12)
        
        if message:
            label = Gtk.Label()
            label.set_text(message)
            label.set_wrap(True)
            content_area.append(label)
        
        # Create radio button group
        radio_group = None
        radio_buttons = []
        
        for i, option in enumerate(options):
            if radio_group is None:
                radio = Gtk.CheckButton.new_with_label(option)
                radio_group = radio
            else:
                radio = Gtk.CheckButton.new_with_label(option)
                radio.set_group(radio_group)
            
            if i == 0:  # Select first option by default
                radio.set_active(True)
            
            radio_buttons.append(radio)
            content_area.append(radio)
        
        dialog.present()
        response = dialog.run()
        
        result = None
        if response == Gtk.ResponseType.OK:
            for i, radio in enumerate(radio_buttons):
                if radio.get_active():
                    result = options[i]
                    break
        
        dialog.destroy()
        return result
    
    def show_progress_dialog(self, title: str, message: str = None):
        """
        Shows a progress dialog for long-running operations.
        
        Returns a dialog object that can be updated and closed.
        """
        dialog = Adw.MessageDialog.new(
            self.main_window,
            title,
            message if message else _("Please wait...")
        )
        
        # Add progress bar
        progress_bar = Gtk.ProgressBar()
        progress_bar.set_margin_top(12)
        progress_bar.set_margin_bottom(12)
        progress_bar.set_margin_start(12)
        progress_bar.set_margin_end(12)
        
        # Note: This would need to be added to dialog content in a real implementation
        # For now, just show the dialog
        
        dialog.present()
        
        return {
            'dialog': dialog,
            'progress_bar': progress_bar,
            'close': lambda: dialog.close(),
            'set_progress': lambda p: progress_bar.set_fraction(p),
            'set_message': lambda m: dialog.set_body(m)
        }