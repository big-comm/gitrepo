#
# gui/widgets/history_widget.py - Build history widget
#

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gitrepo.build_iso.core.config import VALID_DISTROS, VALID_KERNELS, edition_display_name
from gitrepo.build_iso.core.history_store import BuildHistoryStore
from gitrepo.common.desktop_launch import open_folder
from gitrepo.common.translation import _
from gi.repository import Adw, Gdk, Gtk

from gitrepo.common.page_hero import BuildIsoPageHero as PageHero
from gitrepo.common.page_layout import page_body


def format_size(size_bytes: int) -> str:
    """Return a human-sized ISO measurement, or an empty string when unknown."""
    if size_bytes <= 0:
        return ""
    gigabytes = size_bytes / (1024**3)
    if gigabytes >= 1:
        return _("{0:.1f} GB").format(gigabytes)
    return _("{0:.0f} MB").format(size_bytes / (1024**2))


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
                _("Generated ISOs"),
                _("Review outcomes and durations, then open the ISO folder or the terminal log of a build."),
            )
        )

        clamp, page_content = page_body()
        self.append(clamp)

        # Nothing to review yet is a state of its own, not an empty list row.
        self.empty_state = Adw.StatusPage()
        self.empty_state.set_icon_name("build-iso-history")
        self.empty_state.set_title(_("No builds yet"))
        self.empty_state.set_description(
            _("Finished and failed builds are listed here with their ISO, duration, and terminal log.")
        )
        self.empty_state.set_vexpand(False)
        page_content.append(self.empty_state)

        self.history_group = Adw.PreferencesGroup()
        page_content.append(self.history_group)

        # Clear history button
        self.clear_group = Adw.PreferencesGroup()
        self.clear_group.set_margin_top(24)
        page_content.append(self.clear_group)

        clear_row = Adw.ActionRow()
        clear_row.set_title(_("Clear History"))
        clear_row.set_subtitle(_("Delete the local history log; generated ISO files remain untouched"))
        clear_btn = Gtk.Button()
        clear_btn.set_label(_("Clear"))
        clear_btn.set_valign(Gtk.Align.CENTER)
        clear_btn.add_css_class("destructive-action")
        clear_btn.connect("clicked", self._on_clear_clicked)
        clear_row.add_suffix(clear_btn)
        self.clear_group.add(clear_row)

    def refresh(self):
        """Reload history from file"""
        history = self._load_history()

        child = self.history_group.get_first_child()
        rows_to_remove = []
        while child:
            if isinstance(child, Adw.ActionRow):
                rows_to_remove.append(child)
            child = child.get_next_sibling()
        for row in rows_to_remove:
            self.history_group.remove(row)

        self.empty_state.set_visible(not history)
        self.history_group.set_visible(bool(history))
        self.clear_group.set_visible(bool(history))
        if not history:
            return

        # Add history entries (newest first)
        for entry in reversed(history[-50:]):
            self.history_group.add(self._create_entry_row(entry))

    def _create_entry_row(self, entry: dict) -> Adw.ActionRow:
        row = Adw.ActionRow()
        # Every build of the same edition shares its configuration, so leading
        # with it makes the list unreadable: the date and the outcome are what
        # tell one entry from another.
        row.set_title(_("{0} • {1}").format(entry.get("date", "?"), self._outcome_text(entry)))
        row.set_subtitle(self._entry_subtitle(entry))
        row.set_subtitle_lines(0)

        success = entry.get("success", False)
        result_status = entry.get("status", "succeeded" if success else "failed")
        icon_name = "gitrepo-status-ready-symbolic" if success else "gitrepo-status-error-symbolic"
        css_class = "status-ok" if success else "status-error"
        if result_status == "cancelled":
            icon_name, css_class = "gitrepo-status-warning-symbolic", "status-warning"
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.add_css_class(css_class)
        row.add_prefix(icon)

        iso_path = entry.get("iso_path", "")
        if iso_path:
            copy_button = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
            copy_button.set_valign(Gtk.Align.CENTER)
            copy_button.set_tooltip_text(_("Copy the ISO path"))
            copy_button.connect("clicked", self._on_copy_path, iso_path)
            row.add_suffix(copy_button)

        log_path = entry.get("log_path", "")
        if log_path and os.path.exists(log_path):
            log_button = Gtk.Button.new_from_icon_name("text-x-generic-symbolic")
            log_button.set_valign(Gtk.Align.CENTER)
            log_button.set_tooltip_text(_("Open the terminal log of this build"))
            log_button.connect("clicked", self._on_open_path, log_path)
            row.add_suffix(log_button)

        if iso_path and os.path.exists(iso_path):
            open_btn = Gtk.Button.new_from_icon_name("folder-open-symbolic")
            open_btn.set_valign(Gtk.Align.CENTER)
            open_btn.set_tooltip_text(_("Open folder"))
            open_btn.connect("clicked", self._on_open_path, os.path.dirname(iso_path))
            row.add_suffix(open_btn)
        return row

    @staticmethod
    def _outcome_text(entry: dict) -> str:
        success = entry.get("success", False)
        result_status = entry.get("status", "succeeded" if success else "failed")
        return _("Cancelled") if result_status == "cancelled" else _("Success") if success else _("Failed")

    @staticmethod
    def _entry_subtitle(entry: dict) -> str:
        success = entry.get("success", False)
        distro = entry.get("distro", "?")
        kernel = entry.get("kernel", "?")
        facts = [
            _("{0} {1} • kernel {2}").format(
                VALID_DISTROS.get(distro, distro),
                edition_display_name(entry.get("edition", "?")),
                # "(recommended)" advises a choice; a finished build only has
                # the kernel it used.
                VALID_KERNELS.get(kernel, kernel).partition(" (")[0],
            ),
            _("{0} min").format(int(entry.get("duration", 0)) // 60),
        ]

        iso_path = entry.get("iso_path", "")
        if iso_path:
            size_text = format_size(int(entry.get("iso_size", 0)))
            facts.append(f"{os.path.basename(iso_path)}{f' ({size_text})' if size_text else ''}")
            if not os.path.exists(iso_path):
                facts.append(_("file no longer on disk"))
        manifest = entry.get("manifest") or {}
        if manifest:
            facts.append(
                _("built from {0}").format(
                    ", ".join(f"{name} {revision[:12]}" for name, revision in sorted(manifest.items()))
                )
            )
        error = entry.get("error", "")
        if not success and error:
            facts.append(error)
        return " • ".join(fact for fact in facts if fact)

    def _load_history(self):
        return self.history_store.load()

    def _on_clear_clicked(self, button):
        dialog = Adw.AlertDialog(
            heading=_("Clear the list of generated ISOs?"),
            body=_("This will remove all build history entries. This cannot be undone."),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("clear", _("Clear"))
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_clear_confirmed)
        dialog.present(self.get_root())

    def _report_storage_failure(self) -> None:
        """Say the history could not be written rather than leaving it unchanged."""
        root = self.get_root()
        if root and hasattr(root, "show_toast"):
            root.show_toast(_("Could not update the build history. Check config permissions, then try again."))

    def _on_clear_confirmed(self, dialog, response):
        if response == "clear":
            if self.history_store.clear():
                self.refresh()
            else:
                # Silence left the list unchanged with no explanation.
                self._report_storage_failure()

    def _on_copy_path(self, button, iso_path):
        display = Gdk.Display.get_default()
        if display is None:
            return
        display.get_clipboard().set(iso_path)
        root = self.get_root()
        if root and hasattr(root, "show_toast"):
            root.show_toast(_("ISO path copied to the clipboard"))

    def _on_open_path(self, button, path):
        open_folder(button, path)

    @staticmethod
    def add_entry(entry: dict):
        """Add a build entry to history"""
        return BuildHistoryStore().add(entry)
