"""Graphical per-file Git diff viewer."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gitrepo.common.translation import _
from gitrepo.common.terminal_palette import log_palette
from gi.repository import Adw, Gtk

# Status letters as reported by git status/diff, in the user's words.
STATUS_LABELS = {
    "M": _("Modified"),
    "A": _("Added"),
    "D": _("Deleted"),
    "R": _("Renamed"),
    "C": _("Copied"),
    "??": _("Untracked"),
    "AM": _("Added and modified"),
    "MM": _("Modified in index and working tree"),
}


class DiffViewerDialog(Adw.Window):
    """List the changed files and show a unified diff for the selected one."""

    def __init__(self, parent, title, changes, diff_loader, initial_path=None):
        super().__init__(transient_for=parent, modal=True, title=title)
        self.set_default_size(1000, 660)
        self.set_resizable(True)
        self._diff_loader = diff_loader
        self._style_manager = Adw.StyleManager.get_default()

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=title, subtitle=_("{0} changed file(s)").format(len(changes))))
        toolbar.add_top_bar(header)
        self.set_content(toolbar)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_wide_handle(True)
        paned.set_position(320)
        diff_pane = self._create_diff_view()
        file_sidebar = self._create_file_list(changes, initial_path)
        paned.set_start_child(file_sidebar)
        paned.set_end_child(diff_pane)
        toolbar.set_content(paned)

        self._style_handler = self._style_manager.connect("notify::dark", lambda *_args: self._reload_selected_diff())
        self.connect("close-request", self._on_close_request)

    def _on_close_request(self, _window) -> bool:
        """Release the process-wide style handler when the dialog closes."""
        if self._style_handler:
            self._style_manager.disconnect(self._style_handler)
            self._style_handler = 0
        return False

    def _create_file_list(self, changes, initial_path):
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar.add_css_class("build-package-diff-sidebar")

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        self.file_list = Gtk.ListBox()
        self.file_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.file_list.add_css_class("navigation-sidebar")
        self.file_list.connect("row-selected", self._on_row_selected)
        scroll.set_child(self.file_list)
        sidebar.append(scroll)

        selected_row = None
        for status, filepath in changes:
            row = Adw.ActionRow(title=filepath, subtitle=STATUS_LABELS.get(status, status))
            row.set_title_lines(2)
            row.filepath = filepath
            self.file_list.append(row)
            if selected_row is None or filepath == initial_path:
                selected_row = row

        if selected_row is not None:
            self.file_list.select_row(selected_row)
        return sidebar

    def _create_diff_view(self):
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        container.add_css_class("build-package-diff-pane")

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        self.diff_view = Gtk.TextView()
        self.diff_view.set_editable(False)
        self.diff_view.set_cursor_visible(False)
        self.diff_view.set_monospace(True)
        self.diff_view.set_wrap_mode(Gtk.WrapMode.NONE)
        self.diff_view.set_left_margin(14)
        self.diff_view.set_right_margin(14)
        self.diff_view.set_top_margin(12)
        self.diff_view.set_bottom_margin(12)
        self.diff_view.add_css_class("build-package-diff-view")
        self.diff_view.update_property([Gtk.AccessibleProperty.LABEL], [_("File differences")])
        scroll.set_child(self.diff_view)
        container.append(scroll)

        self._set_diff_text(_("No changed files to display."))
        return container

    def _on_row_selected(self, _listbox, row):
        if row is None:
            return
        self._set_diff_text(self._diff_loader(row.filepath) or _("No textual differences to display."))

    def _reload_selected_diff(self):
        self._on_row_selected(self.file_list, self.file_list.get_selected_row())

    def _set_diff_text(self, content):
        buffer = self.diff_view.get_buffer()
        buffer.set_text("")
        palette = log_palette(self._style_manager.get_dark())
        tags = {
            "added": buffer.create_tag(None, foreground=palette["green"]),
            "removed": buffer.create_tag(None, foreground=palette["red"]),
            "hunk": buffer.create_tag(None, foreground=palette["blue"], weight=700),
            "header": buffer.create_tag(None, foreground=palette["dim"], weight=700),
        }
        for line in content.splitlines(keepends=True):
            buffer.insert_with_tags(buffer.get_end_iter(), line, *filter(None, [self._line_tag(line, tags)]))

    @staticmethod
    def _line_tag(line, tags):
        if line.startswith(("diff --git", "index ", "--- ", "+++ ")):
            return tags["header"]
        if line.startswith("@@"):
            return tags["hunk"]
        if line.startswith("+"):
            return tags["added"]
        if line.startswith("-"):
            return tags["removed"]
        return None


def present_diff_viewer(parent, title, changes, diff_loader, initial_path=None):
    """Open the viewer, or report that nothing changed."""
    if not changes:
        if parent is not None and hasattr(parent, "show_toast"):
            parent.show_toast(_("No changed files to display."))
        return None
    dialog = DiffViewerDialog(parent, title, changes, diff_loader, initial_path)
    dialog.present()
    return dialog


__all__ = ["DiffViewerDialog", "present_diff_viewer", "STATUS_LABELS"]
