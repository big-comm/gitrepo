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
import threading


class GTKConflictResolver(ConflictResolver):
    """GTK-based conflict resolver using visual dialogs"""

    def __init__(self, logger, menu_system, parent_window, strategy="interactive"):
        super().__init__(logger, menu_system, strategy)
        self.parent_window = parent_window
        self.dialog_result = None
        self._result_event = threading.Event()

    def _resolve_interactive(self, conflict_files):
        """Resolve conflicts interactively using GTK dialog"""
        return self._show_conflict_dialog(conflict_files)

    def _resolve_interactive_enhanced(self, conflict_files, current_branch, incoming_branch):
        """
        Enhanced interactive resolution with branch comparison.
        For GTK, we use the same dialog but could show branch info in the future.
        """
        # For now, use the same dialog - ConflictDialog already handles the resolution
        # In the future, we could enhance ConflictDialog to show branch comparison
        return self._show_conflict_dialog(conflict_files, current_branch, incoming_branch)

    def _show_conflict_dialog(self, conflict_files, current_branch=None, incoming_branch=None):
        """Show the conflict resolution dialog"""
        # Reset state
        self._result_event.clear()
        self.dialog_result = False

        def show_dialog_on_main_thread():
            """Show dialog on GTK main thread"""
            # Close any existing progress dialog temporarily
            # to avoid modal dialog conflicts
            dialog = ConflictDialog(self.parent_window, conflict_files)
            
            # Store branch info for future use (if dialog supports it)
            if hasattr(dialog, 'set_branch_info') and current_branch and incoming_branch:
                dialog.set_branch_info(current_branch, incoming_branch)

            def on_conflicts_resolved(dlg, result):
                self.dialog_result = result
                self._result_event.set()  # Signal that we have a result

            dialog.connect('conflicts-resolved', on_conflicts_resolved)
            dialog.present()
            return False  # Don't repeat

        # Schedule dialog to show on main thread
        GLib.idle_add(show_dialog_on_main_thread)

        # Wait for result using threading.Event (non-blocking for GTK)
        # This allows GTK to continue processing events
        self._result_event.wait()

        return self.dialog_result

    def show_conflict_info(self, conflict_files):
        """Show information about conflicts"""
        message = _("Found {0} conflicted files:").format(len(conflict_files)) + "\n\n"
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
        self._result = None
        self._result_event = threading.Event()

    def _wait_for_dialog(self, setup_func):
        """
        Helper to show dialog and wait for result without blocking GTK.
        setup_func should configure the dialog and return it.
        """
        self._result_event.clear()
        self._result = None
        
        def show_on_main():
            setup_func()
            return False
        
        GLib.idle_add(show_on_main)
        self._result_event.wait()
        return self._result

    def show_menu(self, title, options, default=None, back_option=True):
        """Show menu using GTK dialog with improved UX and colored branches"""
        def setup():
            # Check if title contains branch information and create enhanced display
            enhanced_title = title
            branch_info_widget = None
            
            # Detect branch pattern in title: "in X, but your branch is Y"
            # Common patterns: "You're in main, but your branch is dev-xxx"
            import re
            branch_pattern = r"(main|master|dev-\w+)"
            matches = re.findall(branch_pattern, title, re.IGNORECASE)
            
            if len(matches) >= 2:
                # We have current branch and target branch
                current_branch = matches[0]
                target_branch = matches[1]
                
                # Create a simpler title
                simple_title = _("Branch Switch Required")
                
                # Create enhanced content with colored branches
                branch_info_widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
                branch_info_widget.set_margin_top(8)
                branch_info_widget.set_margin_bottom(16)
                branch_info_widget.set_size_request(500, -1)  # Minimum width
                
                # Current branch (orange/red for protected, blue for dev)
                current_color = "#e66100" if current_branch.lower() in ["main", "master"] else "#3584e4"
                target_color = "#2ec27e"  # Green for user's branch
                
                # Create info label with Pango markup
                info_label = Gtk.Label()
                info_label.set_markup(
                    f"<span size='large'>{_('You are on')} <b><span foreground='{current_color}'>{current_branch}</span></b></span>\n"
                    f"<span size='large'>{_('Your branch is')} <b><span foreground='{target_color}'>{target_branch}</span></b></span>"
                )
                info_label.set_justify(Gtk.Justification.CENTER)
                info_label.set_halign(Gtk.Align.CENTER)
                branch_info_widget.append(info_label)
                
                # Visual arrow indicator
                arrow_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                arrow_box.set_halign(Gtk.Align.CENTER)
                arrow_box.set_margin_top(8)
                
                current_label = Gtk.Label()
                current_label.set_markup(f"<span foreground='{current_color}' weight='bold'>{current_branch}</span>")
                
                arrow_label = Gtk.Label()
                arrow_label.set_markup("<span size='large'>→</span>")
                
                target_label = Gtk.Label()
                target_label.set_markup(f"<span foreground='{target_color}' weight='bold'>{target_branch}</span>")
                
                arrow_box.append(current_label)
                arrow_box.append(arrow_label)
                arrow_box.append(target_label)
                branch_info_widget.append(arrow_box)
                
                enhanced_title = simple_title
            
            dialog = Adw.MessageDialog.new(
                self.parent_window,
                enhanced_title,
                _("Select an option:") if not branch_info_widget else ""
            )
            
            # Set extra child (branch info or just a spacer for width)
            if branch_info_widget:
                dialog.set_extra_child(branch_info_widget)
            else:
                # Just force minimum width
                content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
                content_box.set_size_request(500, -1)
                dialog.set_extra_child(content_box)

            for i, option in enumerate(options):
                response_id = f"option_{i}"
                dialog.add_response(response_id, option)
                
                if default is not None and i == default:
                    dialog.set_default_response(response_id)
                
                # Smart styling based on option content
                option_lower = option.lower() if hasattr(option, 'lower') else ""
                
                # Destructive actions (red) - cancel, back, exit, voltar, cancelar, sair
                if any(word in option_lower for word in ["cancel", "voltar", "cancelar", "sair"]):
                    dialog.set_response_appearance(response_id, Adw.ResponseAppearance.DESTRUCTIVE)
                
                # Suggested actions (blue) - switch, my branch, minha, mudar, atualizar
                elif any(word in option_lower for word in ["switch", "my branch", "minha", "mudar", "atualizar", "baixar", "recommend", "recomendado"]):
                    dialog.set_response_appearance(response_id, Adw.ResponseAppearance.SUGGESTED)

            if back_option:
                dialog.add_response("back", _("Back"))
                dialog.set_response_appearance("back", Adw.ResponseAppearance.DESTRUCTIVE)
                dialog.set_close_response("back")

            def on_response(dlg, response_id):
                if response_id.startswith("option_"):
                    self._result = [int(response_id.split("_")[1])]
                else:
                    self._result = []
                self._result_event.set()

            dialog.connect("response", on_response)
            dialog.present()

        return self._wait_for_dialog(setup)

    def ask_yes_no(self, question, default_yes=True):
        """Ask yes/no question"""
        def setup():
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

            def on_response(dlg, response_id):
                self._result = (response_id == "yes")
                self._result_event.set()

            dialog.connect("response", on_response)
            dialog.present()

        return self._wait_for_dialog(setup)
    
    def confirm(self, question, default_yes=True):
        """Confirm an action (alias for ask_yes_no)"""
        return self.ask_yes_no(question, default_yes)

    def ask_input(self, prompt, default_value=""):
        """Ask for text input"""
        def setup():
            dialog = Adw.MessageDialog.new(
                self.parent_window,
                "",
                prompt
            )

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
                pass

            dialog.add_response("cancel", _("Cancel"))
            dialog.add_response("ok", _("OK"))
            dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
            dialog.set_default_response("ok")
            dialog.set_close_response("cancel")

            def on_response(dlg, response_id):
                if response_id == "ok":
                    self._result = entry.get_text()
                else:
                    self._result = None
                self._result_event.set()

            dialog.connect("response", on_response)
            dialog.present()

        return self._wait_for_dialog(setup)

    def show_preview(self, operations, dry_run=False):
        """Show operation preview"""
        def setup():
            ops_list = []
            for op in operations:
                ops_list.append({
                    'description': op.description if hasattr(op, 'description') else str(op),
                    'commands': op.commands if hasattr(op, 'commands') else [],
                    'destructive': op.destructive if hasattr(op, 'destructive') else False
                })

            dialog = PreviewDialog(self.parent_window, ops_list, dry_run=dry_run)

            def on_accepted(dlg):
                self._result = True
                self._result_event.set()

            def on_rejected(dlg):
                self._result = False
                self._result_event.set()

            dialog.connect('preview-accepted', on_accepted)
            dialog.connect('preview-rejected', on_rejected)
            dialog.present()

        return self._wait_for_dialog(setup)

    def show_confirmation(self, title, message, destructive=False):
        """Show confirmation dialog"""
        def setup():
            dialog = SimplePreviewDialog(
                self.parent_window,
                title,
                message,
                destructive=destructive
            )

            def on_confirmed(dlg):
                self._result = True
                self._result_event.set()

            def on_cancelled(dlg):
                self._result = False
                self._result_event.set()

            dialog.connect('confirmed', on_confirmed)
            dialog.connect('cancelled', on_cancelled)
            dialog.present()

        return self._wait_for_dialog(setup)
