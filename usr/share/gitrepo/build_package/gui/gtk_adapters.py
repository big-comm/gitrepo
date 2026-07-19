#
# gui/gtk_adapters.py - GTK adapters for core components
#

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GLib
from gitrepo.common.translation import _
from gitrepo.build_package.core.conflict_resolver import ConflictResolver
from .dialogs.conflict_dialog import ConflictDialog
from .dialogs.preview_dialog import PreviewDialog
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
        return self._show_conflict_dialog(conflict_files, current_branch, incoming_branch)

    def _show_conflict_dialog(self, conflict_files, current_branch=None, incoming_branch=None):
        """Present conflict UI on GTK and wait only on the operation worker."""
        self._result_event.clear()
        self.dialog_result = False
        GLib.idle_add(self._present_conflict_dialog, conflict_files, current_branch, incoming_branch)
        self._result_event.wait()
        return self.dialog_result

    def _present_conflict_dialog(self, conflict_files, current_branch, incoming_branch):
        progress_dialog = getattr(getattr(self.parent_window, "operation_runner", None), "current_dialog", None)
        self._set_progress_visible(progress_dialog, False)
        try:
            dialog = ConflictDialog(self.parent_window, conflict_files, repo_root=self.repo_root)
            if current_branch and incoming_branch and hasattr(dialog, "set_branch_info"):
                dialog.set_branch_info(current_branch, incoming_branch)
            dialog.connect("conflicts-resolved", self._finish_conflict_dialog, progress_dialog)
            dialog.connect("destroy", self._destroy_conflict_dialog, progress_dialog)
            dialog.present()
        except Exception:
            self._result_event.set()
        return False

    def _finish_conflict_dialog(self, _dialog, result, progress_dialog):
        self._set_progress_visible(progress_dialog, True)
        self.dialog_result = result
        self._result_event.set()

    def _destroy_conflict_dialog(self, _dialog, progress_dialog):
        if self._result_event.is_set():
            return
        self._set_progress_visible(progress_dialog, True)
        self.dialog_result = False
        self._result_event.set()

    @staticmethod
    def _set_progress_visible(progress_dialog, is_visible):
        if not progress_dialog:
            return
        if is_visible:
            progress_dialog.set_visible(True)
            progress_dialog.set_progress_mode(indeterminate=True)
            return
        if getattr(progress_dialog, "_pulse_timeout_id", None):
            GLib.source_remove(progress_dialog._pulse_timeout_id)
            progress_dialog._pulse_timeout_id = None
        if hasattr(progress_dialog, "spinner"):
            progress_dialog.spinner.stop()
        progress_dialog.set_visible(False)


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

    def show_menu(
        self,
        title,
        options,
        default=None,
        back_option=True,
        additional_content=None,
        default_index=None,
    ):
        """Show a semantic option dialog and return the selected option."""
        selected_default = default_index if default_index is not None else default

        def setup():
            dialog = Adw.MessageDialog.new(self.parent_window, title, _("Select an option."))
            if additional_content:
                details = Gtk.Label(label=additional_content, wrap=True, selectable=True, xalign=0)
                details.set_margin_top(12)
                details.set_margin_bottom(12)
                details.set_margin_start(12)
                details.set_margin_end(12)
                dialog.set_extra_child(details)
            for index, option in enumerate(options):
                response_id = f"option_{index}"
                dialog.add_response(response_id, option)
                self._style_menu_response(dialog, response_id, option)
                if index == selected_default:
                    dialog.set_default_response(response_id)
            if back_option:
                dialog.add_response("back", _("Back"))
                dialog.set_close_response("back")
            dialog.connect("response", self._on_menu_response, options)
            dialog.present()

        return self._wait_for_dialog(setup)

    @staticmethod
    def _style_menu_response(dialog, response_id, option):
        normalized = option.casefold()
        if any(word in normalized for word in ("delete", "remove", "discard", "reset", "excluir", "remover")):
            dialog.set_response_appearance(response_id, Adw.ResponseAppearance.DESTRUCTIVE)
        elif any(word in normalized for word in ("recommended", "recomendado")):
            dialog.set_response_appearance(response_id, Adw.ResponseAppearance.SUGGESTED)

    def _on_menu_response(self, _dialog, response_id, options):
        if response_id.startswith("option_"):
            index = int(response_id.removeprefix("option_"))
            self._result = (index, options[index])
        else:
            self._result = None
        self._result_event.set()

    def ask_yes_no(self, question, default_yes=True):
        """Ask yes/no question"""

        def setup():
            dialog = Adw.MessageDialog.new(self.parent_window, "", question)

            dialog.add_response("no", _("No"))
            dialog.add_response("yes", _("Yes"))

            if default_yes:
                dialog.set_default_response("yes")
                dialog.set_response_appearance("yes", Adw.ResponseAppearance.SUGGESTED)
            else:
                dialog.set_default_response("no")

            dialog.set_close_response("no")

            def on_response(_dlg, response_id):
                self._result = response_id == "yes"
                self._result_event.set()

            dialog.connect("response", on_response)
            dialog.present()

        return self._wait_for_dialog(setup)

    def confirm(self, question, default_yes=True):
        """Confirm an action (alias for ask_yes_no)"""
        return self.ask_yes_no(question, default_yes)

    def show_preview(self, operations, dry_run=False):
        """Show operation preview"""

        def setup():
            ops_list = []
            for op in operations:
                ops_list.append(
                    {
                        "description": op.description if hasattr(op, "description") else str(op),
                        "commands": op.commands if hasattr(op, "commands") else [],
                        "destructive": op.destructive if hasattr(op, "destructive") else False,
                    }
                )

            dialog = PreviewDialog(self.parent_window, ops_list, dry_run=dry_run)

            def on_accepted(_dlg):
                self._result = True
                self._result_event.set()

            def on_rejected(_dlg):
                self._result = False
                self._result_event.set()

            dialog.connect("preview-accepted", on_accepted)
            dialog.connect("preview-rejected", on_rejected)
            dialog.present()

        return self._wait_for_dialog(setup)
