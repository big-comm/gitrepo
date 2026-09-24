#
# gui/dialogs/package_selection_dialog.py - Choose which packages of a repository to build
#

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk, Pango
from gitrepo.common.translation import _

# Fixed, so sixteen packages scroll inside the dialog instead of growing it
# past the screen, and wide enough that a module name and its description
# stay on one line each.
_DIALOG_WIDTH = 600
_DIALOG_HEIGHT = 620


def _package_name_label(choice):
    # A directory is shown exactly as it is named: with mnemonics or markup
    # on, linux-big-tp_smapi would lose its underscore and read "tpsmapi".
    label = Gtk.Label(label=choice.directory, xalign=0)
    label.set_use_underline(False)
    label.set_use_markup(False)
    label.set_ellipsize(Pango.EllipsizeMode.END)
    label.add_css_class("build-package-package-name")
    return label


def _package_description_label(choice):
    label = Gtk.Label(label=choice.description or _("No description in the PKGBUILD"), xalign=0)
    label.set_use_underline(False)
    label.set_use_markup(False)
    label.set_wrap(True)
    label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    label.add_css_class("dim-label")
    label.add_css_class("build-package-package-description")
    return label


class PackageSelectionDialog(Adw.Dialog):
    """Mark the packages of a multi-package repository that should be built.

    *on_done* receives the directories to build, or None when cancelled. It
    is called exactly once, whichever way the dialog closes.
    """

    def __init__(self, selection, on_done):
        super().__init__(title=_("Build packages"))
        self.selection = selection
        self._on_done = on_done
        self._finished = False
        self._checks = {}
        self._updating = False

        self.set_follows_content_size(False)
        self.set_content_width(_DIALOG_WIDTH)
        self.set_content_height(_DIALOG_HEIGHT)
        self.add_css_class("build-package-package-dialog")

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(False)
        header.set_show_end_title_buttons(False)
        toolbar_view.add_top_bar(header)
        toolbar_view.set_content(self._build_content())
        toolbar_view.add_bottom_bar(self._build_footer())
        self.set_child(toolbar_view)

        self.connect("closed", self._on_closed)
        self._refresh()

    def _build_content(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.add_css_class("build-package-package-content")

        intro = Gtk.Label(
            label=_("This repository holds several packages. Mark the ones that should be built."),
            xalign=0,
            wrap=True,
        )
        content.append(intro)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for text, callback in ((_("Select all"), self._on_select_all), (_("Select none"), self._on_select_none)):
            button = Gtk.Button(label=text)
            button.set_use_underline(False)
            button.connect("clicked", callback)
            actions.append(button)
        self.counter = Gtk.Label(xalign=1, hexpand=True)
        self.counter.add_css_class("build-package-package-counter")
        actions.append(self.counter)
        content.append(actions)

        self.warning = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.warning.set_child(self._build_warning())
        content.append(self.warning)

        package_list = Gtk.ListBox()
        package_list.set_selection_mode(Gtk.SelectionMode.NONE)
        package_list.add_css_class("boxed-list")
        package_list.add_css_class("build-package-package-list")
        for choice in self.selection.choices:
            package_list.append(self._build_row(choice))
        package_list.connect("row-activated", self._on_row_activated)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_child(package_list)
        content.append(scrolled)
        return content

    def _build_warning(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.add_css_class("build-package-package-warning")
        text = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        icon.set_valign(Gtk.Align.START)
        text.append(icon)
        label = Gtk.Label(label=self.selection.order_warning_text() if self.selection.main else "", xalign=0)
        label.set_wrap(True)
        label.set_hexpand(True)
        text.append(label)
        box.append(text)
        if self.selection.main:
            only_main = Gtk.Button(label=self.selection.only_main_label(), halign=Gtk.Align.END)
            only_main.set_use_underline(False)
            only_main.connect("clicked", lambda _button: self._finish([self.selection.main]))
            box.append(only_main)
        return box

    def _build_row(self, choice):
        check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
        check.update_property([Gtk.AccessibleProperty.LABEL], [choice.directory])
        check.connect("toggled", self._on_check_toggled, choice.directory)
        self._checks[choice.directory] = check

        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
        labels.append(_package_name_label(choice))
        labels.append(_package_description_label(choice))

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        content.add_css_class("build-package-package-row")
        content.append(check)
        content.append(labels)

        row = Gtk.ListBoxRow(activatable=True)
        row.set_child(content)
        row.package_directory = choice.directory
        return row

    def _build_footer(self):
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.END)
        footer.add_css_class("build-package-package-footer")
        cancel = Gtk.Button(label=_("Cancel"))
        cancel.set_use_underline(False)
        cancel.connect("clicked", lambda _button: self._finish(None))
        footer.append(cancel)
        self.build_button = Gtk.Button(label=_("Build selected packages"))
        self.build_button.set_use_underline(False)
        self.build_button.add_css_class("suggested-action")
        self.build_button.connect("clicked", self._on_build_clicked)
        footer.append(self.build_button)
        return footer

    def _refresh(self):
        self._updating = True
        for directory, check in self._checks.items():
            check.set_active(self.selection.is_selected(directory))
        self._updating = False
        self.counter.set_label(self.selection.count_text())
        self.build_button.set_sensitive(self.selection.can_confirm)
        self.warning.set_reveal_child(self.selection.needs_order_warning)

    def _on_check_toggled(self, check, directory):
        if self._updating:
            return
        self.selection.set_selected(directory, check.get_active())
        self._refresh()

    def _on_row_activated(self, _list_box, row):
        self.selection.toggle(row.package_directory)
        self._refresh()

    def _on_select_all(self, _button):
        self.selection.select_all()
        self._refresh()

    def _on_select_none(self, _button):
        self.selection.clear()
        self._refresh()

    def _on_build_clicked(self, _button):
        if not self.selection.can_confirm:
            return
        if not self.selection.needs_order_warning:
            self._finish(self.selection.selected_directories())
            return
        # Building the modules alongside the kernel compiles them against the
        # headers published before it, so this is never done without asking.
        alert = Adw.AlertDialog(heading=_("Build order"), body=self.selection.order_warning_text())
        alert.add_response("back", _("Back"))
        alert.add_response("all", _("Build all anyway"))
        # Responses always read "_" as a mnemonic; doubling it keeps it literal.
        alert.add_response("main", self.selection.only_main_label().replace("_", "__"))
        alert.set_response_appearance("main", Adw.ResponseAppearance.SUGGESTED)
        alert.set_default_response("main")
        alert.set_close_response("back")
        alert.connect("response", self._on_order_response)
        alert.present(self)

    def _on_order_response(self, _alert, response):
        if response == "main":
            self._finish([self.selection.main])
        elif response == "all":
            self._finish(self.selection.selected_directories())

    def _finish(self, directories):
        if self._finished:
            return
        self._finished = True
        self._on_done(directories)
        self.force_close()

    def _on_closed(self, _dialog):
        if not self._finished:
            self._finished = True
            self._on_done(None)
