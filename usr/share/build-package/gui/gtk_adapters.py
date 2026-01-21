#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/gtk_adapters.py - GTK adapters for core components
#

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GLib
from core.translation_utils import _
from core.conflict_resolver import ConflictResolver
from .dialogs.conflict_dialog import ConflictDialog
from .dialogs.preview_dialog import PreviewDialog, SimplePreviewDialog


class GTKConflictResolver(ConflictResolver):
    """GTK-based conflict resolver using visual dialogs"""

    def __init__(self, logger, menu_system, parent_window, strategy="interactive"):
        super().__init__(logger, menu_system, strategy)
        self.parent_window = parent_window
        self.dialog_result = None

    def _resolve_interactive(self, conflict_files):
        """Resolve conflicts interactively using GTK dialog"""
        # Create conflict dialog
        dialog = ConflictDialog(self.parent_window, conflict_files)

        # Wait for user interaction
        result_received = [False]
        success = [False]

        def on_conflicts_resolved(dialog, result):
            success[0] = result
            result_received[0] = True

        dialog.connect('conflicts-resolved', on_conflicts_resolved)
        dialog.present()

        # Wait for dialog to finish (using main loop)
        while not result_received[0]:
            GLib.MainContext.default().iteration(True)

        return success[0]

    def show_conflict_info(self, conflict_files):
        """Show information about conflicts"""
        message = _("Found {0} conflicted files:\n\n").format(len(conflict_files))
        message += "\n".join(f"  • {f}" for f in conflict_files[:10])

        if len(conflict_files) > 10:
            message += f"\n  ... and {len(conflict_files) - 10} more"

        toast = Adw.Toast.new(message)
        toast.set_timeout(5)

        if hasattr(self.parent_window, 'toast_overlay'):
            self.parent_window.toast_overlay.add_toast(toast)


class GTKMenuSystem:
    """GTK-based menu system using dialogs"""

    def __init__(self, parent_window):
        self.parent_window = parent_window

    def show_menu(self, title, options, default=None, back_option=True):
        """Show menu using GTK dialog"""
        # Create action sheet / dialog
        dialog = Adw.MessageDialog.new(
            self.parent_window,
            title,
            _("Select an option:")
        )

        # Add responses for each option
        for i, option in enumerate(options):
            response_id = f"option_{i}"
            dialog.add_response(response_id, option)

            # Highlight default
            if default is not None and i == default:
                dialog.set_default_response(response_id)

        # Add back/cancel if requested
        if back_option:
            dialog.add_response("back", _("Back"))
            dialog.set_close_response("back")

        # Wait for response
        result = [None]

        def on_response(dlg, response_id):
            if response_id.startswith("option_"):
                result[0] = int(response_id.split("_")[1])
            else:
                result[0] = None

        dialog.connect("response", on_response)
        dialog.present()

        # Wait for result
        while result[0] is None and dialog.get_visible():
            GLib.MainContext.default().iteration(True)

        return [result[0]] if result[0] is not None else []

    def ask_yes_no(self, question, default_yes=True):
        """Ask yes/no question"""
        dialog = Adw.MessageDialog.new(
            self.parent_window,
            "",
            question
        )

        dialog.add_response("no", _("No"))
        dialog.add_response("yes", _("Yes"))

        if default_yes:
            dialog.set_default_response("yes")
            dialog.set_response_appearance("yes", Adw.ResponseAppearance.SUGGESTED)
        else:
            dialog.set_default_response("no")

        dialog.set_close_response("no")

        result = [False]

        def on_response(dlg, response_id):
            result[0] = (response_id == "yes")

        dialog.connect("response", on_response)
        dialog.present()

        # Wait for result
        while dialog.get_visible():
            GLib.MainContext.default().iteration(True)

        return result[0]
    
    def confirm(self, question, default_yes=True):
        """Confirm an action (alias for ask_yes_no)"""
        return self.ask_yes_no(question, default_yes)

    def ask_input(self, prompt, default_value=""):
        """Ask for text input"""
        dialog = Adw.MessageDialog.new(
            self.parent_window,
            "",
            prompt
        )

        # Create entry
        entry = Gtk.Entry()
        entry.set_text(default_value)
        entry.set_activates_default(True)
        entry.set_margin_top(12)
        entry.set_margin_bottom(12)
        entry.set_margin_start(12)
        entry.set_margin_end(12)

        try:
            dialog.set_extra_child(entry)
        except AttributeError:
            pass  # Fallback: dialog without entry field

        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("ok", _("OK"))
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("ok")
        dialog.set_close_response("cancel")

        result = [None]

        def on_response(dlg, response_id):
            if response_id == "ok":
                result[0] = entry.get_text()
            else:
                result[0] = None

        dialog.connect("response", on_response)
        dialog.present()

        # Wait for result
        while result[0] is None and dialog.get_visible():
            GLib.MainContext.default().iteration(True)

        return result[0]

    def show_preview(self, operations, dry_run=False):
        """Show operation preview"""
        # Convert operations to the format expected by PreviewDialog
        ops_list = []
        for op in operations:
            ops_list.append({
                'description': op.description if hasattr(op, 'description') else str(op),
                'commands': op.commands if hasattr(op, 'commands') else [],
                'destructive': op.destructive if hasattr(op, 'destructive') else False
            })

        dialog = PreviewDialog(self.parent_window, ops_list, dry_run=dry_run)

        result = [False]

        def on_accepted(dlg):
            result[0] = True

        def on_rejected(dlg):
            result[0] = False

        dialog.connect('preview-accepted', on_accepted)
        dialog.connect('preview-rejected', on_rejected)
        dialog.present()

        # Wait for result
        while dialog.get_visible():
            GLib.MainContext.default().iteration(True)

        return result[0]

    def show_confirmation(self, title, message, destructive=False):
        """Show confirmation dialog"""
        dialog = SimplePreviewDialog(
            self.parent_window,
            title,
            message,
            destructive=destructive
        )

        result = [False]

        def on_confirmed(dlg):
            result[0] = True

        def on_cancelled(dlg):
            result[0] = False

        dialog.connect('confirmed', on_confirmed)
        dialog.connect('cancelled', on_cancelled)
        dialog.present()

        # Wait for result
        while dialog.get_visible():
            GLib.MainContext.default().iteration(True)

        return result[0]
