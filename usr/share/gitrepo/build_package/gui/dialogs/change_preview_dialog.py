"""Show what an operation will change before it runs: steps, files, and GitHub.

The same dialog reviews Synchronize, Go back to a commit and Undo, from a
``history.Preview`` the core computes without GTK.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk, Pango

from gitrepo.common.translation import _

# Status of a changed file: pill text and colour class.
_FILE_STATUS = {
    "A": (lambda: _("added"), "status-ok"),
    "M": (lambda: _("modified"), "status-accent"),
    "D": (lambda: _("deleted"), "status-error"),
    "R": (lambda: _("renamed"), "status-warning"),
    "C": (lambda: _("copied"), "status-accent"),
}
_MAX_FILES = 200
_NOTICE_ICONS = {"warning": "dialog-warning-symbolic", "info": "dialog-information-symbolic"}


def _label(text, *css_classes, selectable=False):
    label = Gtk.Label(label=text, xalign=0, wrap=True)
    label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    label.set_selectable(selectable)
    for css_class in css_classes:
        label.add_css_class(css_class)
    return label


def _section_title(text):
    title = _label(text, "heading")
    title.set_accessible_role(Gtk.AccessibleRole.HEADING)
    title.set_margin_top(6)
    return title


def _boxed_list():
    listbox = Gtk.ListBox()
    listbox.set_selection_mode(Gtk.SelectionMode.NONE)
    listbox.add_css_class("boxed-list")
    return listbox


def _step_row(step):
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    row.add_css_class("change-preview-row")
    icon = Gtk.Image.new_from_icon_name(step.icon)
    icon.set_valign(Gtk.Align.START)
    icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
    row.append(icon)
    text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    text.set_hexpand(True)
    text.append(_label(step.text))
    if step.command:
        text.append(_label(step.command, "change-preview-command", selectable=True))
    row.append(text)
    return row


def _file_row(change):
    label_text, css_class = _FILE_STATUS.get(change.status, (lambda: change.status, "dim-label"))
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    row.add_css_class("change-preview-row")
    pill = Gtk.Label(label=label_text())
    pill.add_css_class("state-pill")
    pill.add_css_class(css_class)
    pill.set_valign(Gtk.Align.CENTER)
    pill.set_width_chars(10)
    row.append(pill)
    path = _label(change.path, "change-preview-command", selectable=True)
    path.set_hexpand(True)
    row.append(path)
    return row


def _notice(tone, text):
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    box.add_css_class("change-preview-notice")
    box.add_css_class(tone)
    icon = Gtk.Image.new_from_icon_name(_NOTICE_ICONS.get(tone, "dialog-information-symbolic"))
    icon.set_valign(Gtk.Align.START)
    icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
    box.append(icon)
    box.append(_label(text))
    return box


class ChangePreviewDialog(Adw.AlertDialog):
    """Review a ``history.Preview``; *on_confirm(include_remote)* runs it."""

    def __init__(self, preview, confirm_label, on_confirm, *, remote_default=True):
        super().__init__(heading="", body="")
        self._on_confirm = on_confirm
        self.update_property([Gtk.AccessibleProperty.LABEL], [preview.heading])

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        deletes = any(change.status == "D" for change in preview.files)
        icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic" if deletes else "dialog-question-symbolic")
        icon.set_pixel_size(28)
        icon.set_valign(Gtk.Align.START)
        icon.add_css_class("status-warning" if deletes else "status-accent")
        icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        header.append(icon)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        heading = _label(preview.heading, "title-3")
        heading.set_accessible_role(Gtk.AccessibleRole.HEADING)
        titles.append(heading)
        if preview.summary:
            titles.append(_label(preview.summary, "dim-label"))
        header.append(titles)
        content.append(header)

        for tone, text in preview.notices:
            content.append(_notice(tone, text))

        if preview.steps:
            content.append(_section_title(_("What will be done")))
            steps = _boxed_list()
            for step in preview.steps:
                steps.append(_step_row(step))
            content.append(steps)

        if preview.files:
            # The whole dialog scrolls; a nested scroller would squeeze the list to a row or two.
            content.append(_section_title(f"{preview.files_title} ({len(preview.files)})"))
            files = _boxed_list()
            for change in preview.files[:_MAX_FILES]:
                files.append(_file_row(change))
            if len(preview.files) > _MAX_FILES:
                more = _label(_("… and {0} more").format(len(preview.files) - _MAX_FILES), "dim-label")
                more.add_css_class("change-preview-row")
                files.append(more)
            content.append(files)

        self._remote_switch = None
        if preview.remote_steps:
            remote = Adw.PreferencesGroup()
            self._remote_switch = Adw.SwitchRow()
            self._remote_switch.set_title(preview.remote_title)
            self._remote_switch.set_subtitle(_("Rewrites the branch on GitHub only if nobody published to it since."))
            self._remote_switch.set_active(remote_default)
            remote.add(self._remote_switch)
            content.append(remote)
            remote_steps = _boxed_list()
            for step in preview.remote_steps:
                remote_steps.append(_step_row(step))
            content.append(remote_steps)

        page = Gtk.ScrolledWindow()
        page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page.set_max_content_height(560)
        page.set_propagate_natural_height(True)
        page.set_child(content)
        self.set_extra_child(page)
        self.set_follows_content_size(False)
        self.set_content_width(720)

        self.add_response("cancel", _("Cancel"))
        self.add_response("apply", confirm_label)
        self.set_response_appearance(
            "apply", Adw.ResponseAppearance.DESTRUCTIVE if deletes else Adw.ResponseAppearance.SUGGESTED
        )
        self.set_default_response("cancel" if deletes else "apply")
        self.set_close_response("cancel")
        self.connect("response", self._on_response)

    @property
    def include_remote(self) -> bool:
        return bool(self._remote_switch and self._remote_switch.get_active())

    def _on_response(self, _dialog, response):
        # Adw.AlertDialog closes itself after any response; closing it here
        # again makes libadwaita abort the whole application.
        if response == "apply":
            self._on_confirm(self.include_remote)
