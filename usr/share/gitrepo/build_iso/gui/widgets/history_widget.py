#
# gui/widgets/history_widget.py - Build history widget
#

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gitrepo.build_iso.core.history_store import BuildHistoryStore
from gitrepo.common.translation import _
from gi.repository import Adw, Gtk

from gitrepo.common.page_hero import BuildIsoPageHero as PageHero


class HistoryWidget(Gtk.Box):
    """Build history page"""

    __gtype_name__ = "HistoryWidget"

    def __init__(self, settings):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.settings = settings
        self.history_store = BuildHistoryStore()

        self._create_ui()
        self.refresh()

    def _create_ui(self):
        """Create history UI"""

        self.append(
            PageHero(
                "build-iso-history",
                _("Build History"),
                _("Review outcomes and durations, then open the folder of a completed ISO."),
            )
        )

        page_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        page_content.add_css_class("page-frame")
        self.append(page_content)

        self.history_group = Adw.PreferencesGroup()
        page_content.append(self.history_group)

        # Empty state
        self.empty_row = Adw.ActionRow()
        self.empty_row.set_title(_("No builds yet"))
        self.empty_row.set_subtitle(_("Build history will appear here after your first build"))
        icon = Gtk.Image.new_from_icon_name("build-iso-history")
        icon.set_pixel_size(24)
        self.empty_row.add_prefix(icon)
        self.history_group.add(self.empty_row)

        # Clear history button
        clear_group = Adw.PreferencesGroup()
        clear_group.set_margin_top(24)
        page_content.append(clear_group)

        clear_row = Adw.ActionRow()
        clear_row.set_title(_("Clear History"))
        clear_row.set_subtitle(_("Delete the local history log; generated ISO files remain untouched"))
        clear_btn = Gtk.Button()
        clear_btn.set_label(_("Clear"))
        clear_btn.set_valign(Gtk.Align.CENTER)
        clear_btn.add_css_class("destructive-action")
        clear_btn.connect("clicked", self._on_clear_clicked)
        clear_row.add_suffix(clear_btn)
        clear_group.add(clear_row)

    def refresh(self):
        """Reload history from file"""
        history = self._load_history()

        # Remove existing rows (except empty_row)
        child = self.history_group.get_first_child()
        rows_to_remove = []
        while child:
            if child != self.empty_row and isinstance(child, Adw.ActionRow):
                rows_to_remove.append(child)
            child = child.get_next_sibling()
        for row in rows_to_remove:
            self.history_group.remove(row)

        if not history:
            self.empty_row.set_visible(True)
            return

        self.empty_row.set_visible(False)

        # Add history entries (newest first)
        for entry in reversed(history[-50:]):
            row = Adw.ActionRow()
            distro = entry.get("distro", "?")
            edition = entry.get("edition", "?")
            kernel = entry.get("kernel", "?")
            row.set_title(f"{distro} - {edition} ({kernel})")

            date = entry.get("date", "?")
            success = entry.get("success", False)
            result_status = entry.get("status", "succeeded" if success else "failed")
            duration_s = entry.get("duration", 0)
            duration_min = duration_s // 60
            status = _("Cancelled") if result_status == "cancelled" else _("Success") if success else _("Failed")
            row.set_subtitle(f"{date} | {status} | {duration_min} min")

            if success:
                icon = Gtk.Image.new_from_icon_name("gitrepo-status-ready-symbolic")
                icon.add_css_class("status-ok")
            else:
                icon = Gtk.Image.new_from_icon_name("gitrepo-status-error-symbolic")
                icon.add_css_class("status-error")
            row.add_prefix(icon)

            iso_path = entry.get("iso_path", "")
            if iso_path and os.path.exists(iso_path):
                open_btn = Gtk.Button()
                open_btn.set_icon_name("folder-open-symbolic")
                open_btn.set_valign(Gtk.Align.CENTER)
                open_btn.set_tooltip_text(_("Open folder"))
                open_btn.connect("clicked", self._on_open_folder, os.path.dirname(iso_path))
                row.add_suffix(open_btn)

            self.history_group.add(row)

    def _load_history(self):
        return self.history_store.load()

    def _on_clear_clicked(self, button):
        dialog = Adw.AlertDialog(
            heading=_("Clear Build History?"),
            body=_("This will remove all build history entries. This cannot be undone."),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("clear", _("Clear"))
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_clear_confirmed)
        dialog.present(self.get_root())

    def _on_clear_confirmed(self, dialog, response):
        if response == "clear":
            if self.history_store.clear():
                self.refresh()

    def _on_open_folder(self, button, folder_path):
        from gitrepo.common import child_process as subprocess

        subprocess.Popen(["xdg-open", folder_path])

    @staticmethod
    def add_entry(entry: dict):
        """Add a build entry to history"""
        return BuildHistoryStore().add(entry)
