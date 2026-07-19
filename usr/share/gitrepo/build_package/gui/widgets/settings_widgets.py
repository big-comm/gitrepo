"""Visible settings pages for Build Package navigation."""

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gitrepo.build_package.core.token_store import TokenStore
from gitrepo.common.translation import _
from gi.repository import Adw, Gio, GLib, Gtk

from gitrepo.common.page_hero import BuildPackagePageHero as PageHero


class TokenSettingsWidget(Gtk.Box):
    """Explain and manage GitHub tokens without exposing their values."""

    def __init__(self, parent_window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.parent_window = parent_window
        self._token_rows = []
        self._create_ui()
        self._refresh_token_rows()

    def _create_ui(self):
        self.append(
            PageHero(
                "build-package-repository",
                _("Connect GitHub securely"),
                _(
                    "Local Git commands do not need a token. A token is used only when this app asks GitHub to run package workflows or manage remote automation."
                ),
            )
        )

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.add_css_class("page-frame")
        self.append(content)
        content.append(self._create_token_guide())

        self.tokens_group = Adw.PreferencesGroup()
        self.tokens_group.set_title(_("Tokens saved on this computer"))
        self.tokens_group.set_description(
            _("Values are protected by the system keyring and are never displayed by this app.")
        )
        content.append(self.tokens_group)
        content.append(self._create_token_form())

    def _create_token_guide(self):
        guide_group = Adw.PreferencesGroup()
        guide_group.set_title(_("Before adding a token"))
        guide_group.set_description(
            _(
                "The token authorizes GitHub operations for one organization or user. Saving it does not verify that its permissions are valid."
            )
        )

        purpose_row = Adw.ActionRow()
        purpose_row.set_title(_("Why GitHub needs it"))
        purpose_row.set_subtitle(
            _("GitHub uses the token to identify your account and authorize workflows that Git alone cannot start.")
        )
        purpose_row.add_prefix(Gtk.Image.new_from_icon_name("security-high-symbolic"))
        guide_group.add(purpose_row)

        link_row = Adw.ActionRow()
        link_row.set_title(_("Create a classic access token on GitHub"))
        link_row.set_subtitle("github.com/settings/tokens → Generate new token (classic)")
        link_row.set_activatable(True)
        link_row.add_prefix(Gtk.Image.new_from_icon_name("web-browser-symbolic"))
        link_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        link_row.connect(
            "activated", lambda _row: Gio.AppInfo.launch_default_for_uri("https://github.com/settings/tokens", None)
        )
        guide_group.add(link_row)

        scopes_row = Adw.ActionRow()
        scopes_row.set_title(_("Permissions required by the package workflows"))
        scopes_row.set_subtitle("repo  ·  workflow  ·  write:packages  ·  delete:packages  ·  read:org")
        scopes_row.add_prefix(Gtk.Image.new_from_icon_name("emblem-ok-symbolic"))
        guide_group.add(scopes_row)
        return guide_group

    def _create_token_form(self):
        add_group = Adw.PreferencesGroup()
        add_group.set_title(_("Save or replace an access token"))
        add_group.set_description(
            _("Use the GitHub organization or username that owns the repositories where workflows will run.")
        )

        self.token_org_entry = Adw.EntryRow()
        self.token_org_entry.set_title(_("GitHub organization or username"))
        self.token_org_entry.set_show_apply_button(False)
        add_group.add(self.token_org_entry)

        self.token_value_entry = Adw.PasswordEntryRow()
        self.token_value_entry.set_title(_("Personal access token"))
        self.token_value_entry.connect("entry-activated", self._on_save_token)
        add_group.add(self.token_value_entry)

        save_row = Adw.ActionRow()
        save_row.set_title(_("Store in the system keyring"))
        save_row.set_subtitle(_("The token value will be cleared from this form after it is stored."))
        self.save_token_button = Gtk.Button(label=_("Save access token"))
        self.save_token_button.set_valign(Gtk.Align.CENTER)
        self.save_token_button.add_css_class("suggested-action")
        self.save_token_button.connect("clicked", self._on_save_token)
        save_row.add_suffix(self.save_token_button)
        add_group.add(save_row)
        return add_group

    def _refresh_token_rows(self):
        self._replace_token_rows([], _("Checking the system keyring…"))

        def worker():
            entries = TokenStore.read_all()
            GLib.idle_add(self._replace_token_rows, entries, None)

        threading.Thread(target=worker, daemon=True).start()

    def _replace_token_rows(self, entries, empty_title):
        for row in self._token_rows:
            self.tokens_group.remove(row)
        self._token_rows = []

        if not entries:
            row = Adw.ActionRow()
            row.set_title(empty_title or _("No access tokens saved"))
            row.set_subtitle("" if empty_title else _("Use the form below when you want to run a GitHub workflow."))
            self.tokens_group.add(row)
            self._token_rows.append(row)
            return False

        for organization, _token in entries:
            row = Adw.ActionRow()
            row.set_title(organization)
            row.set_subtitle(_("Stored securely in the system keyring"))
            delete_button = Gtk.Button(icon_name="edit-delete-symbolic")
            delete_button.set_valign(Gtk.Align.CENTER)
            delete_button.add_css_class("destructive-action")
            delete_button.add_css_class("flat")
            delete_button.update_property(
                [Gtk.AccessibleProperty.LABEL], [_("Delete access token for {0}").format(organization)]
            )
            delete_button.connect("clicked", self._on_delete_token, organization)
            row.add_suffix(delete_button)
            self.tokens_group.add(row)
            self._token_rows.append(row)
        return False

    def _on_save_token(self, _widget):
        organization = self.token_org_entry.get_text().strip()
        token = self.token_value_entry.get_text().strip()
        if not organization or not token:
            self.parent_window.show_error_toast(_("Enter both the GitHub organization and the access token."))
            return

        self.save_token_button.set_sensitive(False)

        def worker():
            saved = TokenStore.upsert(organization, token) and TokenStore.get_token(organization) == token
            GLib.idle_add(self._finish_token_save, organization, token, saved)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_token_save(self, organization, token, saved):
        self.save_token_button.set_sensitive(True)
        if not saved:
            self.parent_window.show_error_dialog(
                _("The token could not be saved. Unlock the system keyring and try again.")
            )
            return False

        api = getattr(getattr(self.parent_window, "build_package", None), "github_api", None)
        if api and api.organization.lower() == organization.lower():
            api.token = token
            api.headers = {
                "Accept": "application/vnd.github.v3+json",
                "Authorization": f"token {token}",
            }
        self.token_org_entry.set_text("")
        self.token_value_entry.set_text("")
        self.parent_window.show_toast(_("Access token saved in the system keyring"))
        self._refresh_token_rows()
        return False

    def _on_delete_token(self, _button, organization):
        def worker():
            GLib.idle_add(self._finish_token_delete, TokenStore.delete(organization))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_token_delete(self, deleted):
        if deleted:
            self.parent_window.show_toast(_("Access token removed"))
            self._refresh_token_rows()
        else:
            self.parent_window.show_error_dialog(
                _("The token could not be removed. Unlock the system keyring and try again.")
            )
        return False


class BehaviorSettingsWidget(Gtk.Box):
    """Directly accessible local Git behavior settings."""

    STRATEGIES = ("interactive", "auto-ours", "auto-theirs", "manual")

    def __init__(self, parent_window, settings):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.parent_window = parent_window
        self.settings = settings
        self._is_syncing = False
        self._create_ui()
        self.sync_from_settings()

    def _create_ui(self):
        self.append(
            PageHero(
                "build-package-advanced",
                _("Choose how local Git operations behave"),
                _(
                    "These settings affect work in the current repository. They do not connect to GitHub and do not require an access token."
                ),
            )
        )

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.add_css_class("page-frame")
        self.append(content)
        content.append(self._create_conflict_group())
        content.append(self._create_safety_group())
        content.append(self._create_version_group())
        content.append(self._create_reset_group())

    def _create_conflict_group(self):
        conflict_group = Adw.PreferencesGroup()
        conflict_group.set_title(_("When downloaded and local changes conflict"))
        conflict_group.set_description(
            _("Choose whether the app asks you what to keep or stops so you can resolve the conflict manually.")
        )
        self.strategy_row = Adw.ComboRow()
        self.strategy_row.set_title(_("Conflict resolution method"))
        strategies = Gtk.StringList()
        strategies.append(_("Ask each time"))
        strategies.append(_("Keep local changes"))
        strategies.append(_("Keep downloaded changes"))
        strategies.append(_("Resolve manually"))
        self.strategy_row.set_model(strategies)
        self.strategy_row.connect("notify::selected", self._on_strategy_changed)
        conflict_group.add(self.strategy_row)
        return conflict_group

    def _create_safety_group(self):
        safety_group = Adw.PreferencesGroup()
        safety_group.set_title(_("Protection against data loss"))
        safety_group.set_description(_("Safety confirmations are part of the app and cannot be disabled."))
        confirm_row = Adw.ActionRow()
        confirm_row.set_title(_("Confirm destructive Git operations"))
        confirm_row.set_subtitle(
            _("The app asks before force push, hard reset, branch cleanup, tag deletion, or workflow deletion.")
        )
        confirm_row.add_prefix(Gtk.Image.new_from_icon_name("security-high-symbolic"))
        safety_group.add(confirm_row)
        return safety_group

    def _create_version_group(self):
        version_group = Adw.PreferencesGroup()
        version_group.set_title(_("Package version"))
        self.auto_version_row = Adw.SwitchRow()
        self.auto_version_row.set_title(_("Update the package version automatically"))
        self.auto_version_row.set_subtitle(
            _("When publishing a typed commit, calculate the next version from the selected change type.")
        )
        self.auto_version_row.connect("notify::active", self._on_auto_version_changed)
        version_group.add(self.auto_version_row)
        return version_group

    def _create_reset_group(self):
        reset_group = Adw.PreferencesGroup()
        reset_group.set_title(_("Restore the original configuration"))
        reset_row = Adw.ActionRow()
        reset_row.set_title(_("Reset all Build Package settings"))
        reset_row.set_subtitle(_("Disable optional GitHub workflows and restore the recommended local Git behavior."))
        reset_button = Gtk.Button(label=_("Reset settings"))
        reset_button.set_valign(Gtk.Align.CENTER)
        reset_button.add_css_class("destructive-action")
        reset_button.connect("clicked", self._on_reset_clicked)
        reset_row.add_suffix(reset_button)
        reset_group.add(reset_row)
        return reset_group

    def sync_from_settings(self):
        self._is_syncing = True
        strategy = self.settings.get("conflict_strategy", "interactive")
        self.strategy_row.set_selected(self.STRATEGIES.index(strategy) if strategy in self.STRATEGIES else 0)
        self.auto_version_row.set_active(self.settings.get("auto_version_bump", True))
        self._is_syncing = False

    def _on_strategy_changed(self, combo, _pspec):
        if self._is_syncing:
            return
        selected = combo.get_selected()
        if selected >= len(self.STRATEGIES):
            return
        if not self.settings.set("conflict_strategy", self.STRATEGIES[selected]):
            self.sync_from_settings()
            self.parent_window.show_error_toast(_("The conflict setting could not be saved."))
            return
        resolver = getattr(getattr(self.parent_window, "build_package", None), "conflict_resolver", None)
        if resolver:
            resolver.strategy = self.STRATEGIES[selected]

    def _on_auto_version_changed(self, switch, _pspec):
        if self._is_syncing:
            return
        if not self.settings.set("auto_version_bump", switch.get_active()):
            self.sync_from_settings()
            self.parent_window.show_error_toast(_("The version setting could not be saved."))

    def _on_reset_clicked(self, _button):
        dialog = Adw.MessageDialog.new(
            self.get_root(),
            _("Reset all settings?"),
            _("Optional GitHub workflows will be disabled and local Git behavior will return to its defaults."),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("reset", _("Reset settings"))
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_reset_response)
        dialog.present()

    def _on_reset_response(self, dialog, response):
        if response == "reset":
            if self.settings.reset():
                self.sync_from_settings()
                self.parent_window.refresh_features()
                self.parent_window.show_toast(_("Settings restored"))
            else:
                self.parent_window.show_error_dialog(_("Settings could not be restored. Try again."))
        dialog.close()
