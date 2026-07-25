#
# gui/widgets/container_widget.py - Container management widget
#

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gitrepo.build_iso.core.config import CONTAINER_IMAGE
from gitrepo.build_iso.core.container_manager import ContainerManager, ContainerStatus
from gitrepo.common.translation import _
from gi.repository import Adw, GLib, GObject, Gtk

from gitrepo.common.page_hero import BuildIsoPageHero as PageHero
from gitrepo.common.page_layout import page_body


class ContainerWidget(Gtk.Box):
    """Container engine management page"""

    __gtype_name__ = "ContainerWidget"

    __gsignals__ = {
        "refresh-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, settings):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.settings = settings
        self.container_mgr = ContainerManager()

        self._create_ui()

    def _create_ui(self):
        """Create container management UI"""

        self.append(
            PageHero(
                "build-iso-environment",
                _("Prepare the build environment"),
                _("Inspect the container runtime, update the required image, and clean stopped build containers."),
            )
        )

        clamp, page_content = page_body()
        self.append(clamp)

        # ── Engine Info ──
        info_group = Adw.PreferencesGroup()
        info_group.set_title(_("Container Engine"))
        info_group.set_description(_("Runtime diagnostics used by ISO builds."))
        page_content.append(info_group)

        self.engine_row = Adw.ActionRow()
        self.engine_row.set_title(_("Engine"))
        self.engine_row.set_subtitle(_("Detecting..."))
        info_group.add(self.engine_row)

        self.driver_row = Adw.ActionRow()
        self.driver_row.set_title(_("Storage Driver"))
        self.driver_row.set_subtitle(_("Checking..."))
        info_group.add(self.driver_row)

        self.version_row = Adw.ActionRow()
        self.version_row.set_title(_("Version"))
        self.version_row.set_subtitle(_("Checking..."))
        info_group.add(self.version_row)

        # ── Image Management ──
        image_group = Adw.PreferencesGroup()
        image_group.set_title(_("Build Image"))
        image_group.set_description(_("Required container image: {0}").format(CONTAINER_IMAGE))
        image_group.set_margin_top(24)
        page_content.append(image_group)

        self.image_status_row = Adw.ActionRow()
        self.image_status_row.set_title(_("Image Status"))
        self.image_status_row.set_subtitle(_("Checking..."))
        image_group.add(self.image_status_row)

        # Pull image button
        pull_row = Adw.ActionRow()
        pull_row.set_title(_("Pull Latest Image"))
        pull_row.set_subtitle(_("Download or update the build container image"))

        self.pull_button = Gtk.Button()
        self.pull_button.set_label(_("Pull Image"))
        self.pull_button.set_valign(Gtk.Align.CENTER)
        self.pull_button.add_css_class("suggested-action")
        self.pull_button.connect("clicked", self._on_pull_clicked)
        pull_row.add_suffix(self.pull_button)
        image_group.add(pull_row)

        # ── Maintenance ──
        maint_group = Adw.PreferencesGroup()
        maint_group.set_title(_("Maintenance"))
        maint_group.set_description(_("Removes stopped build containers without deleting images or package data."))
        maint_group.set_margin_top(24)
        page_content.append(maint_group)

        # Cleanup containers
        cleanup_row = Adw.ActionRow()
        cleanup_row.set_title(_("Cleanup Old Containers"))
        cleanup_row.set_subtitle(_("Remove stopped build containers"))
        self.cleanup_button = Gtk.Button()
        self.cleanup_button.set_label(_("Clean"))
        self.cleanup_button.set_valign(Gtk.Align.CENTER)
        self.cleanup_button.connect("clicked", self._on_cleanup_clicked)
        cleanup_row.add_suffix(self.cleanup_button)
        maint_group.add(cleanup_row)

        self.storage_notice_row = Adw.ActionRow()
        self.storage_notice_row.set_title(_("Docker storage is managed by the system"))
        self.storage_notice_row.set_subtitle(
            _("GitRepo reports the active driver but never changes it or removes Docker data.")
        )
        warning_icon = Gtk.Image.new_from_icon_name("gitrepo-status-warning-symbolic")
        warning_icon.add_css_class("status-warning")
        self.storage_notice_row.add_prefix(warning_icon)
        self.storage_notice_row.set_visible(False)
        maint_group.add(self.storage_notice_row)

        # Pull progress
        self.pull_progress_group = Adw.PreferencesGroup()
        self.pull_progress_group.set_title(_("Pull Progress"))
        self.pull_progress_group.set_margin_top(24)
        self.pull_progress_group.set_visible(False)
        page_content.append(self.pull_progress_group)

        self.pull_progress_bar = Gtk.ProgressBar()
        self.pull_progress_bar.set_show_text(True)
        self.pull_progress_group.add(self.pull_progress_bar)

        self.pull_log_label = Gtk.Label()
        self.pull_log_label.set_halign(Gtk.Align.START)
        self.pull_log_label.add_css_class("dim-label")
        self.pull_log_label.add_css_class("caption")
        self.pull_log_label.set_wrap(True)
        self.pull_log_label.set_max_width_chars(80)
        self.pull_progress_group.add(self.pull_log_label)

    def set_checking(self) -> None:
        """Show pending state while the shared environment probe runs."""
        self.engine_row.set_subtitle(_("Detecting..."))
        self.driver_row.set_subtitle(_("Checking..."))
        self.version_row.set_subtitle(_("Checking..."))
        self.image_status_row.set_subtitle(_("Checking..."))
        self.pull_button.set_sensitive(False)
        self.cleanup_button.set_sensitive(False)

    def apply_status(self, manager: ContainerManager, status: ContainerStatus) -> None:
        """Render the shared environment snapshot."""
        self.container_mgr = manager
        self.pull_button.set_sensitive(status.is_engine_ready)
        self.cleanup_button.set_sensitive(status.is_engine_ready)

        if status.is_engine_ready and status.engine:
            self.engine_row.set_subtitle(status.engine.capitalize())
            self.version_row.set_subtitle(status.version)
        else:
            self.engine_row.set_subtitle(_("Unavailable — {0}").format(status.engine_error))
            self.version_row.set_subtitle(_("Not checked — start or install the engine, then refresh."))

        if status.driver:
            self.driver_row.set_subtitle(status.driver)
            if status.driver == "btrfs":
                self.driver_row.add_css_class("warning")
                self.storage_notice_row.set_visible(True)
            else:
                self.driver_row.remove_css_class("warning")
                self.storage_notice_row.set_visible(False)
        else:
            detail = status.driver_error or _("Not checked — start or install the engine, then refresh.")
            self.driver_row.set_subtitle(detail)
            self.driver_row.remove_css_class("warning")
            self.storage_notice_row.set_visible(False)

        if status.is_image_available:
            self.image_status_row.set_subtitle(
                _("Available ({0:.1f} GB) - {1}").format(status.image_size_gb, status.image_created[:10])
            )
        else:
            detail = status.image_error or _("Not checked — start or install the engine, then refresh.")
            self.image_status_row.set_subtitle(detail)

    def _on_pull_clicked(self, button):
        """Start pulling container image"""
        self.pull_button.set_sensitive(False)
        self.pull_progress_group.set_visible(True)
        self.pull_progress_bar.set_fraction(0.0)
        self.pull_progress_bar.set_text(_("Starting download..."))

        thread = threading.Thread(target=self._pull_worker, daemon=True)
        thread.start()

    def _pull_worker(self):
        def progress_callback(line):
            GLib.idle_add(self._update_pull_progress, line)

        success = self.container_mgr.pull_image(CONTAINER_IMAGE, progress_callback)
        GLib.idle_add(self._pull_completed, success)

    def _update_pull_progress(self, line):
        self.pull_log_label.set_text(line)
        self.pull_progress_bar.pulse()
        return False

    def _pull_completed(self, success):
        self.pull_button.set_sensitive(True)
        if success:
            self.pull_progress_bar.set_fraction(1.0)
            self.pull_progress_bar.set_text(_("Image pulled successfully"))
        else:
            self.pull_progress_bar.set_text(_("Pull failed"))
        self.emit("refresh-requested")
        return False

    def _on_cleanup_clicked(self, button):
        button.set_sensitive(False)
        thread = threading.Thread(target=self._prepare_cleanup, args=(button,), daemon=True)
        thread.start()

    def _prepare_cleanup(self, button):
        container_ids = self.container_mgr.list_stopped_containers(CONTAINER_IMAGE)
        GLib.idle_add(self._show_cleanup_confirmation, button, container_ids)

    def _show_cleanup_confirmation(self, button, container_ids):
        button.set_sensitive(True)
        if not container_ids:
            return False
        dialog = Adw.AlertDialog(
            heading=_("Remove {0} stopped build containers?").format(len(container_ids)),
            body=_(
                "Only stopped containers created from {0} will be removed. Images and Docker storage are kept."
            ).format(CONTAINER_IMAGE),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("remove", _("Remove Stopped Containers"))
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_cleanup_confirmed, container_ids)
        dialog.present(self.get_root())
        return False

    def _on_cleanup_confirmed(self, dialog, response, container_ids):
        if response == "remove":
            thread = threading.Thread(target=self._cleanup_worker, args=(container_ids,), daemon=True)
            thread.start()

    def _cleanup_worker(self, container_ids):
        self.container_mgr.remove_stopped_containers(container_ids)
        GLib.idle_add(self.emit, "refresh-requested")
