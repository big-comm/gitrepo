#
# gui/widgets/dashboard_widget.py - Dashboard/overview widget
#

import os
import shutil

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gitrepo.build_iso.core.config import CONTAINER_IMAGE
from gitrepo.build_iso.core.container_manager import ContainerStatus
from gitrepo.build_iso.core.history_store import BuildHistoryStore
from gitrepo.common.translation import _
from gi.repository import Adw, GObject, Gtk, Pango

from gitrepo.common.page_hero import BuildIsoPageHero as PageHero, is_large_text_enabled


class DashboardWidget(Gtk.Box):
    """Dashboard with status cards and quick actions"""

    __gtype_name__ = "DashboardWidget"

    __gsignals__ = {
        "navigate-to": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, settings):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.settings = settings

        self._create_ui()

    def _create_ui(self):
        """Create dashboard UI"""

        hero = PageHero(
            "build-iso-dashboard",
            _("Build ISO with confidence"),
            _("Checking the build environment…"),
        )
        self.hero_subtitle = hero.description_label
        self.append(hero)

        dashboard_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        dashboard_content.add_css_class("page-frame")
        self.append(dashboard_content)

        dashboard_content.append(self._create_learning_section())
        dashboard_content.append(self._create_status_section())
        dashboard_content.append(self._create_actions_section())
        dashboard_content.append(self._create_recent_section())

    def _create_learning_section(self):
        learning_list = Gtk.ListBox()
        learning_list.set_selection_mode(Gtk.SelectionMode.NONE)
        learning_list.add_css_class("premium-list")
        learning_row = Adw.ActionRow(
            title=_("Create an installable Linux system image"),
            subtitle=_(
                "An ISO is the file used to install or test a system from a USB drive or virtual machine. "
                "Choose a distribution profile and package channels; the application builds them in an isolated "
                "container and saves the finished ISO in your output folder."
            ),
        )
        learning_row.set_subtitle_lines(0)
        learning_icon = Gtk.Image.new_from_icon_name("help-about-symbolic")
        learning_icon.set_pixel_size(24)
        learning_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        learning_row.add_prefix(learning_icon)
        learning_list.append(learning_row)
        return learning_list

    def _create_status_section(self):
        status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        status_heading = Gtk.Label(label=_("System Status"), xalign=0)
        status_heading.add_css_class("section-heading")
        status_box.append(status_heading)
        status_grid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        status_grid.set_homogeneous(True)
        self.engine_card, self.engine_detail, self.engine_status = self._create_status_card(
            "build-iso-engine", _("Container Engine")
        )
        status_grid.append(self.engine_card)
        self.image_card, self.image_detail, self.image_status = self._create_status_card(
            "build-iso-build-image", _("Build Image")
        )
        status_grid.append(self.image_card)
        self.disk_card, self.disk_detail, self.disk_status = self._create_status_card(
            "build-iso-storage", _("Disk Space")
        )
        status_grid.append(self.disk_card)
        gtk_settings = Gtk.Settings.get_default()
        if gtk_settings is not None:

            def sync_status_layout(*_args) -> None:
                status_grid.set_orientation(
                    Gtk.Orientation.VERTICAL if is_large_text_enabled(gtk_settings) else Gtk.Orientation.HORIZONTAL
                )

            gtk_settings.connect("notify::gtk-font-name", sync_status_layout)
            gtk_settings.connect("notify::gtk-xft-dpi", sync_status_layout)
            sync_status_layout()
        status_box.append(status_grid)
        return status_box

    def _create_actions_section(self):
        actions_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        actions_heading = Gtk.Label(label=_("Choose the next step"), xalign=0)
        actions_heading.add_css_class("section-heading")
        actions_box.append(actions_heading)
        actions_flow = Gtk.FlowBox()
        actions_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        actions_flow.set_min_children_per_line(1)
        actions_flow.set_max_children_per_line(3)
        actions_flow.set_homogeneous(True)
        actions_flow.set_column_spacing(12)
        actions_flow.set_row_spacing(12)
        actions_flow.add_css_class("build-iso-destinations")
        actions_flow.insert(
            self._create_destination_card(
                "build-iso-profiles",
                _("Choose a system profile"),
                _(
                    "A profile defines the desktop, packages, services, and defaults included in the ISO. "
                    "Choosing one opens the build configuration."
                ),
                "profiles",
            ),
            -1,
        )
        actions_flow.insert(
            self._create_destination_card(
                "build-iso-environment",
                _("Prepare the build environment"),
                _("Check Docker or Podman, download the build image, and remove stopped build containers."),
                "container",
            ),
            -1,
        )
        actions_flow.insert(
            self._create_destination_card(
                "build-iso-history",
                _("Review generated ISOs"),
                _("See which builds succeeded, how long they took, and where each finished ISO was saved."),
                "history",
            ),
            -1,
        )
        actions_box.append(actions_flow)
        return actions_box

    def _create_recent_section(self):
        recent_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        recent_heading = Gtk.Label(label=_("Last Build"), xalign=0)
        recent_heading.add_css_class("section-heading")
        recent_box.append(recent_heading)
        recent_list = Gtk.ListBox()
        recent_list.set_selection_mode(Gtk.SelectionMode.NONE)
        recent_list.add_css_class("premium-list")
        recent_box.append(recent_list)

        self.last_build_row = Adw.ActionRow()
        self.last_build_row.set_title(_("No builds yet"))
        self.last_build_row.set_subtitle(_("Choose a profile, configure the system, and start your first ISO build."))
        recent_icon = Gtk.Image.new_from_icon_name("build-iso-history")
        recent_icon.set_pixel_size(24)
        recent_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self.last_build_row.add_prefix(recent_icon)
        recent_list.append(self.last_build_row)
        return recent_box

    def _create_status_card(self, icon_name, title):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("build-iso-status-card")

        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        context_icon = Gtk.Image.new_from_icon_name(icon_name)
        context_icon.set_pixel_size(28)
        context_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        heading.append(context_icon)
        title_label = Gtk.Label(label=title, xalign=0)
        title_label.add_css_class("heading")
        title_label.set_hexpand(True)
        title_label.set_wrap(True)
        title_label.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        title_label.set_width_chars(1)
        heading.append(title_label)
        state_icon = Gtk.Image.new_from_icon_name("gitrepo-status-checking-symbolic")
        state_icon.set_pixel_size(20)
        state_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        heading.append(state_icon)
        card.append(heading)

        detail = Gtk.Label(label=_("Checking..."), xalign=0)
        detail.add_css_class("dim-label")
        detail.add_css_class("caption")
        detail.set_wrap(True)
        detail.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        detail.set_width_chars(1)
        detail.set_yalign(0)
        card.append(detail)
        return card, detail, state_icon

    def _create_destination_card(self, icon_name, title, subtitle, page_id):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.set_halign(Gtk.Align.FILL)

        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(28)
        icon.set_halign(Gtk.Align.START)
        icon.set_valign(Gtk.Align.CENTER)
        icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        heading.append(icon)

        title_label = Gtk.Label(label=title, xalign=0)
        title_label.add_css_class("heading")
        title_label.set_hexpand(True)
        title_label.set_valign(Gtk.Align.CENTER)
        title_label.set_wrap(True)
        title_label.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        title_label.set_width_chars(1)
        title_label.set_max_width_chars(20)
        heading.append(title_label)
        content.append(heading)

        subtitle_label = Gtk.Label(label=subtitle, xalign=0)
        subtitle_label.add_css_class("dim-label")
        subtitle_label.add_css_class("caption")
        subtitle_label.set_wrap(True)
        subtitle_label.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        subtitle_label.set_width_chars(1)
        subtitle_label.set_max_width_chars(22)
        subtitle_label.set_yalign(0)
        content.append(subtitle_label)

        button = Gtk.Button(child=content)
        button.add_css_class("build-iso-destination-card")
        button.set_tooltip_text(title)
        button.update_property([Gtk.AccessibleProperty.LABEL], [title])
        button.connect("clicked", lambda _button: self.emit("navigate-to", page_id))
        return button

    def set_checking(self) -> None:
        """Show pending state while the shared environment probe runs."""
        self._set_checking_state()

    def _set_checking_state(self):
        self.hero_subtitle.set_text(_("Checking the build environment…"))
        for detail in (self.engine_detail, self.disk_detail):
            detail.set_text(_("Checking..."))
        self.image_detail.set_text(_("Checking {0}...").format(CONTAINER_IMAGE))
        for icon in (self.engine_status, self.image_status, self.disk_status):
            self._set_status_icon(icon, "gitrepo-status-checking-symbolic", None)

    @staticmethod
    def _set_status_icon(icon, icon_name, css_class):
        for candidate in ("status-ok", "status-warning", "status-error"):
            icon.remove_css_class(candidate)
        icon.set_from_icon_name(icon_name)
        if css_class:
            icon.add_css_class(css_class)

    def capture_disk_status(self):
        """Return output-volume capacity and accessibility state."""
        output_dir = self.settings.output_dir
        free_gb = 0
        total_gb = 0
        disk_error = ""
        check_dir = output_dir
        while check_dir and not os.path.exists(check_dir):
            check_dir = os.path.dirname(check_dir)
        if check_dir:
            try:
                usage = shutil.disk_usage(check_dir)
                free_gb = usage.free / (1024**3)
                total_gb = usage.total / (1024**3)
            except OSError as error:
                disk_error = str(error)
        else:
            disk_error = _("No accessible parent directory was found.")
        dir_exists = os.path.exists(output_dir)
        return free_gb, total_gb, dir_exists, disk_error

    def apply_status(self, status: ContainerStatus, disk_status: tuple) -> None:
        """Render one shared container snapshot and the output-disk state."""
        free_gb, total_gb, dir_exists, disk_error = disk_status
        self._update_engine_status(status)
        self._update_image_status(status)
        self._update_disk_status(free_gb, total_gb, dir_exists, disk_error)
        self._update_last_build()
        self._update_hero_status(status, free_gb, total_gb)

    def _update_engine_status(self, status: ContainerStatus) -> None:
        if status.is_engine_ready:
            self.engine_detail.set_text(status.version)
            self._set_status_icon(self.engine_status, "gitrepo-status-ready-symbolic", "status-ok")
        else:
            self.engine_detail.set_text(_("Unavailable — {0}").format(status.engine_error))
            self._set_status_icon(self.engine_status, "gitrepo-status-error-symbolic", "status-error")

    def _update_image_status(self, status: ContainerStatus) -> None:
        if status.is_image_available:
            self.image_detail.set_text(_("{0} (available)").format(CONTAINER_IMAGE))
            self._set_status_icon(self.image_status, "gitrepo-status-ready-symbolic", "status-ok")
        elif not status.is_engine_ready:
            self.image_detail.set_text(_("Not checked — install or start Docker/Podman, then refresh."))
            self._set_status_icon(self.image_status, "gitrepo-status-error-symbolic", "status-error")
        else:
            self.image_detail.set_text(_("Unavailable — {0} Pull the image, then refresh.").format(status.image_error))
            self._set_status_icon(self.image_status, "gitrepo-status-warning-symbolic", "status-warning")

    def _update_disk_status(self, free_gb, total_gb, dir_exists, disk_error):
        if total_gb > 0:
            subtitle = _("{0:.1f} GB free of {1:.1f} GB").format(free_gb, total_gb)
            if not dir_exists:
                subtitle += " " + _("(directory will be created)")
            self.disk_detail.set_text(subtitle)
            if free_gb >= 20:
                self._set_status_icon(self.disk_status, "gitrepo-status-ready-symbolic", "status-ok")
            else:
                self._set_status_icon(self.disk_status, "gitrepo-status-warning-symbolic", "status-warning")
        else:
            self.disk_detail.set_text(
                _("Unavailable — {0} Choose another output directory, then refresh.").format(disk_error)
            )
            self._set_status_icon(self.disk_status, "gitrepo-status-error-symbolic", "status-error")

    def _update_hero_status(self, status: ContainerStatus, free_gb: float, total_gb: float) -> None:
        if not status.is_engine_ready:
            self.hero_subtitle.set_text(_("Container engine unavailable • install or start Docker/Podman"))
        elif not status.is_image_available:
            self.hero_subtitle.set_text(_("Build image missing • open Container to prepare the environment"))
        elif total_gb <= 0 or free_gb < 20:
            self.hero_subtitle.set_text(_("Storage needs attention • review the output directory"))
        else:
            self.hero_subtitle.set_text(_("Environment ready • choose a profile and configure the next ISO"))

    def _update_last_build(self):
        """Update last build info from history"""
        store = BuildHistoryStore()
        history = store.load()
        if store.last_error:
            self.last_build_row.set_title(_("Build history unavailable"))
            self.last_build_row.set_subtitle(_("The history file is invalid. Review or remove it, then refresh."))
        elif history:
            last = history[-1]
            self.last_build_row.set_title(f"{last.get('distro', '?')} - {last.get('edition', '?')}")
            status = _("Success") if last.get("success") else _("Failed")
            self.last_build_row.set_subtitle(f"{last.get('date', '?')} | {status}")
