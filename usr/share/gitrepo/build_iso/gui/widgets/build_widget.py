#
# gui/widgets/build_widget.py - Build configuration and execution widget
#

import os
import shutil
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gitrepo.build_iso.core.config import (
    BRANCH_DESCRIPTIONS,
    BRANCH_DISPLAY_NAMES,
    ISO_PROFILES_REPOS,
    RECOMMENDED_EDITIONS,
    VALID_BRANCHES,
    VALID_DISTROS,
    VALID_KERNELS,
    edition_display_name,
)
from gitrepo.build_iso.core.profile_catalog import ProfileCatalogResult, load_profile_catalog
from gitrepo.common.translation import _
from gitrepo.common.network_url import UnsafeNetworkUrl, validate_github_repository_url
from gi.repository import Adw, GLib, GObject, Gtk

from gitrepo.common.page_hero import BuildIsoPageHero as PageHero
from gitrepo.common.help_popover import help_button
from gitrepo.common.page_layout import page_body


class BuildWidget(Gtk.Box):
    """Build ISO configuration page"""

    __gtype_name__ = "BuildWidget"

    __gsignals__ = {
        "build-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "open-environment": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, settings):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.settings = settings
        self._edition_keys = []
        self._edition_cards = {}
        self._selected_edition = settings.edition
        self._editions_cache = {}
        self._loading_editions = False
        self._loading_cache_key = ""
        self._catalog_has_loaded = False
        self._catalog_retry_timeout_id = 0
        self._is_initializing = True

        self._create_ui()
        self._load_from_settings()
        self._is_initializing = False

    def _create_ui(self):
        """Create the single build journey: what, where, and everything else."""

        self.append(
            PageHero(
                "build-iso-create",
                _("Create an installable ISO"),
                _(
                    "Choose what the image contains and where it is saved. The build runs in an isolated "
                    "container, so its tools and files stay separate from your installed system."
                ),
            )
        )

        clamp, page_content = page_body(spacing=18)
        self.append(clamp)

        # A broken prerequisite is announced here, where the build starts, and
        # carries the action that fixes it.
        self.environment_banner = Adw.Banner()
        self.environment_banner.set_button_label(_("Open settings"))
        self.environment_banner.add_css_class("error")
        self.environment_banner.set_revealed(False)
        self.environment_banner.connect("button-clicked", lambda _banner: self.emit("open-environment"))
        page_content.append(self.environment_banner)

        self.environment_label = Gtk.Label(label=_("Checking the build environment…"), xalign=0)
        self.environment_label.add_css_class("dim-label")
        self.environment_label.add_css_class("caption")
        page_content.append(self.environment_label)

        page_content.append(self._create_target_section())
        page_content.append(self._create_output_section())
        page_content.append(self._create_advanced_section())
        page_content.append(self._create_footer())

    def _create_target_section(self) -> Gtk.Widget:
        """First decision: the system the image will install."""
        group = Adw.PreferencesGroup()
        group.set_title(_("What the ISO will install"))
        group.set_description(_("Pick the package base and the desktop the image starts with."))
        group.set_header_suffix(
            help_button(
                _("Distribution and edition"),
                _(
                    "The distribution sets which package repositories the image is built from. "
                    "The edition is the desktop it starts with — the same system with a different "
                    "workspace, applications, and defaults."
                ),
            )
        )

        self.distro_row = Adw.ComboRow()
        self.distro_row.set_title(_("Distribution"))
        self.distro_row.set_subtitle(_("Sets the package base and compatible profiles"))
        distro_model = Gtk.StringList()
        self._distro_keys = list(VALID_DISTROS.keys())
        for key in self._distro_keys:
            distro_model.append(VALID_DISTROS[key])
        self.distro_row.set_model(distro_model)
        self.distro_row.connect("notify::selected", self._on_distro_changed)
        group.add(self.distro_row)
        group.add(self._create_edition_picker())
        return group

    def _create_edition_picker(self) -> Gtk.Widget:
        """The edition is one choice among many, so it stays one row."""
        self.edition_row = Adw.ComboRow()
        self.edition_row.set_title(_("Edition"))
        self.edition_row.set_subtitle(_("Loading compatible desktop profiles…"))
        self._edition_model = Gtk.StringList()
        self.edition_row.set_model(self._edition_model)
        self.edition_row.connect("notify::selected", self._on_edition_selected)
        profile_icon = Gtk.Image.new_from_icon_name("build-iso-profile")
        profile_icon.set_pixel_size(24)
        profile_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self.edition_row.add_prefix(profile_icon)

        self.edition_spinner = Gtk.Spinner()
        self.edition_spinner.set_visible(False)
        self.edition_spinner.set_valign(Gtk.Align.CENTER)
        self.edition_row.add_suffix(self.edition_spinner)

        self.retry_editions_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self.retry_editions_button.set_tooltip_text(_("Retry loading editions"))
        self.retry_editions_button.add_css_class("flat")
        self.retry_editions_button.set_valign(Gtk.Align.CENTER)
        self.retry_editions_button.connect("clicked", lambda _button: self._fetch_editions_async(force_refresh=True))
        self.edition_row.add_suffix(self.retry_editions_button)
        return self.edition_row

    def _create_output_section(self) -> Gtk.Widget:
        """Second decision: where the finished image lands."""
        group = Adw.PreferencesGroup()
        group.set_title(_("Where to save it"))
        group.set_description(_("Choose where completed images and build artifacts are stored."))

        output_row = Adw.ActionRow()
        output_row.set_title(_("Destination Folder"))
        storage_icon = Gtk.Image.new_from_icon_name("build-iso-storage")
        storage_icon.set_pixel_size(24)
        storage_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        output_row.add_prefix(storage_icon)
        self.output_row = Gtk.Entry()
        self.output_row.set_hexpand(True)
        self.output_row.set_valign(Gtk.Align.CENTER)
        self.output_row.update_property([Gtk.AccessibleProperty.LABEL], [_("Destination path")])
        self.output_row.set_text(self.settings.output_dir)
        output_row.add_suffix(self.output_row)

        browse_btn = Gtk.Button()
        browse_btn.set_icon_name("folder-open-symbolic")
        browse_btn.set_valign(Gtk.Align.CENTER)
        browse_btn.set_tooltip_text(_("Browse..."))
        browse_btn.connect("clicked", self._on_browse_output)
        output_row.add_suffix(browse_btn)
        group.add(output_row)

        self.disk_label = Gtk.Label()
        self.disk_label.set_halign(Gtk.Align.START)
        self.disk_label.add_css_class("dim-label")
        self.disk_label.add_css_class("caption")
        self.disk_label.set_margin_top(4)
        self.disk_label.set_margin_start(12)
        group.add(self.disk_label)
        self._update_disk_space()
        return group

    def _create_advanced_section(self) -> Gtk.Widget:
        """Everything with a good default stays folded until it is needed."""
        group = Adw.PreferencesGroup()
        expander = Adw.ExpanderRow()
        expander.set_title(_("Advanced options"))
        expander.set_subtitle(_("Kernel, package channels, and where profiles come from"))
        group.add(expander)

        self.kernel_row = Adw.ComboRow()
        self.kernel_row.set_title(_("Kernel Variant"))
        self.kernel_row.set_subtitle(_("Long-term stability or newer hardware support"))
        kernel_model = Gtk.StringList()
        self._kernel_keys = list(VALID_KERNELS.keys())
        for key in self._kernel_keys:
            kernel_model.append(VALID_KERNELS[key])
        self.kernel_row.set_model(kernel_model)
        self.kernel_row.add_suffix(
            help_button(
                _("Which kernel to choose"),
                _(
                    "LTS receives long-term fixes and is the safest default. Latest supports very recent "
                    "hardware but changes faster. Old LTS helps on older machines, and XanMod targets "
                    "desktop responsiveness."
                ),
            )
        )
        expander.add_row(self.kernel_row)

        self._add_channel_rows(expander)
        self._add_profile_source_rows(expander)
        return group

    def _add_channel_rows(self, expander: Adw.ExpanderRow) -> None:
        """Package channels share one explanation and one model."""
        self.manjaro_branch_row = Adw.ComboRow()
        self.manjaro_branch_row.set_title(_("Manjaro Packages"))
        self.manjaro_branch_row.set_subtitle(_("Base system packages"))
        self.manjaro_branch_row.set_model(self._branch_model())
        self.manjaro_branch_row.add_suffix(
            help_button(
                _("Package channels"),
                "\n".join(
                    f"{BRANCH_DISPLAY_NAMES[branch]}: {BRANCH_DESCRIPTIONS[branch]}" for branch in VALID_BRANCHES
                ),
            )
        )
        expander.add_row(self.manjaro_branch_row)

        self.biglinux_branch_row = Adw.ComboRow()
        self.biglinux_branch_row.set_title(_("BigLinux Packages"))
        self.biglinux_branch_row.set_subtitle(_("BigLinux system components"))
        self.biglinux_branch_row.set_model(self._branch_model())
        expander.add_row(self.biglinux_branch_row)

        self.community_branch_row = Adw.ComboRow()
        self.community_branch_row.set_title(_("Community Packages"))
        self.community_branch_row.set_subtitle(_("Packages maintained by BigCommunity"))
        self.community_branch_row.set_model(self._branch_model())
        expander.add_row(self.community_branch_row)

    def _add_profile_source_rows(self, expander: Adw.ExpanderRow) -> None:
        """Where profile definitions come from, and their inputs."""
        self.profiles_source_row = Adw.ComboRow()
        self.profiles_source_row.set_title(_("Profile source"))
        self.profiles_source_row.set_subtitle(_("Maintained profiles from the official GitHub repositories"))
        source_model = Gtk.StringList()
        source_model.append(_("Official (GitHub)"))
        source_model.append(_("Custom Repository URL"))
        source_model.append(_("Local Folder"))
        self.profiles_source_row.set_model(source_model)
        self.profiles_source_row.connect("notify::selected", self._on_profiles_source_changed)
        source_icon = Gtk.Image.new_from_icon_name("build-iso-source")
        source_icon.set_pixel_size(24)
        source_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self.profiles_source_row.add_prefix(source_icon)
        self.profiles_source_row.add_suffix(
            help_button(
                _("Profile definitions"),
                _(
                    "A profile is the recipe of the image: package lists, enabled services, and files "
                    "copied into the system. Keep the official source unless you maintain your own "
                    "iso-profiles repository or folder."
                ),
            )
        )
        expander.add_row(self.profiles_source_row)

        self.custom_url_row = Adw.EntryRow()
        self.custom_url_row.set_title(_("Repository URL"))
        self.custom_url_row.set_text("")
        self.custom_url_row.set_visible(False)
        self.custom_url_row.connect("changed", self._on_custom_source_changed)
        expander.add_row(self.custom_url_row)

        self.local_path_row = Adw.EntryRow()
        self.local_path_row.set_title(_("Local Folder Path"))
        self.local_path_row.set_text("")
        self.local_path_row.set_visible(False)
        local_browse_btn = Gtk.Button()
        local_browse_btn.set_icon_name("folder-open-symbolic")
        local_browse_btn.set_valign(Gtk.Align.CENTER)
        local_browse_btn.set_tooltip_text(_("Browse..."))
        local_browse_btn.connect("clicked", self._on_browse_local_profiles)
        self.local_path_row.add_suffix(local_browse_btn)
        self.local_path_row.connect("changed", self._on_custom_source_changed)
        expander.add_row(self.local_path_row)

    def _create_footer(self) -> Gtk.Widget:
        """The primary action and the summary of what it will produce."""
        self.page_footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.page_footer.add_css_class("page-footer-bar")

        summary_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        summary_box.set_hexpand(True)
        summary_box.set_valign(Gtk.Align.CENTER)
        self.summary_label = Gtk.Label(xalign=0)
        self.summary_label.add_css_class("build-summary-value")
        self.summary_label.set_wrap(True)
        self.summary_label.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        self.summary_label.set_width_chars(1)
        summary_box.append(self.summary_label)
        self.summary_detail = Gtk.Label(xalign=0)
        self.summary_detail.add_css_class("dim-label")
        self.summary_detail.add_css_class("caption")
        self.summary_detail.set_wrap(True)
        self.summary_detail.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        self.summary_detail.set_width_chars(1)
        summary_box.append(self.summary_detail)
        self.page_footer.append(summary_box)

        self.build_button = Gtk.Button()
        self.build_button.set_label(_("Create ISO image"))
        self.build_button.add_css_class("suggested-action")
        self.build_button.set_valign(Gtk.Align.CENTER)
        self.build_button.set_sensitive(False)
        self.build_button.connect("clicked", self._on_build_clicked)
        self.page_footer.append(self.build_button)

        for row in (
            self.distro_row,
            self.kernel_row,
            self.manjaro_branch_row,
            self.biglinux_branch_row,
            self.community_branch_row,
        ):
            row.connect("notify::selected", lambda *_args: self._update_summary())
        self.output_row.connect("changed", lambda *_args: self._update_summary())
        self._update_summary()
        # The footer is owned by the window's bottom bar, not by the page body.
        return Gtk.Box()

    def apply_environment(self, status, disk_status) -> None:
        """Report the build prerequisites where the build is started."""
        free_gb, total_gb, _dir_exists, disk_error = disk_status
        if not status.is_engine_ready:
            problem = _("Container engine unavailable — {0}").format(status.engine_error)
        elif not status.is_image_available:
            problem = _("Build image missing — {0}").format(status.image_error)
        elif total_gb <= 0:
            problem = _("Output storage unavailable — {0}").format(disk_error)
        else:
            problem = ""

        self.environment_banner.set_title(problem)
        self.environment_banner.set_revealed(bool(problem))
        if problem:
            self.environment_label.set_visible(False)
            return

        self.environment_label.set_visible(True)
        self.environment_label.set_text(
            _("Environment ready • {0} {1} • {2:.1f} GB free").format(
                (status.engine or "").capitalize(), status.version, free_gb
            )
        )

    @staticmethod
    def _branch_model() -> Gtk.StringList:
        model = Gtk.StringList()
        for branch in VALID_BRANCHES:
            model.append(BRANCH_DISPLAY_NAMES[branch])
        return model

    def _update_summary(self) -> None:
        """Describe, in one line, exactly what the primary action will build."""
        distro = self._get_selected_distro()
        branches = [
            _("Manjaro {0}").format(BRANCH_DISPLAY_NAMES[self._get_selected_branch(self.manjaro_branch_row)]),
            _("BigLinux {0}").format(BRANCH_DISPLAY_NAMES[self._get_selected_branch(self.biglinux_branch_row)]),
        ]
        if distro != "biglinux":
            branches.append(
                _("Community {0}").format(BRANCH_DISPLAY_NAMES[self._get_selected_branch(self.community_branch_row)])
            )
        self.summary_label.set_text(
            _("{0} • {1} • kernel {2}").format(
                VALID_DISTROS.get(distro, distro),
                edition_display_name(self._get_selected_edition()),
                VALID_KERNELS.get(self._get_selected_kernel(), self._get_selected_kernel()),
            )
        )
        self.summary_detail.set_text(
            _("{0} • saved in {1}").format(" · ".join(branches), self.output_row.get_text() or _("not chosen"))
        )

    def _load_from_settings(self):
        """Load settings into UI"""
        # Distro
        distro = self.settings.distribution
        if distro in self._distro_keys:
            self.distro_row.set_selected(self._distro_keys.index(distro))

        # Kernel
        kernel = self.settings.kernel
        if kernel in self._kernel_keys:
            self.kernel_row.set_selected(self._kernel_keys.index(kernel))

        # Branches
        branches = self.settings.branches
        for i, b in enumerate(VALID_BRANCHES):
            if b == branches.get("manjaro", "stable"):
                self.manjaro_branch_row.set_selected(i)
            if b == branches.get("biglinux", "stable"):
                self.biglinux_branch_row.set_selected(i)
            if b == branches.get("community", "stable"):
                self.community_branch_row.set_selected(i)

        # Output dir
        self.output_row.set_text(self.settings.output_dir)

        # Community branch visibility
        self._update_community_branch_visibility()

        # ISO Profiles source
        source = self.settings.get("build", "iso_profiles_source", default="remote")
        if source == "remote":
            self.profiles_source_row.set_selected(0)
        elif source == "custom_url":
            self.profiles_source_row.set_selected(1)
            self.custom_url_row.set_text(self.settings.get("build", "iso_profiles_custom_url", default=""))
        elif source == "local":
            self.profiles_source_row.set_selected(2)
            self.local_path_row.set_text(self.settings.get("build", "iso_profiles_local_path", default=""))
        self._on_profiles_source_changed(self.profiles_source_row, None)

    def _on_profiles_source_changed(self, row, _pspec):
        """Handle profiles source change"""
        idx = self.profiles_source_row.get_selected()
        self.custom_url_row.set_visible(idx == 1)
        self.local_path_row.set_visible(idx == 2)

        if idx == 0:
            self.profiles_source_row.set_subtitle(_("Maintained profiles from the official GitHub repositories"))
        elif idx == 1:
            self.profiles_source_row.set_subtitle(_("Profiles from a GitHub repository you control"))
        elif idx == 2:
            self.profiles_source_row.set_subtitle(_("Profiles read directly from a local folder"))

        if self._is_initializing:
            return
        # Clear cache to force refetch
        self._editions_cache.clear()
        self._catalog_has_loaded = False
        self._fetch_editions_async(force_refresh=True)

    def _on_custom_source_changed(self, row):
        """Handle custom URL or local path change - refresh editions"""
        if self._is_initializing:
            return
        self._editions_cache.clear()
        self._catalog_has_loaded = False
        self._fetch_editions_async(force_refresh=True)

    def _on_browse_local_profiles(self, button):
        """Open folder chooser for local iso-profiles"""
        dialog = Gtk.FileDialog()
        dialog.set_title(_("Select iso-profiles Folder"))
        dialog.select_folder(self.get_root(), None, self._on_local_profiles_selected)

    def _on_local_profiles_selected(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                self.local_path_row.set_text(folder.get_path())
                self._editions_cache.clear()
                self._fetch_editions_async()
        except Exception:
            pass

    def _get_profiles_source(self):
        """Get current profiles source type and value"""
        idx = self.profiles_source_row.get_selected()
        if idx == 0:
            return "remote", ""
        elif idx == 1:
            return "custom_url", self.custom_url_row.get_text().strip()
        elif idx == 2:
            return "local", self.local_path_row.get_text().strip()
        return "remote", ""

    def _on_distro_changed(self, row, _pspec):
        """Handle distribution change - refresh editions and toggle community branch"""
        self._update_community_branch_visibility()
        if self._is_initializing:
            return
        self._editions_cache.clear()
        self._catalog_has_loaded = False
        self._fetch_editions_async()

    def _update_community_branch_visibility(self):
        """Show/hide community branch based on selected distribution"""
        distro = self._get_selected_distro()
        # BigLinux does not have a community repository
        self.community_branch_row.set_visible(distro != "biglinux")

    def ensure_catalog_loaded(self) -> None:
        """Load the selected catalog only when the Build page is first shown."""
        if not self._catalog_has_loaded and not self._loading_editions:
            self._fetch_editions_async()

    def _fetch_editions_async(self, *, force_refresh: bool = False) -> None:
        """Fetch editions off the GTK main loop and reject stale replies."""
        distro_key = self._get_selected_distro()
        source_type, source_value = self._get_profiles_source()
        cache_key = f"{distro_key}:{source_type}:{source_value}"
        if self._loading_editions and self._loading_cache_key == cache_key:
            return
        self._editions_request_id = getattr(self, "_editions_request_id", 0) + 1
        request_id = self._editions_request_id
        if not force_refresh and cache_key in self._editions_cache:
            self._populate_editions(request_id, self._editions_cache[cache_key])
            return
        self.edition_spinner.set_visible(True)
        self.edition_spinner.start()
        self._loading_editions = True
        self._loading_cache_key = cache_key
        threading.Thread(
            target=self._fetch_editions_worker,
            args=(request_id, distro_key, source_type, source_value, cache_key, force_refresh),
            daemon=True,
        ).start()

    def _fetch_editions_worker(
        self,
        request_id: int,
        distro_key: str,
        source_type: str,
        source_value: str,
        cache_key: str,
        force_refresh: bool,
    ) -> None:
        result = load_profile_catalog(distro_key, source_type, source_value, force_refresh=force_refresh)
        if not result.is_fallback and not result.is_stale:
            self._editions_cache[cache_key] = result
        GLib.idle_add(self._populate_editions, request_id, result)

    def _populate_editions(self, request_id: int, result: ProfileCatalogResult) -> bool:
        """Populate edition combo with fetched data (main thread)"""
        if request_id != self._editions_request_id:
            return False
        self.edition_spinner.stop()
        self.edition_spinner.set_visible(False)
        self._loading_editions = False
        self._loading_cache_key = ""
        self._catalog_has_loaded = True
        self._apply_catalog_result_state(result)
        self._replace_editions(result.editions)
        return False

    def _apply_catalog_result_state(self, result: ProfileCatalogResult) -> None:
        self.edition_row.remove_css_class("error")
        self.edition_row.remove_css_class("warning")
        # Retrying is only an option when the load did not go well; keeping the
        # button always visible squeezed the edition name into an ellipsis.
        self.retry_editions_button.set_visible(bool(result.failure_kind) or result.is_fallback or result.is_stale)
        if result.failure_kind == "rate_limit":
            retry_time = time.strftime("%H:%M", time.localtime(result.retry_at))
            if result.is_fallback:
                self.edition_row.set_subtitle(
                    _("GitHub API quota reached — using built-in suggestions. Automatic retry at {0}.").format(
                        retry_time
                    )
                )
                self.edition_row.add_css_class("error")
                self._catalog_is_valid = False
                self.build_button.set_sensitive(False)
            else:
                self.edition_row.set_subtitle(
                    _("GitHub API quota reached — using cached profiles. Automatic refresh at {0}.").format(retry_time)
                )
                self.edition_row.add_css_class("warning")
                self._catalog_is_valid = True
                self.build_button.set_sensitive(True)
            self._defer_catalog_retry_until(result.retry_at)
        elif result.is_fallback:
            self.edition_row.set_subtitle(
                _("Built-in suggestions — could not load the selected source: {0}").format(result.error)
            )
            self.edition_row.add_css_class("error")
            self._catalog_is_valid = False
            self.build_button.set_sensitive(False)
            self._enable_catalog_retry()
        elif result.is_stale:
            self.edition_row.set_subtitle(_("Using cached profiles — the source is temporarily unreachable."))
            self.edition_row.add_css_class("warning")
            self._catalog_is_valid = True
            self.build_button.set_sensitive(True)
            self._enable_catalog_retry()
        elif result.origin == "official:GitHub":
            self.edition_row.set_subtitle(
                _("Official profile • GitHub cache") if result.is_cached else _("Official profile • GitHub")
            )
            self._enable_catalog_retry()
        elif result.origin.startswith("custom:"):
            self.edition_row.set_subtitle(
                _("Custom profile • GitHub cache") if result.is_cached else _("Custom profile • GitHub")
            )
            self._enable_catalog_retry()
        elif result.origin.startswith("local:"):
            self.edition_row.set_subtitle(_("Local profile folder"))
            self._enable_catalog_retry()
        else:
            self.edition_row.set_subtitle(result.origin)
            self._enable_catalog_retry()
        if not result.is_fallback and result.failure_kind != "rate_limit" and not result.is_stale:
            self._catalog_is_valid = True
            self.build_button.set_sensitive(True)

    def _replace_editions(self, editions: tuple[str, ...]) -> None:
        pending = getattr(self, "_pending_edition", None)
        current_edition = pending or self._selected_edition or self.settings.edition
        if pending:
            self._pending_edition = None

        self._edition_keys = list(editions)
        self._edition_model = Gtk.StringList()
        for edition in editions:
            label = edition_display_name(edition)
            if edition.lower() in RECOMMENDED_EDITIONS:
                label = _("{0} (recommended)").format(label)
            self._edition_model.append(label)
        self.edition_row.set_model(self._edition_model)
        self._select_edition(current_edition if current_edition in editions else (editions[0] if editions else ""))

    def _on_edition_selected(self, row, _pspec) -> None:
        index = row.get_selected()
        if 0 <= index < len(self._edition_keys):
            self._selected_edition = self._edition_keys[index]
            self._update_summary()

    def _select_edition(self, edition: str) -> None:
        self._selected_edition = edition
        if edition in self._edition_keys:
            self.edition_row.set_selected(self._edition_keys.index(edition))
        self._update_summary()

    def _defer_catalog_retry_until(self, retry_at: int) -> None:
        if self._catalog_retry_timeout_id:
            GLib.source_remove(self._catalog_retry_timeout_id)
        retry_time = time.strftime("%H:%M", time.localtime(retry_at))
        self.retry_editions_button.set_sensitive(False)
        self.retry_editions_button.set_tooltip_text(_("GitHub API available again at {0}").format(retry_time))
        delay = max(1, retry_at - int(time.time()) + 1)
        self._catalog_retry_timeout_id = GLib.timeout_add_seconds(delay, self._retry_catalog_after_limit)

    def _retry_catalog_after_limit(self) -> bool:
        self._catalog_retry_timeout_id = 0
        self.retry_editions_button.set_sensitive(True)
        self.retry_editions_button.set_tooltip_text(_("Retry loading editions"))
        self._fetch_editions_async(force_refresh=True)
        return False

    def _enable_catalog_retry(self) -> None:
        if self._catalog_retry_timeout_id:
            GLib.source_remove(self._catalog_retry_timeout_id)
            self._catalog_retry_timeout_id = 0
        self.retry_editions_button.set_sensitive(True)
        self.retry_editions_button.set_tooltip_text(_("Retry loading editions"))

    def _get_selected_distro(self):
        idx = self.distro_row.get_selected()
        if 0 <= idx < len(self._distro_keys):
            return self._distro_keys[idx]
        return self._distro_keys[0]

    def _get_selected_edition(self):
        return self._selected_edition or self.settings.edition or "gnome"

    def _get_selected_kernel(self):
        idx = self.kernel_row.get_selected()
        if 0 <= idx < len(self._kernel_keys):
            return self._kernel_keys[idx]
        return "lts"

    def _get_selected_branch(self, row):
        idx = row.get_selected()
        if 0 <= idx < len(VALID_BRANCHES):
            return VALID_BRANCHES[idx]
        return "stable"

    def _on_browse_output(self, button):
        """Open folder chooser for output directory"""
        dialog = Gtk.FileDialog()
        dialog.set_title(_("Select Output Directory"))
        dialog.select_folder(self.get_root(), None, self._on_folder_selected)

    def _on_folder_selected(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                path = folder.get_path()
                self.output_row.set_text(path)
                self._update_disk_space()
        except Exception:
            pass

    def _update_disk_space(self):
        """Report the destination's free space only when it needs attention.

        The environment line above already states the free space of a healthy
        setup; repeating it under the folder row is noise, while a folder that
        does not exist or is nearly full is worth a line of its own.
        """
        path = self.output_row.get_text()
        if not path or not os.path.exists(path):
            self.disk_label.set_text(_("This folder does not exist yet; it will be created."))
            self.disk_label.set_visible(True)
            return

        usage = shutil.disk_usage(path)
        free_gb = usage.free / (1024**3)
        if free_gb >= 20:
            self.disk_label.set_visible(False)
            return

        self.disk_label.remove_css_class("dim-label")
        self.disk_label.add_css_class("status-warning")
        self.disk_label.set_text(_("Only {0:.1f} GB free here; a build needs about 20 GB.").format(free_gb))
        self.disk_label.set_visible(True)

    def set_build_config(self, distro_key, edition):
        """Set distro and edition from external source (e.g. profiles page)"""
        self._pending_edition = edition

        # Check if distro is already selected
        current_distro = self._get_selected_distro()
        if current_distro == distro_key:
            if edition in self._edition_keys:
                self._select_edition(edition)
                self._pending_edition = None
                return
            # Edition not in model yet, force re-fetch
            self._fetch_editions_async()
        else:
            # Set distro - this triggers _on_distro_changed which fetches editions
            for i, key in enumerate(VALID_DISTROS):
                if key == distro_key:
                    self.distro_row.set_selected(i)
                    break

    def _on_build_clicked(self, button):
        """Handle Start Build button click"""
        if not getattr(self, "_catalog_is_valid", False):
            return
        distro = self._get_selected_distro()
        source_type, source_value = self._get_profiles_source()

        # Determine iso_profiles_repo based on source
        if source_type == "custom_url" and source_value:
            try:
                iso_profiles_repo = validate_github_repository_url(source_value)
            except UnsafeNetworkUrl:
                self.custom_url_row.add_css_class("error")
                return
        elif source_type == "local":
            iso_profiles_repo = ISO_PROFILES_REPOS.get(distro, "")
        else:
            iso_profiles_repo = ISO_PROFILES_REPOS.get(distro, "")

        config = {
            "distroname": distro,
            "edition": self._get_selected_edition(),
            "kernel": self._get_selected_kernel(),
            "branches": {
                "manjaro": self._get_selected_branch(self.manjaro_branch_row),
                "biglinux": self._get_selected_branch(self.biglinux_branch_row),
                "community": self._get_selected_branch(self.community_branch_row) if distro != "biglinux" else "",
            },
            "iso_profiles_repo": iso_profiles_repo,
            "iso_profiles_source": source_type,
            "iso_profiles_local_path": source_value if source_type == "local" else "",
            "build_dir": distro,
            "output_dir": self.output_row.get_text(),
            "container_engine": self.settings.get("container", "engine", default="docker"),
            "container_image": self.settings.container_image,
        }

        if not self.settings.set_many(
            {
                ("general", "distribution"): distro,
                ("general", "edition"): config["edition"],
                ("general", "kernel"): config["kernel"],
                ("general", "branches"): config["branches"],
                ("general", "output_dir"): config["output_dir"],
                ("build", "iso_profiles_source"): source_type,
                ("build", "iso_profiles_custom_url"): source_value if source_type == "custom_url" else "",
                ("build", "iso_profiles_local_path"): source_value if source_type == "local" else "",
            }
        ):
            root = self.get_root()
            if root and hasattr(root, "show_toast"):
                root.show_toast(_("Could not save build settings. Check config permissions, then try again."))
            return

        self.emit("build-requested", config)

    def refresh(self):
        """Refresh widget state"""
        self._update_disk_space()
