#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/dialogs/preferences_dialog.py - Preferences dialog for GitRepo
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw
from core.translation_utils import _
from core.settings import Settings


class PreferencesDialog(Adw.PreferencesDialog):
    """Preferences dialog for configuring GitRepo features and behavior"""
    
    def __init__(self, parent_window, settings):
        super().__init__()
        self.settings = settings
        self.parent_window = parent_window
        self.needs_restart = False
        
        self.set_title(_("Preferences"))
        
        # Create preference pages
        self._create_features_page()
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
        features_group.set_description(
            _("Enable or disable optional features. Changes require restart.")
        )
        
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
        
        # Info about restart
        info_group = Adw.PreferencesGroup()
        
        info_row = Adw.ActionRow()
        info_row.set_title(_("ℹ️ Restart Required"))
        info_row.set_subtitle(_("Feature changes will take effect after restarting GitRepo"))
        info_row.set_activatable(False)
        info_group.add(info_row)
        
        page.add(info_group)
        
        self.add(page)
    
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
        org_list.append(_("Auto-detect from remote"))
        for org in Settings.PREDEFINED_ORGANIZATIONS:
            org_list.append(f"{org['name']} ({org['value']})")
        org_list.append(_("Custom..."))
        
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
        
        # Git operations group
        git_group = Adw.PreferencesGroup()
        git_group.set_title(_("Git Operations"))
        
        # Auto-fetch
        auto_fetch_row = Adw.SwitchRow()
        auto_fetch_row.set_title(_("Auto-fetch before operations"))
        auto_fetch_row.set_subtitle(_("Fetch remote changes before commits and merges"))
        auto_fetch_row.set_active(self.settings.get("auto_fetch", True))
        auto_fetch_row.connect("notify::active", self._on_setting_toggle, "auto_fetch")
        git_group.add(auto_fetch_row)
        
        # Auto-switch branch
        auto_switch_row = Adw.SwitchRow()
        auto_switch_row.set_title(_("Auto-switch to dev branch"))
        auto_switch_row.set_subtitle(_("Automatically switch to your development branch"))
        auto_switch_row.set_active(self.settings.get("auto_switch_branch", True))
        auto_switch_row.connect("notify::active", self._on_setting_toggle, "auto_switch_branch")
        git_group.add(auto_switch_row)
        
        # Confirm destructive
        confirm_row = Adw.SwitchRow()
        confirm_row.set_title(_("Confirm destructive operations"))
        confirm_row.set_subtitle(_("Ask before force push, reset --hard, etc"))
        confirm_row.set_active(self.settings.get("confirm_destructive", True))
        confirm_row.connect("notify::active", self._on_setting_toggle, "confirm_destructive")
        git_group.add(confirm_row)
        
        # Show git commands
        show_commands_row = Adw.SwitchRow()
        show_commands_row.set_title(_("Show git commands"))
        show_commands_row.set_subtitle(_("Display git commands before executing"))
        show_commands_row.set_active(self.settings.get("show_git_commands", False))
        show_commands_row.connect("notify::active", self._on_setting_toggle, "show_git_commands")
        git_group.add(show_commands_row)
        
        page.add(git_group)
        
        # Reset group
        reset_group = Adw.PreferencesGroup()
        reset_group.set_title(_("Reset"))
        
        reset_row = Adw.ActionRow()
        reset_row.set_title(_("Reset to Defaults"))
        reset_row.set_subtitle(_("Restore all settings to default values"))
        reset_row.set_activatable(True)
        
        reset_button = Gtk.Button()
        reset_button.set_label(_("Reset"))
        reset_button.set_valign(Gtk.Align.CENTER)
        reset_button.add_css_class("destructive-action")
        reset_button.connect("clicked", self._on_reset_clicked)
        reset_row.add_suffix(reset_button)
        
        reset_group.add(reset_row)
        
        page.add(reset_group)
        
        self.add(page)
    
    def _on_feature_toggle(self, switch, pspec, setting_key):
        """Handle feature toggle change"""
        self.settings.set(setting_key, switch.get_active())
        self.needs_restart = True
    
    def _on_setting_toggle(self, switch, pspec, setting_key):
        """Handle setting toggle change"""
        self.settings.set(setting_key, switch.get_active())
    
    def _on_org_selected(self, combo, pspec):
        """Handle organization selection"""
        selected = combo.get_selected()
        
        if selected == 0:
            # Auto-detect
            self.settings.set("organization_name", "")
            self.custom_org_row.set_visible(False)
        elif selected <= len(Settings.PREDEFINED_ORGANIZATIONS):
            # Predefined organization
            org = Settings.PREDEFINED_ORGANIZATIONS[selected - 1]
            self.settings.set("organization_name", org['value'])
            self.custom_org_row.set_visible(False)
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
            self.needs_restart = True
            # Refresh UI
            self._refresh_ui()
            
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
    
    def _on_closed(self, dialog):
        """Handle dialog close"""
        if self.needs_restart:
            # Show restart hint
            if hasattr(self.parent_window, 'show_toast'):
                self.parent_window.show_toast(
                    _("Restart GitRepo to apply feature changes")
                )
