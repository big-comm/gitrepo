#
# gui/widgets/profiles_widget.py - ISO profiles browser widget
#

import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gitrepo.build_iso.core.config import (
    RECOMMENDED_EDITIONS,
    VALID_DISTROS,
    edition_display_name,
)
from gitrepo.build_iso.core.profile_catalog import ProfileCatalogResult, load_profile_catalog
from gitrepo.common.translation import _
from gi.repository import Adw, GLib, GObject, Gtk

from gitrepo.common.page_hero import BuildIsoPageHero as PageHero
from gitrepo.common.page_layout import page_body


class ProfilesWidget(Gtk.Box):
    """Browse and select ISO profiles for each distribution"""

    __gtype_name__ = "ProfilesWidget"

    __gsignals__ = {
        "profile-selected": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),  # distro, edition
    }

    def __init__(self, settings):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.settings = settings
        self._profiles_data = {}
        self._has_loaded = False
        self._is_loading = False
        self._retry_timeout_id = 0

        self._create_ui()

    def _create_ui(self):
        """Create profiles browser UI"""

        self.append(
            PageHero(
                "build-iso-profiles",
                _("Available ISO Profiles"),
                _("Browse editions from the selected source. Choosing one opens the build page with that profile."),
            )
        )

        clamp, page_content = page_body()
        self.append(clamp)

        # Source info
        self.header_group = Adw.PreferencesGroup()
        page_content.append(self.header_group)

        # Source info row
        self.source_row = Adw.ActionRow()
        self.source_row.set_title(_("Current Source"))
        self._update_source_label()
        source_icon = Gtk.Image.new_from_icon_name("build-iso-source")
        source_icon.set_pixel_size(24)
        self.source_row.add_prefix(source_icon)

        self.refresh_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self.refresh_button.set_valign(Gtk.Align.CENTER)
        self.refresh_button.set_tooltip_text(_("Refresh profiles"))
        self.refresh_button.connect("clicked", self._on_refresh_clicked)
        self.source_row.add_suffix(self.refresh_button)
        self.header_group.add(self.source_row)

        # Spinner for loading
        self.spinner = Gtk.Spinner()
        self.spinner.set_size_request(32, 32)
        self.spinner.set_halign(Gtk.Align.CENTER)
        self.spinner.set_margin_top(24)
        self.spinner.set_visible(False)
        page_content.append(self.spinner)

        # Container for profile groups
        self.profiles_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.profiles_box.set_margin_top(12)
        page_content.append(self.profiles_box)

    def _update_source_label(self):
        """Update the source description based on current settings"""
        source = self.settings.get("build", "iso_profiles_source", default="remote")
        if source == "local":
            path = self.settings.get("build", "iso_profiles_local_path", default="")
            self.source_row.set_subtitle(_("Local: {0}").format(path or _("not configured")))
        elif source == "custom_url":
            url = self.settings.get("build", "iso_profiles_custom_url", default="")
            self.source_row.set_subtitle(_("Custom: {0}").format(url or _("not configured")))
        else:
            self.source_row.set_subtitle(_("Official GitHub repositories"))

    def _on_refresh_clicked(self, button):
        """Refresh profiles list"""
        if self._is_loading:
            return
        self._profiles_data.clear()
        self._clear_profiles()
        self._update_source_label()
        self.spinner.set_visible(True)
        self.spinner.start()
        self._fetch_all_profiles(force_refresh=True)

    def refresh(self):
        """Public refresh method"""
        self._on_refresh_clicked(None)

    def ensure_loaded(self) -> None:
        """Load catalogs only when the Profiles page is first shown."""
        if self._has_loaded or self._is_loading:
            return
        self.spinner.set_visible(True)
        self.spinner.start()
        self._fetch_all_profiles()

    def _fetch_all_profiles(self, *, force_refresh: bool = False) -> None:
        if self._is_loading:
            return
        self._is_loading = True
        self._request_generation = getattr(self, "_request_generation", 0) + 1
        request_id = self._request_generation
        threading.Thread(target=self._fetch_worker, args=(request_id, force_refresh), daemon=True).start()

    def _fetch_worker(self, request_id: int, force_refresh: bool) -> None:
        source = self.settings.get("build", "iso_profiles_source", default="remote")
        source_value = ""
        if source == "local":
            source_value = self.settings.get("build", "iso_profiles_local_path", default="")
        elif source == "custom_url":
            source_value = self.settings.get("build", "iso_profiles_custom_url", default="")
        results = {
            distro_key: load_profile_catalog(distro_key, source, source_value, force_refresh=force_refresh)
            for distro_key in VALID_DISTROS
        }
        GLib.idle_add(self._populate_profiles, request_id, results)

    def _populate_profiles(self, request_id: int, results: dict[str, ProfileCatalogResult]) -> bool:
        if request_id != self._request_generation:
            return False
        self.spinner.stop()
        self.spinner.set_visible(False)
        self._is_loading = False
        self._has_loaded = True

        self._profiles_data = results
        self._clear_profiles()
        self._show_catalog_source_state(results)
        self._append_profile_groups(results)
        return False

    def _show_catalog_source_state(self, results: dict[str, ProfileCatalogResult]) -> None:
        failures = [result.error for result in results.values() if result.is_fallback]
        self.source_row.remove_css_class("error")
        self.source_row.remove_css_class("warning")
        limited = [result for result in results.values() if result.failure_kind == "rate_limit"]
        stale = [result for result in results.values() if result.is_stale]
        if limited:
            retry_at = max(result.retry_at for result in limited)
            retry_time = time.strftime("%H:%M", time.localtime(retry_at))
            if any(result.is_fallback for result in limited):
                self.source_row.set_subtitle(
                    _("GitHub API quota reached — using built-in suggestions. Automatic retry at {0}.").format(
                        retry_time
                    )
                )
                self.source_row.add_css_class("error")
            else:
                self.source_row.set_subtitle(
                    _("GitHub API quota reached — using cached profiles. Automatic refresh at {0}.").format(retry_time)
                )
                self.source_row.add_css_class("warning")
            self._defer_refresh_until(retry_at)
        elif stale:
            self.source_row.set_subtitle(_("Using cached profiles — the source is temporarily unreachable."))
            self.source_row.add_css_class("warning")
            self._enable_refresh()
        elif failures:
            self.source_row.set_subtitle(
                _("Built-in suggestions — could not load the selected source: {0}").format(failures[0])
            )
            self.source_row.add_css_class("error")
            self._enable_refresh()
        else:
            self._update_source_label()
            self._enable_refresh()

    def _append_profile_groups(self, results: dict[str, ProfileCatalogResult]) -> None:
        for distro_key, result in results.items():
            editions = result.editions
            distro_name = VALID_DISTROS.get(distro_key, distro_key)

            group = Adw.PreferencesGroup()
            group.set_title(distro_name)

            for edition in editions:
                row = Adw.ActionRow()
                row.set_title(edition_display_name(edition))
                row.set_subtitle(_("{0} desktop image • profile folder “{1}”").format(distro_name, edition))
                row.set_activatable(True)

                icon = Gtk.Image.new_from_icon_name("build-iso-profile")
                icon.set_pixel_size(24)
                row.add_prefix(icon)

                if edition.lower() in RECOMMENDED_EDITIONS:
                    recommended = Gtk.Label(label=_("Recommended"))
                    recommended.add_css_class("state-pill")
                    recommended.add_css_class("status-ok")
                    recommended.set_valign(Gtk.Align.CENTER)
                    row.add_suffix(recommended)

                arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
                arrow.set_valign(Gtk.Align.CENTER)
                row.add_suffix(arrow)

                row._distro_key = distro_key
                row._edition = edition
                row.connect("activated", self._on_profile_activated)

                group.add(row)

            self.profiles_box.append(group)

    def _clear_profiles(self):
        child = self.profiles_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.profiles_box.remove(child)
            child = next_child

    def _defer_refresh_until(self, retry_at: int) -> None:
        if self._retry_timeout_id:
            GLib.source_remove(self._retry_timeout_id)
        retry_time = time.strftime("%H:%M", time.localtime(retry_at))
        self.refresh_button.set_sensitive(False)
        self.refresh_button.set_tooltip_text(_("GitHub API available again at {0}").format(retry_time))
        delay = max(1, retry_at - int(time.time()) + 1)
        self._retry_timeout_id = GLib.timeout_add_seconds(delay, self._retry_after_limit)

    def _retry_after_limit(self) -> bool:
        self._retry_timeout_id = 0
        self.refresh_button.set_sensitive(True)
        self.refresh_button.set_tooltip_text(_("Refresh profiles"))
        self._fetch_all_profiles(force_refresh=True)
        return False

    def _enable_refresh(self) -> None:
        if self._retry_timeout_id:
            GLib.source_remove(self._retry_timeout_id)
            self._retry_timeout_id = 0
        self.refresh_button.set_sensitive(True)
        self.refresh_button.set_tooltip_text(_("Refresh profiles"))

    def _on_profile_activated(self, row):
        """Handle profile row click - emit signal to navigate to build with this profile"""
        self.emit("profile-selected", row._distro_key, row._edition)
