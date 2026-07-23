#!/usr/bin/env python3
"""Choose the remote branch used as the update source."""

from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from core.translation_utils import _, ngettext
from gi.repository import Adw, GObject, Gtk


class PullSourceDialog(Adw.Window):
    """Display remote branches and let the user choose an update source."""

    __gtype_name__ = "PullSourceDialog"

    __gsignals__ = {
        "pull-requested": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "preview-requested": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, parent, branches, current_branch):
        super().__init__(
            transient_for=parent,
            modal=True,
            title=_("Choose Update Source"),
        )
        self.set_default_size(820, 650)
        self.set_resizable(True)
        self._branches = branches
        self._current_branch = current_branch
        self._selected = None

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        self.set_content(toolbar)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_start(18)
        content.set_margin_end(18)
        toolbar.set_content(content)

        title = Gtk.Label(label=_("Choose where updates should come from"), xalign=0)
        title.add_css_class("title-2")
        content.append(title)

        explanation = Gtk.Label(
            label=_(
                "The selected remote branch will be incorporated into {0}. "
                "You will remain on your own branch."
            ).format(current_branch),
            xalign=0,
        )
        explanation.set_wrap(True)
        explanation.add_css_class("dim-label")
        content.append(explanation)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        content.append(scroll)

        self.branch_list = Gtk.ListBox()
        self.branch_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.branch_list.add_css_class("boxed-list")
        self.branch_list.connect("row-selected", self._on_row_selected)
        scroll.set_child(self.branch_list)

        selected_row = None
        for branch in branches:
            row = self._create_branch_row(branch)
            self.branch_list.append(row)
            if selected_row is None and branch.get("is_recommended"):
                selected_row = row

        if selected_row is None:
            selected_row = self.branch_list.get_row_at_index(0)
        if selected_row is not None:
            self.branch_list.select_row(selected_row)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        button_box.set_halign(Gtk.Align.END)
        content.append(button_box)

        cancel_button = Gtk.Button(label=_("Cancel"))
        cancel_button.connect("clicked", lambda _button: self.close())
        button_box.append(cancel_button)

        self.preview_button = Gtk.Button(label=_("Preview Changes"))
        self.preview_button.connect("clicked", self._on_preview_clicked)
        button_box.append(self.preview_button)

        self.pull_button = Gtk.Button(label=_("Pull Updates"))
        self.pull_button.add_css_class("suggested-action")
        self.pull_button.connect("clicked", self._on_pull_clicked)
        button_box.append(self.pull_button)

        self._update_buttons()

    def _create_branch_row(self, branch):
        subtitle = _("{0} by {1} — {2}").format(
            branch.get("short_commit", ""),
            branch.get("author") or _("Unknown author"),
            self._format_date(branch.get("timestamp", 0)),
        )
        subject = branch.get("subject", "")
        if subject:
            subtitle = _("{0}\n{1}").format(subtitle, subject)

        row = Adw.ActionRow(title=branch["branch"], subtitle=subtitle)
        row.branch_data = branch
        row.set_activatable(True)

        relation_label = Gtk.Label(label=self._relation_text(branch))
        relation_label.add_css_class("caption")
        relation_label.add_css_class(self._relation_tone(branch))
        row.add_suffix(relation_label)

        if branch.get("is_latest"):
            row.add_suffix(self._badge(_("Newest commit"), "success"))
        if branch.get("is_recommended"):
            row.add_suffix(self._badge(_("Recommended"), "accent"))
        if branch.get("is_current"):
            row.add_suffix(self._badge(_("Current branch"), "accent"))
        if branch.get("is_main"):
            row.add_suffix(self._badge(_("Main"), "purple"))
        return row

    @staticmethod
    def _badge(text, tone):
        badge = Gtk.Label(label=text)
        badge.add_css_class("caption")
        badge.add_css_class("pill")
        badge.add_css_class(tone)
        return badge

    @staticmethod
    def _format_date(timestamp):
        if not timestamp:
            return _("Unknown date")
        return datetime.fromtimestamp(timestamp).astimezone().strftime("%x %X")

    def _relation_text(self, branch):
        incoming = branch.get("incoming", 0)
        local_only = branch.get("local_only", 0)
        relation = branch.get("relation")
        if relation == "diverged":
            incoming_text = ngettext(
                "{0} incoming commit",
                "{0} incoming commits",
                incoming,
            ).format(incoming)
            local_text = ngettext(
                "{0} local commit",
                "{0} local commits",
                local_only,
            ).format(local_only)
            return _("{0}; {1}").format(incoming_text, local_text)
        if relation == "incoming":
            return ngettext(
                "{0} incoming commit",
                "{0} incoming commits",
                incoming,
            ).format(incoming)
        if relation == "local-ahead":
            return ngettext(
                "{0} local commit ahead",
                "{0} local commits ahead",
                local_only,
            ).format(local_only)
        return _("Up to date")

    @staticmethod
    def _relation_tone(branch):
        return {
            "diverged": "warning",
            "incoming": "success",
            "local-ahead": "accent",
            "up-to-date": "dim-label",
        }.get(branch.get("relation"), "dim-label")

    def _on_row_selected(self, _listbox, row):
        self._selected = row.branch_data if row is not None else None
        self._update_buttons()

    def _update_buttons(self):
        if not hasattr(self, "preview_button"):
            return
        enabled = self._selected is not None
        self.preview_button.set_sensitive(
            enabled and self._selected.get("incoming", 0) > 0
        )
        self.pull_button.set_sensitive(enabled)

    def _on_preview_clicked(self, _button):
        if self._selected:
            self.emit("preview-requested", self._selected["branch"])

    def _on_pull_clicked(self, _button):
        if not self._selected:
            return
        branch = self._selected["branch"]
        self.close()
        self.emit("pull-requested", branch)
