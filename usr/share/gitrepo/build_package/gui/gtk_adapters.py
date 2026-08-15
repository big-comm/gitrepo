#
# gui/gtk_adapters.py - GTK adapters for core components
#

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GLib
from gitrepo.common.translation import _
from gitrepo.build_package.core.conflict_resolver import ConflictResolver
from .confirmation_dialog import ConfirmationDialog
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

    def _resolve_interactive_stash(self, conflict_files, source_branch, target_branch):
        """Present saved work as local even though Git stores it in stage three."""
        return self._show_conflict_dialog(
            conflict_files,
            source_branch,
            target_branch,
            local_side="theirs",
        )

    def _show_conflict_dialog(
        self,
        conflict_files,
        current_branch=None,
        incoming_branch=None,
        local_side="ours",
    ):
        """Present conflict UI on GTK and wait only on the operation worker."""
        self._result_event.clear()
        self.dialog_result = False
        GLib.idle_add(
            self._present_conflict_dialog,
            conflict_files,
            current_branch,
            incoming_branch,
            local_side,
        )
        self._result_event.wait()
        return self.dialog_result

    def _present_conflict_dialog(self, conflict_files, current_branch, incoming_branch, local_side):
        progress_dialog = getattr(getattr(self.parent_window, "operation_runner", None), "current_dialog", None)
        self._set_progress_visible(progress_dialog, False)
        try:
            dialog = ConflictDialog(
                self.parent_window,
                conflict_files,
                repo_root=self.repo_root,
                local_side=local_side,
            )
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


# A menu body is prose the caller wrote, and some of it is a list as long as
# the conflict is: a merge of the translation workflow's output names all 39
# catalogs. The dialog sizes itself to its child, so an unscrolled label of
# that length grows a window taller than the screen -- with the responses,
# the only way to answer it, off the bottom edge. Same treatment the
# confirmation dialog already gives its details.
_DETAILS_MAX_HEIGHT = 360
# Without it the wrapped label settles on a column narrow enough to make a
# path list unreadable, which is what makes a long body long in the first place.
_DETAILS_MIN_WIDTH = 520


def _scrollable_details(details):
    scrolled = Gtk.ScrolledWindow()
    scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scrolled.set_max_content_height(_DETAILS_MAX_HEIGHT)
    # Short bodies keep their own height: the scroller is a ceiling, not a size.
    scrolled.set_propagate_natural_height(True)
    scrolled.set_size_request(_DETAILS_MIN_WIDTH, -1)
    scrolled.set_child(details)
    return scrolled


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
            try:
                setup_func()
            except Exception:
                self._result_event.set()
                raise
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
        # Adw renders the heading centred and bold, which turns a multi-line
        # question into an unreadable block. Only the first line is a heading;
        # everything else is body text, left aligned like the prose it is.
        heading, _separator, remainder = str(title).partition("\n")
        body = "\n\n".join(part for part in (remainder.strip(), additional_content) if part)

        def setup():
            dialog = Adw.MessageDialog.new(self.parent_window, heading, None)
            if body:
                details = Gtk.Label(label=body, wrap=True, selectable=True, xalign=0)
                details.set_margin_top(12)
                details.set_margin_bottom(12)
                details.set_margin_start(12)
                details.set_margin_end(12)
                dialog.set_extra_child(_scrollable_details(details))
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
            dialog = ConfirmationDialog(question, default_yes)

            def on_response(_dlg, response_id):
                self._result = response_id == "yes"
                self._result_event.set()

            dialog.connect("response", on_response)
            progress_dialog = getattr(
                getattr(self.parent_window, "operation_runner", None),
                "current_dialog",
                None,
            )
            dialog.present(progress_dialog or self.parent_window)

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
