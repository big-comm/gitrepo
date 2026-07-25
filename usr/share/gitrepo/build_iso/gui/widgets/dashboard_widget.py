#
# gui/widgets/dashboard_widget.py - Dashboard/overview widget
#

import os
import shutil

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gitrepo.build_iso.core.config import CONTAINER_IMAGE, VALID_DISTROS, edition_display_name
from gitrepo.build_iso.core.container_manager import ContainerStatus
from gitrepo.build_iso.core.history_store import BuildHistoryStore
from gitrepo.common.translation import _
from gi.repository import Adw, GObject, Gtk, Pango

from gitrepo.common.page_hero import BuildIsoPageHero as PageHero, is_large_text_enabled
from gitrepo.common.page_layout import page_body

# A build only starts once the environment is ready and a profile is chosen, so
# the dashboard states that order explicitly instead of offering loose links.
FLOW_STEPS = (
    ("container", _("Prepare the build environment"), _("Open Environment")),
    ("profiles", _("Choose the system profile"), _("Choose Profile")),
    ("build", _("Create the ISO image"), _("Open Create ISO")),
)

STATE_LABELS = {
    "checking": _("Checking"),
    "ok": _("Ready"),
    "warning": _("Attention"),
    "error": _("Blocked"),
}
STATE_ICONS = {
    "checking": "gitrepo-status-checking-symbolic",
    "ok": "gitrepo-status-ready-symbolic",
    "warning": "gitrepo-status-warning-symbolic",
    "error": "gitrepo-status-error-symbolic",
}
STATE_CSS = {"ok": "status-ok", "warning": "status-warning", "error": "status-error"}


class DashboardWidget(Gtk.Box):
    """Dashboard with status cards and the guided build flow"""

    __gtype_name__ = "DashboardWidget"

    __gsignals__ = {
        "navigate-to": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, settings):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.settings = settings
        self.flow_rows = {}

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

        clamp, dashboard_content = page_body(spacing=18)
        self.append(clamp)

        dashboard_content.append(self._create_learning_section())
        dashboard_content.append(self._create_status_section())
        dashboard_content.append(self._create_flow_section())
        dashboard_content.append(self._create_recent_section())

    def _create_learning_section(self):
        learning_list = Gtk.ListBox()
        learning_list.set_selection_mode(Gtk.SelectionMode.NONE)
        learning_list.add_css_class("premium-list")
        learning_row = Adw.ActionRow(
            title=_("An ISO is the file used to install or test a system"),
            subtitle=_("It boots from a USB drive or virtual machine and installs the system it contains."),
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
        self.engine_card = self._create_status_card("build-iso-engine", _("Container Engine"))
        status_grid.append(self.engine_card["card"])
        self.image_card = self._create_status_card("build-iso-build-image", _("Build Image"))
        status_grid.append(self.image_card["card"])
        self.disk_card = self._create_status_card("build-iso-storage", _("Disk Space"))
        status_grid.append(self.disk_card["card"])
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

    def _create_flow_section(self):
        flow_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        heading = Gtk.Label(label=_("Three steps to your ISO"), xalign=0)
        heading.add_css_class("section-heading")
        flow_box.append(heading)

        for number, (page_id, title, action_label) in enumerate(FLOW_STEPS, start=1):
            flow_box.append(self._create_flow_step(number, page_id, title, action_label))
        return flow_box

    def _create_flow_step(self, number, page_id, title, action_label):
        step = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        step.add_css_class("build-flow-step")
        step.set_accessible_role(Gtk.AccessibleRole.GROUP)

        marker = Gtk.Label(label=str(number))
        marker.add_css_class("build-flow-number")
        marker.set_valign(Gtk.Align.CENTER)
        step.append(marker)

        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        copy.set_hexpand(True)
        title_label = Gtk.Label(label=title, xalign=0)
        title_label.add_css_class("heading")
        title_label.set_wrap(True)
        title_label.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        title_label.set_width_chars(1)
        copy.append(title_label)
        detail_label = Gtk.Label(label=_("Checking..."), xalign=0)
        detail_label.add_css_class("dim-label")
        detail_label.add_css_class("caption")
        detail_label.set_wrap(True)
        detail_label.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        detail_label.set_width_chars(1)
        copy.append(detail_label)
        step.append(copy)

        button = Gtk.Button(label=action_label)
        button.set_valign(Gtk.Align.CENTER)
        button.connect("clicked", lambda _button: self.emit("navigate-to", page_id))
        step.append(button)

        self.flow_rows[page_id] = {
            "step": step,
            "detail": detail_label,
            "marker": marker,
            "number": str(number),
            "button": button,
        }
        return step

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
        state_icon = Gtk.Image.new_from_icon_name(STATE_ICONS["checking"])
        state_icon.set_pixel_size(20)
        state_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        heading.append(state_icon)
        # Colour alone is not a state. The pill repeats it as readable text.
        state_label = Gtk.Label(label=STATE_LABELS["checking"])
        state_label.add_css_class("state-pill")
        state_label.set_valign(Gtk.Align.CENTER)
        heading.append(state_label)
        card.append(heading)

        detail = Gtk.Label(label=_("Checking..."), xalign=0)
        detail.add_css_class("dim-label")
        detail.add_css_class("caption")
        detail.set_wrap(True)
        detail.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        detail.set_width_chars(1)
        detail.set_yalign(0)
        card.append(detail)
        return {"card": card, "detail": detail, "icon": state_icon, "pill": state_label}

    def set_checking(self) -> None:
        """Show pending state while the shared environment probe runs."""
        self._set_checking_state()

    def _set_checking_state(self):
        self.hero_subtitle.set_text(_("Checking the build environment…"))
        for card in (self.engine_card, self.disk_card):
            card["detail"].set_text(_("Checking..."))
        self.image_card["detail"].set_text(_("Checking {0}...").format(CONTAINER_IMAGE))
        for card in (self.engine_card, self.image_card, self.disk_card):
            self._set_card_state(card, "checking")

    @staticmethod
    def _set_card_state(card, state):
        for widget in (card["icon"], card["pill"]):
            for candidate in STATE_CSS.values():
                widget.remove_css_class(candidate)
        card["icon"].set_from_icon_name(STATE_ICONS[state])
        card["pill"].set_text(STATE_LABELS[state])
        css_class = STATE_CSS.get(state)
        if css_class:
            card["icon"].add_css_class(css_class)
            card["pill"].add_css_class(css_class)

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
        self._update_flow(status)

    def _update_engine_status(self, status: ContainerStatus) -> None:
        if status.is_engine_ready:
            self.engine_card["detail"].set_text(status.version)
            self._set_card_state(self.engine_card, "ok")
        else:
            self.engine_card["detail"].set_text(_("Unavailable — {0}").format(status.engine_error))
            self._set_card_state(self.engine_card, "error")

    def _update_image_status(self, status: ContainerStatus) -> None:
        if status.is_image_available:
            self.image_card["detail"].set_text(_("{0} (available)").format(CONTAINER_IMAGE))
            self._set_card_state(self.image_card, "ok")
        elif not status.is_engine_ready:
            self.image_card["detail"].set_text(_("Not checked — install or start Docker/Podman, then refresh."))
            self._set_card_state(self.image_card, "error")
        else:
            self.image_card["detail"].set_text(
                _("Unavailable — {0} Pull the image, then refresh.").format(status.image_error)
            )
            self._set_card_state(self.image_card, "warning")

    def _update_disk_status(self, free_gb, total_gb, dir_exists, disk_error):
        if total_gb > 0:
            subtitle = _("{0:.1f} GB free of {1:.1f} GB").format(free_gb, total_gb)
            if not dir_exists:
                subtitle += " " + _("(directory will be created)")
            self.disk_card["detail"].set_text(subtitle)
            self._set_card_state(self.disk_card, "ok" if free_gb >= 20 else "warning")
        else:
            self.disk_card["detail"].set_text(
                _("Unavailable — {0} Choose another output directory, then refresh.").format(disk_error)
            )
            self._set_card_state(self.disk_card, "error")

    def _update_hero_status(self, status: ContainerStatus, free_gb: float, total_gb: float) -> None:
        if not status.is_engine_ready:
            self.hero_subtitle.set_text(_("Container engine unavailable • install or start Docker/Podman"))
        elif not status.is_image_available:
            self.hero_subtitle.set_text(_("Build image missing • open Container to prepare the environment"))
        elif total_gb <= 0 or free_gb < 20:
            self.hero_subtitle.set_text(_("Storage needs attention • review the output directory"))
        else:
            self.hero_subtitle.set_text(_("Environment ready • choose a profile and configure the next ISO"))

    def _update_flow(self, status: ContainerStatus) -> None:
        """Mark each guided step as done, current, or still waiting."""
        environment_ready = status.is_engine_ready and status.is_image_available
        distro_name = VALID_DISTROS.get(self.settings.distribution, self.settings.distribution)

        self._set_flow_state(
            "container",
            "done" if environment_ready else "current",
            _("Docker or Podman and the build image are ready.")
            if environment_ready
            else _("The engine or the build image still needs attention."),
        )
        self._set_flow_state(
            "profiles",
            "done" if environment_ready else "waiting",
            _("Selected: {0} • {1}").format(distro_name, edition_display_name(self.settings.edition)),
        )
        self._set_flow_state(
            "build",
            "current" if environment_ready else "waiting",
            _("Review the settings and start the build.")
            if environment_ready
            else _("Available after the environment is ready."),
        )
        self.flow_rows["build"]["button"].set_sensitive(environment_ready)

    def _set_flow_state(self, page_id, state, detail):
        row = self.flow_rows[page_id]
        for candidate in ("flow-done", "flow-current", "flow-waiting"):
            row["step"].remove_css_class(candidate)
        row["step"].add_css_class(f"flow-{state}")
        row["marker"].set_text("✓" if state == "done" else row["number"])
        row["detail"].set_text(detail)

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
