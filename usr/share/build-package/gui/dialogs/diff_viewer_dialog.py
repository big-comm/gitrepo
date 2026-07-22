#!/usr/bin/env python3
"""Graphical per-file Git diff viewer."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from core.translation_utils import _
from gi.repository import Adw, Gtk


class DiffViewerDialog(Adw.Window):
    """Display a list of changed files and a unified diff for each file."""

    def __init__(self, parent, title, changes, diff_loader, initial_path=None):
        super().__init__(transient_for=parent, modal=True, title=title)
        self.set_default_size(1100, 720)
        self.set_resizable(True)
        self._changes = changes
        self._diff_loader = diff_loader
        self._rows = {}

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        self.set_content(toolbar)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_wide_handle(True)
        paned.set_position(330)
        toolbar.set_content(paned)

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        sidebar.set_margin_top(12)
        sidebar.set_margin_bottom(12)
        sidebar.set_margin_start(12)
        sidebar.set_margin_end(6)

        summary = Gtk.Label(
            label=_("{0} changed file(s)").format(len(changes)),
            xalign=0,
        )
        summary.add_css_class("heading")
        sidebar.append(summary)

        file_scroll = Gtk.ScrolledWindow()
        file_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        file_scroll.set_vexpand(True)
        file_list = Gtk.ListBox()
        file_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        file_list.add_css_class("boxed-list")
        file_list.connect("row-selected", self._on_row_selected)
        file_scroll.set_child(file_list)
        sidebar.append(file_scroll)
        paned.set_start_child(sidebar)

        diff_frame = Gtk.Frame()
        diff_frame.set_margin_top(12)
        diff_frame.set_margin_bottom(12)
        diff_frame.set_margin_start(6)
        diff_frame.set_margin_end(12)
        diff_frame.add_css_class("view")
        diff_scroll = Gtk.ScrolledWindow()
        diff_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.diff_view = Gtk.TextView()
        self.diff_view.set_editable(False)
        self.diff_view.set_cursor_visible(False)
        self.diff_view.set_monospace(True)
        self.diff_view.set_wrap_mode(Gtk.WrapMode.NONE)
        self.diff_view.set_left_margin(12)
        self.diff_view.set_right_margin(12)
        self.diff_view.set_top_margin(12)
        self.diff_view.set_bottom_margin(12)
        diff_scroll.set_child(self.diff_view)
        diff_frame.set_child(diff_scroll)
        paned.set_end_child(diff_frame)

        selected_row = None
        for status, filepath in changes:
            row = Adw.ActionRow(title=filepath, subtitle=self._status_label(status))
            row.filepath = filepath
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            file_list.append(row)
            self._rows[filepath] = row
            if selected_row is None or filepath == initial_path:
                selected_row = row

        if selected_row is not None:
            file_list.select_row(selected_row)
        else:
            self._set_diff_text(_("No changed files to display."))

    @staticmethod
    def _status_label(status):
        return {
            "M": _("Modified"),
            "A": _("Added"),
            "D": _("Deleted"),
            "R": _("Renamed"),
            "C": _("Copied"),
            "??": _("Untracked"),
            "AM": _("Added and modified"),
            "MM": _("Modified in index and working tree"),
        }.get(status, status)

    def _on_row_selected(self, _listbox, row):
        if row is None:
            return
        diff = self._diff_loader(row.filepath)
        self._set_diff_text(diff or _("No textual differences to display."))

    def _set_diff_text(self, content):
        buffer = self.diff_view.get_buffer()
        buffer.set_text("")
        tags = {
            "added": buffer.create_tag(None, foreground="#2ec27e"),
            "removed": buffer.create_tag(None, foreground="#e01b24"),
            "hunk": buffer.create_tag(None, foreground="#3584e4", weight=700),
            "header": buffer.create_tag(None, foreground="#986a44", weight=700),
        }
        for line in content.splitlines(keepends=True):
            tag = None
            if line.startswith(("diff --git", "index ", "--- ", "+++ ")):
                tag = tags["header"]
            elif line.startswith("@@"):
                tag = tags["hunk"]
            elif line.startswith("+"):
                tag = tags["added"]
            elif line.startswith("-"):
                tag = tags["removed"]
            end = buffer.get_end_iter()
            if tag:
                buffer.insert_with_tags(end, line, tag)
            else:
                buffer.insert(end, line)

