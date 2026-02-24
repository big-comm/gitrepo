#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/dialogs/preferences_dialog.py - Preferences dialog for GitRepo
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")


from core.settings import Settings
from core.token_store import TokenStore
from core.translation_utils import _
from gi.repository import Adw, Gio, Gtk


class PreferencesDialog(Adw.PreferencesDialog):
    """Preferences dialog for configuring GitRepo features and behavior"""

    def __init__(self, parent_window, settings):
        super().__init__()
        self.settings = settings
        self.parent_window = parent_window
        self.needs_restart = False

        self.set_title(_("Preferences"))
        self.set_content_width(560)

        # Create preference pages
        self._create_features_page()
        self._create_tokens_page()
        self._create_organization_page()
        self._create_behavior_page()

        # Connect close signal
        self.connect("closed", self._on_closed)

    def _create_features_page(self):
        """Create Features page with feature toggles"""
        page = Adw.PreferencesPage()
        page.set_title(_("Features"))
        page.set_icon_name("applications-system-symbolic")

        # Feature toggles group
        features_group = Adw.PreferencesGroup()
        features_group.set_title(_("Optional Features"))
        features_group.set_description(_("Enable or disable optional features."))

        # Package Generation toggle
        self.package_row = Adw.SwitchRow()
        self.package_row.set_title(_("Package Generation"))
        self.package_row.set_subtitle(_("Build and deploy packages via GitHub Actions"))
        self.package_row.set_active(self.settings.get("package_features_enabled", False))
        self.package_row.connect("notify::active", self._on_feature_toggle, "package_features_enabled")
        features_group.add(self.package_row)

        # AUR Package toggle
        self.aur_row = Adw.SwitchRow()
        self.aur_row.set_title(_("AUR Packages"))
        self.aur_row.set_subtitle(_("Import and build packages from Arch User Repository"))
        self.aur_row.set_active(self.settings.get("aur_features_enabled", False))
        self.aur_row.connect("notify::active", self._on_feature_toggle, "aur_features_enabled")
        features_group.add(self.aur_row)

        # Note: ISO Builder is a separate project (build-iso)

        page.add(features_group)

        self.add(page)

    # ── helpers for token file ─────────────────────────────────────────────

    def _refresh_token_rows(self):
        """Rebuild the token list rows inside tokens_group."""
        if hasattr(self, '_token_rows'):
            for row in self._token_rows:
                self.tokens_group.remove(row)
        self._token_rows = []

        entries = TokenStore.read_all()
        if not entries:
            row = Adw.ActionRow()
            row.set_title(_("No tokens configured"))
            row.set_subtitle(_("Use the form below to add a token"))
            self.tokens_group.add(row)
            self._token_rows.append(row)
            return

        for org, tok in entries:
            row = Adw.ActionRow()
            row.set_title(org)
            masked = tok[:8] + "·····" if len(tok) > 8 else tok
            row.set_subtitle(masked)

            del_btn = Gtk.Button()
            del_btn.set_icon_name("edit-delete-symbolic")
            del_btn.set_valign(Gtk.Align.CENTER)
            del_btn.add_css_class("destructive-action")
            del_btn.add_css_class("flat")
            del_btn.update_property([Gtk.AccessibleProperty.LABEL], [_("Delete token for {0}").format(org)])
            del_btn.connect('clicked', self._on_delete_token, org)
            row.add_suffix(del_btn)

            self.tokens_group.add(row)
            self._token_rows.append(row)

    # ── page builder ──────────────────────────────────────────────────────

    def _create_tokens_page(self):
        """Create GitHub Tokens page"""
        page = Adw.PreferencesPage()
        page.set_title(_("Tokens"))
        page.set_icon_name("dialog-password-symbolic")

        # — Guide group —
        guide_group = Adw.PreferencesGroup()
        guide_group.set_title(_("GitHub Personal Access Token"))
        guide_group.set_description(
            _("A Classic token is required for package build and deployment operations.")
        )

        link_row = Adw.ActionRow()
        link_row.set_title(_("Generate Token (Classic)"))
        link_row.set_subtitle("github.com/settings/tokens → Generate new token (classic)")
        link_row.set_activatable(True)
        link_row.add_prefix(Gtk.Image.new_from_icon_name("web-browser-symbolic"))
        link_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        link_row.connect('activated', lambda _r: Gio.AppInfo.launch_default_for_uri(
            "https://github.com/settings/tokens", None
        ))
        guide_group.add(link_row)

        scopes_row = Adw.ActionRow()
        scopes_row.set_title(_("Required Scopes"))
        scopes_row.set_subtitle("repo  ·  workflow  ·  write:packages  ·  delete:packages  ·  read:org")
        scopes_row.set_activatable(False)
        scopes_row.add_prefix(Gtk.Image.new_from_icon_name("emblem-ok-symbolic"))
        guide_group.add(scopes_row)

        page.add(guide_group)

        # — Configured tokens —
        self.tokens_group = Adw.PreferencesGroup()
        self.tokens_group.set_title(_("Configured Tokens"))
        self.tokens_group.set_description(_("Stored in ~/.config/gitrepo/github_token"))
        self._token_rows = []
        self._refresh_token_rows()
        page.add(self.tokens_group)

        # — Add / update token —
        add_group = Adw.PreferencesGroup()
        add_group.set_title(_("Add / Update Token"))
        add_group.set_description(
            _("Enter the organization or username that owns the token.")
        )

        self.token_org_entry = Adw.EntryRow()
        self.token_org_entry.set_title(_("Organization or Username (e.g. big-comm)"))
        add_group.add(self.token_org_entry)

        self.token_value_entry = Adw.PasswordEntryRow()
        self.token_value_entry.set_title(_("Token  (ghp_…)"))
        add_group.add(self.token_value_entry)

        save_row = Adw.ActionRow()
        save_btn = Gtk.Button()
        save_btn.set_label(_("Save Token"))
        save_btn.set_valign(Gtk.Align.CENTER)
        save_btn.add_css_class("suggested-action")
        save_btn.connect('clicked', self._on_save_token)
        save_row.add_suffix(save_btn)
        add_group.add(save_row)

        page.add(add_group)
        self.add(page)

    # ── token callbacks ───────────────────────────────────────────────────

    def _on_save_token(self, _button):
        """Save or update a token entry."""
        org = self.token_org_entry.get_text().strip()
        tok = self.token_value_entry.get_text().strip()
        if not org or not tok:
            return

        if TokenStore.upsert(org, tok):
            # Update live token in github_api if org matches current session
            if hasattr(self.parent_window, 'build_package') and self.parent_window.build_package:
                api = self.parent_window.build_package.github_api
                if api.organization.lower() == org.lower():
                    api.token = tok
                    api.headers = {
                        "Accept": "application/vnd.github.v3+json",
                        "Authorization": f"token {tok}",
                    }

            self.token_org_entry.set_text("")
            self.token_value_entry.set_text("")
            self._refresh_token_rows()

    def _on_delete_token(self, _button, org):
        """Remove a token entry from the file."""
        TokenStore.delete(org)
        self._refresh_token_rows()

    def _create_organization_page(self):
        """Create Organization page for GitHub settings"""
        page = Adw.PreferencesPage()
        page.set_title(_("Organization"))
        page.set_icon_name("system-users-symbolic")
        
        # Organization group
        org_group = Adw.PreferencesGroup()
        org_group.set_title(_("GitHub Organization"))
        org_group.set_description(
            _("Configure your GitHub organization for package workflows")
        )
        
        # Predefined organizations dropdown
        self.org_combo = Adw.ComboRow()
        self.org_combo.set_title(_("Organization"))
        self.org_combo.set_subtitle(_("Select or enter custom organization"))
        
        # Create string list with predefined + custom option
        org_list = Gtk.StringList()
        org_list.append(_("Auto-detect"))
        for org in Settings.PREDEFINED_ORGANIZATIONS:
            # Use simple name for better display
            org_list.append(org['name'])
        org_list.append(_("Custom"))
        
        self.org_combo.set_model(org_list)
        
        # Set current selection
        current_org = self.settings.get("organization_name", "")
        if not current_org:
            self.org_combo.set_selected(0)  # Auto-detect
        else:
            # Find in predefined
            found = False
            for i, org in enumerate(Settings.PREDEFINED_ORGANIZATIONS):
                if org['value'] == current_org:
                    self.org_combo.set_selected(i + 1)
                    found = True
                    break
            if not found:
                self.org_combo.set_selected(len(Settings.PREDEFINED_ORGANIZATIONS) + 1)  # Custom
        
        self.org_combo.connect("notify::selected", self._on_org_selected)
        org_group.add(self.org_combo)
        
        # Custom organization entry (shown when "Custom" is selected)
        self.custom_org_row = Adw.EntryRow()
        self.custom_org_row.set_title(_("Custom Organization"))
        self.custom_org_row.set_text(self.settings.get("organization_name", ""))
        self.custom_org_row.connect("changed", self._on_custom_org_changed)
        
        # Show/hide based on selection
        current_org = self.settings.get("organization_name", "")
        is_custom = current_org and not any(
            org['value'] == current_org for org in Settings.PREDEFINED_ORGANIZATIONS
        )
        self.custom_org_row.set_visible(is_custom)
        
        org_group.add(self.custom_org_row)
        
        page.add(org_group)
        
        # Workflow repository group
        workflow_group = Adw.PreferencesGroup()
        workflow_group.set_title(_("Workflow Configuration"))
        workflow_group.set_description(
            _("Repository containing GitHub Actions workflows")
        )
        
        self.workflow_row = Adw.EntryRow()
        self.workflow_row.set_title(_("Workflow Repository"))
        self.workflow_row.set_text(self.settings.get("workflow_repository", ""))
        self.workflow_row.connect("changed", self._on_workflow_changed)
        workflow_group.add(self.workflow_row)
        
        # Hint with actual default value from config.py
        hint_row = Adw.ActionRow()
        hint_row.set_title(_("💡 Tip"))
        hint_row.set_subtitle(_("Leave empty to use default: big-comm/build-package"))
        hint_row.set_activatable(False)
        workflow_group.add(hint_row)
        
        page.add(workflow_group)
        
        self.add(page)
    
    def _create_behavior_page(self):
        """Create Behavior page for operation settings"""
        page = Adw.PreferencesPage()
        page.set_title(_("Behavior"))
        page.set_icon_name("preferences-system-symbolic")

        # ── Operation mode ────────────────────────────────────────────────
        mode_group = Adw.PreferencesGroup()
        mode_group.set_title(_("Operation Mode"))
        mode_group.set_description(_("Choose how the application should operate"))

        self.mode_row = Adw.ComboRow()
        self.mode_row.set_title(_("Mode"))
        self.mode_row.set_subtitle(_("Select your preferred operation mode"))
        modes_list = Gtk.StringList()
        modes_list.append(_("Safe – Show previews and confirmations"))
        modes_list.append(_("Quick – Fast with minimal confirmations"))
        modes_list.append(_("Expert – Maximum automation, no confirmations"))
        self.mode_row.set_model(modes_list)
        mode_index = {"safe": 0, "quick": 1, "expert": 2}.get(self.settings.get("operation_mode", "safe"), 0)
        self.mode_row.set_selected(mode_index)
        self.mode_row.connect("notify::selected", self._on_mode_changed)
        mode_group.add(self.mode_row)

        self.strategy_row = Adw.ComboRow()
        self.strategy_row.set_title(_("Conflict Strategy"))
        self.strategy_row.set_subtitle(_("How to resolve merge conflicts"))
        strategies_list = Gtk.StringList()
        strategies_list.append(_("Interactive – Ask for each file"))
        strategies_list.append(_("Auto-ours – Always keep local changes"))
        strategies_list.append(_("Auto-theirs – Always accept remote changes"))
        strategies_list.append(_("Manual – Stop and let me resolve"))
        self.strategy_row.set_model(strategies_list)
        strategy_index = {
            "interactive": 0,
            "auto-ours": 1,
            "auto-theirs": 2,
            "manual": 3,
        }.get(self.settings.get("conflict_strategy", "interactive"), 0)
        self.strategy_row.set_selected(strategy_index)
        self.strategy_row.connect("notify::selected", self._on_strategy_changed)
        mode_group.add(self.strategy_row)

        page.add(mode_group)

        # ── Git operations ────────────────────────────────────────────────
        git_group = Adw.PreferencesGroup()
        git_group.set_title(_("Git Operations"))

        auto_fetch_row = Adw.SwitchRow()
        auto_fetch_row.set_title(_("Auto-fetch before operations"))
        auto_fetch_row.set_subtitle(_("Fetch remote changes before commits and merges"))
        auto_fetch_row.set_active(self.settings.get("auto_fetch", True))
        auto_fetch_row.connect("notify::active", self._on_setting_toggle, "auto_fetch")
        git_group.add(auto_fetch_row)

        auto_switch_row = Adw.SwitchRow()
        auto_switch_row.set_title(_("Auto-switch to dev branch"))
        auto_switch_row.set_subtitle(_("Automatically switch to your development branch"))
        auto_switch_row.set_active(self.settings.get("auto_switch_branch", True))
        auto_switch_row.connect("notify::active", self._on_setting_toggle, "auto_switch_branch")
        git_group.add(auto_switch_row)

        auto_pull_row = Adw.SwitchRow()
        auto_pull_row.set_title(_("Auto-pull latest changes"))
        auto_pull_row.set_subtitle(_("Automatically pull remote changes before operations"))
        auto_pull_row.set_active(self.settings.get("auto_pull", False))
        auto_pull_row.connect("notify::active", self._on_setting_toggle, "auto_pull")
        git_group.add(auto_pull_row)

        confirm_row = Adw.SwitchRow()
        confirm_row.set_title(_("Confirm destructive operations"))
        confirm_row.set_subtitle(_("Ask before force push, reset --hard, etc"))
        confirm_row.set_active(self.settings.get("confirm_destructive", True))
        confirm_row.connect("notify::active", self._on_setting_toggle, "confirm_destructive")
        git_group.add(confirm_row)

        show_commands_row = Adw.SwitchRow()
        show_commands_row.set_title(_("Show git commands"))
        show_commands_row.set_subtitle(_("Display git commands before executing"))
        show_commands_row.set_active(self.settings.get("show_git_commands", False))
        show_commands_row.connect("notify::active", self._on_setting_toggle, "show_git_commands")
        git_group.add(show_commands_row)

        page.add(git_group)

        # ── Version management ────────────────────────────────────────────
        version_group = Adw.PreferencesGroup()
        version_group.set_title(_("Version Management"))

        auto_version_row = Adw.SwitchRow()
        auto_version_row.set_title(_("Auto-version bump"))
        auto_version_row.set_subtitle(_("Automatically increment version based on commit type"))
        auto_version_row.set_active(self.settings.get("auto_version_bump", True))
        auto_version_row.connect("notify::active", self._on_setting_toggle, "auto_version_bump")
        version_group.add(auto_version_row)

        page.add(version_group)

        # ── Reset ─────────────────────────────────────────────────────────
        reset_group = Adw.PreferencesGroup()
        reset_group.set_title(_("Reset"))

        reset_row = Adw.ActionRow()
        reset_row.set_title(_("Reset to Defaults"))
        reset_row.set_subtitle(_("Restore all settings to default values"))

        reset_button = Gtk.Button()
        reset_button.set_label(_("Reset"))
        reset_button.set_valign(Gtk.Align.CENTER)
        reset_button.add_css_class("destructive-action")
        reset_button.connect("clicked", self._on_reset_clicked)
        reset_row.add_suffix(reset_button)

        reset_group.add(reset_row)
        page.add(reset_group)

        self.add(page)

    def _on_mode_changed(self, combo, pspec):
        """Save operation_mode from combo selection."""
        modes = ["safe", "quick", "expert"]
        idx = combo.get_selected()
        if idx < len(modes):
            self.settings.set("operation_mode", modes[idx])

    def _on_strategy_changed(self, combo, pspec):
        """Save conflict_strategy from combo selection."""
        strategies = ["interactive", "auto-ours", "auto-theirs", "manual"]
        idx = combo.get_selected()
        if idx < len(strategies):
            self.settings.set("conflict_strategy", strategies[idx])
    
    def _on_feature_toggle(self, switch, pspec, setting_key):
        """Handle feature toggle change"""
        self.settings.set(setting_key, switch.get_active())
        if hasattr(self.parent_window, "refresh_features"):
            self.parent_window.refresh_features()
    
    def _on_setting_toggle(self, switch, pspec, setting_key):
        """Handle setting toggle change"""
        self.settings.set(setting_key, switch.get_active())
    
    def _on_org_selected(self, combo, pspec):
        """Handle organization selection"""
        selected = combo.get_selected()
        
        if selected == 0:
            # Auto-detect
            self.settings.set("organization_name", "")
            self.settings.set("workflow_repository", "")  # Clear workflow too
            self.workflow_row.set_text("")
            self.custom_org_row.set_visible(False)
        elif selected <= len(Settings.PREDEFINED_ORGANIZATIONS):
            # Predefined organization
            org = Settings.PREDEFINED_ORGANIZATIONS[selected - 1]
            self.settings.set("organization_name", org['value'])
            self.custom_org_row.set_visible(False)
            
            # Auto-fill workflow repository
            workflow = f"{org['value']}/build-package"
            self.settings.set("workflow_repository", workflow)
            self.workflow_row.set_text(workflow)
        else:
            # Custom
            self.custom_org_row.set_visible(True)
            # Don't clear the value, user might want to edit existing
    
    def _on_custom_org_changed(self, entry):
        """Handle custom organization entry change"""
        self.settings.set("organization_name", entry.get_text())
    
    def _on_workflow_changed(self, entry):
        """Handle workflow repository entry change"""
        self.settings.set("workflow_repository", entry.get_text())
    
    def _on_reset_clicked(self, button):
        """Handle reset to defaults"""
        dialog = Adw.MessageDialog(
            transient_for=self,
            modal=True
        )
        dialog.set_heading(_("Reset Settings?"))
        dialog.set_body(
            _("All settings will be restored to their default values. This cannot be undone.")
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("reset", _("Reset"))
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        
        dialog.connect("response", self._on_reset_response)
        dialog.present()
    
    def _on_reset_response(self, dialog, response):
        """Handle reset confirmation response"""
        if response == "reset":
            self.settings.reset()
            # Refresh UI
            self._refresh_ui()
            if hasattr(self.parent_window, "refresh_features"):
                self.parent_window.refresh_features()
            # Show toast
            if hasattr(self.parent_window, 'show_toast'):
                self.parent_window.show_toast(_("Settings reset to defaults"))
    
    def _refresh_ui(self):
        """Refresh UI to reflect current settings"""
        self.package_row.set_active(self.settings.get("package_features_enabled", False))
        self.aur_row.set_active(self.settings.get("aur_features_enabled", False))
        self.org_combo.set_selected(0)
        self.custom_org_row.set_text("")
        self.workflow_row.set_text("")
        mode_index = {"safe": 0, "quick": 1, "expert": 2}.get(self.settings.get("operation_mode", "safe"), 0)
        self.mode_row.set_selected(mode_index)
        strategy_index = {
            "interactive": 0,
            "auto-ours": 1,
            "auto-theirs": 2,
            "manual": 3,
        }.get(self.settings.get("conflict_strategy", "interactive"), 0)
        self.strategy_row.set_selected(strategy_index)
    
    def _on_closed(self, dialog):
        """Sync conflict_strategy to the running build_package instance."""
        if hasattr(self.parent_window, "build_package") and self.parent_window.build_package:
            bp = self.parent_window.build_package
            if hasattr(bp, "conflict_resolver"):
                bp.conflict_resolver.strategy = self.settings.get("conflict_strategy", "interactive")
