#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/dialogs/settings_dialog.py - Visual settings dialog for GUI
#

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject
from core.translation_utils import _
from core.settings import Settings

class SettingsDialog(Adw.PreferencesWindow):
    """Visual settings dialog using libadwaita"""

    __gsignals__ = {
        'settings-changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, parent, settings):
        super().__init__(
            transient_for=parent,
            modal=True
        )

        self.settings = settings
        self.set_title(_("Settings"))
        self.set_search_enabled(True)

        self.create_ui()
        self.load_settings()

    def create_ui(self):
        """Create settings UI"""

        # ===== OPERATION MODE PAGE =====
        operation_page = Adw.PreferencesPage()
        operation_page.set_title(_("Operation"))
        operation_page.set_icon_name("system-run-symbolic")

        # Operation Mode Group
        mode_group = Adw.PreferencesGroup()
        mode_group.set_title(_("Operation Mode"))
        mode_group.set_description(_("Choose how the application should operate"))

        # Mode selection using ComboRow
        self.mode_row = Adw.ComboRow()
        self.mode_row.set_title(_("Mode"))
        self.mode_row.set_subtitle(_("Select your preferred operation mode"))

        # Create string list for modes
        modes_list = Gtk.StringList()
        modes_list.append(_("Safe - Show previews and confirmations"))
        modes_list.append(_("Quick - Fast with minimal confirmations"))
        modes_list.append(_("Expert - Maximum automation, no confirmations"))
        self.mode_row.set_model(modes_list)

        self.mode_row.connect('notify::selected', self.on_mode_changed)
        mode_group.add(self.mode_row)

        operation_page.add(mode_group)

        # ===== CONFLICTS PAGE =====
        conflicts_page = Adw.PreferencesPage()
        conflicts_page.set_title(_("Conflicts"))
        conflicts_page.set_icon_name("dialog-warning-symbolic")

        # Conflict Strategy Group
        conflict_group = Adw.PreferencesGroup()
        conflict_group.set_title(_("Conflict Resolution"))
        conflict_group.set_description(_("How to handle merge conflicts"))

        # Strategy selection
        self.strategy_row = Adw.ComboRow()
        self.strategy_row.set_title(_("Strategy"))
        self.strategy_row.set_subtitle(_("Select conflict resolution strategy"))

        strategies_list = Gtk.StringList()
        strategies_list.append(_("Interactive - Ask for each file"))
        strategies_list.append(_("Auto-ours - Always keep local changes"))
        strategies_list.append(_("Auto-theirs - Always accept remote changes"))
        strategies_list.append(_("Manual - Stop and let me resolve"))
        self.strategy_row.set_model(strategies_list)

        self.strategy_row.connect('notify::selected', self.on_strategy_changed)
        conflict_group.add(self.strategy_row)

        conflicts_page.add(conflict_group)

        # ===== AUTOMATION PAGE =====
        automation_page = Adw.PreferencesPage()
        automation_page.set_title(_("Automation"))
        automation_page.set_icon_name("emblem-system-symbolic")

        # Git Operations Group
        git_group = Adw.PreferencesGroup()
        git_group.set_title(_("Git Operations"))
        git_group.set_description(_("Automatic git operations"))

        # Auto-fetch toggle
        self.auto_fetch_row = Adw.SwitchRow()
        self.auto_fetch_row.set_title(_("Auto-fetch"))
        self.auto_fetch_row.set_subtitle(_("Automatically fetch from remote before operations"))
        self.auto_fetch_row.connect('notify::active', self.on_auto_fetch_changed)
        git_group.add(self.auto_fetch_row)

        # Auto-switch branch toggle
        self.auto_switch_row = Adw.SwitchRow()
        self.auto_switch_row.set_title(_("Auto-switch branch"))
        self.auto_switch_row.set_subtitle(_("Automatically switch to your development branch"))
        self.auto_switch_row.connect('notify::active', self.on_auto_switch_changed)
        git_group.add(self.auto_switch_row)

        # Auto-pull toggle
        self.auto_pull_row = Adw.SwitchRow()
        self.auto_pull_row.set_title(_("Auto-pull"))
        self.auto_pull_row.set_subtitle(_("Automatically pull latest changes"))
        self.auto_pull_row.connect('notify::active', self.on_auto_pull_changed)
        git_group.add(self.auto_pull_row)

        automation_page.add(git_group)

        # Version Management Group
        version_group = Adw.PreferencesGroup()
        version_group.set_title(_("Version Management"))

        # Auto version bump toggle
        self.auto_version_row = Adw.SwitchRow()
        self.auto_version_row.set_title(_("Auto-version bump"))
        self.auto_version_row.set_subtitle(_("Automatically increment version based on commit type"))
        self.auto_version_row.connect('notify::active', self.on_auto_version_changed)
        version_group.add(self.auto_version_row)

        automation_page.add(version_group)

        # ===== ADVANCED PAGE =====
        advanced_page = Adw.PreferencesPage()
        advanced_page.set_title(_("Advanced"))
        advanced_page.set_icon_name("preferences-system-symbolic")

        # Display Group
        display_group = Adw.PreferencesGroup()
        display_group.set_title(_("Display"))

        # Show git commands toggle
        self.show_commands_row = Adw.SwitchRow()
        self.show_commands_row.set_title(_("Show git commands"))
        self.show_commands_row.set_subtitle(_("Display git commands being executed"))
        self.show_commands_row.connect('notify::active', self.on_show_commands_changed)
        display_group.add(self.show_commands_row)

        # Confirm destructive toggle
        self.confirm_destructive_row = Adw.SwitchRow()
        self.confirm_destructive_row.set_title(_("Confirm destructive operations"))
        self.confirm_destructive_row.set_subtitle(_("Always confirm potentially destructive operations"))
        self.confirm_destructive_row.connect('notify::active', self.on_confirm_destructive_changed)
        display_group.add(self.confirm_destructive_row)

        advanced_page.add(display_group)

        # Reset Group
        reset_group = Adw.PreferencesGroup()
        reset_group.set_title(_("Reset"))

        # Reset button
        reset_row = Adw.ActionRow()
        reset_row.set_title(_("Reset to defaults"))
        reset_row.set_subtitle(_("Restore all settings to their default values"))

        reset_button = Gtk.Button()
        reset_button.set_label(_("Reset"))
        reset_button.set_valign(Gtk.Align.CENTER)
        reset_button.add_css_class("destructive-action")
        reset_button.connect('clicked', self.on_reset_clicked)
        reset_row.add_suffix(reset_button)

        reset_group.add(reset_row)
        advanced_page.add(reset_group)

        # Add all pages
        self.add(operation_page)
        self.add(conflicts_page)
        self.add(automation_page)
        self.add(advanced_page)

    def load_settings(self):
        """Load current settings into UI"""
        # Operation mode
        mode = self.settings.get("operation_mode", "safe")
        mode_index = {"safe": 0, "quick": 1, "expert": 2}.get(mode, 0)
        self.mode_row.set_selected(mode_index)

        # Conflict strategy
        strategy = self.settings.get("conflict_strategy", "interactive")
        strategy_index = {
            "interactive": 0,
            "auto-ours": 1,
            "auto-theirs": 2,
            "manual": 3
        }.get(strategy, 0)
        self.strategy_row.set_selected(strategy_index)

        # Toggles
        self.auto_fetch_row.set_active(self.settings.get("auto_fetch", True))
        self.auto_switch_row.set_active(self.settings.get("auto_switch_branch", True))
        self.auto_pull_row.set_active(self.settings.get("auto_pull", False))
        self.auto_version_row.set_active(self.settings.get("auto_version_bump", True))
        self.show_commands_row.set_active(self.settings.get("show_git_commands", False))
        self.confirm_destructive_row.set_active(self.settings.get("confirm_destructive", True))

    def on_mode_changed(self, combo_row, param):
        """Handle mode selection change"""
        selected = combo_row.get_selected()
        modes = ["safe", "quick", "expert"]
        if selected < len(modes):
            self.settings.set("operation_mode", modes[selected])
            self.emit('settings-changed')

    def on_strategy_changed(self, combo_row, param):
        """Handle strategy selection change"""
        selected = combo_row.get_selected()
        strategies = ["interactive", "auto-ours", "auto-theirs", "manual"]
        if selected < len(strategies):
            self.settings.set("conflict_strategy", strategies[selected])
            self.emit('settings-changed')

    def on_auto_fetch_changed(self, switch, param):
        """Handle auto-fetch toggle"""
        self.settings.set("auto_fetch", switch.get_active())
        self.emit('settings-changed')

    def on_auto_switch_changed(self, switch, param):
        """Handle auto-switch toggle"""
        self.settings.set("auto_switch_branch", switch.get_active())
        self.emit('settings-changed')

    def on_auto_pull_changed(self, switch, param):
        """Handle auto-pull toggle"""
        self.settings.set("auto_pull", switch.get_active())
        self.emit('settings-changed')

    def on_auto_version_changed(self, switch, param):
        """Handle auto-version toggle"""
        self.settings.set("auto_version_bump", switch.get_active())
        self.emit('settings-changed')

    def on_show_commands_changed(self, switch, param):
        """Handle show commands toggle"""
        self.settings.set("show_git_commands", switch.get_active())
        self.emit('settings-changed')

    def on_confirm_destructive_changed(self, switch, param):
        """Handle confirm destructive toggle"""
        self.settings.set("confirm_destructive", switch.get_active())
        self.emit('settings-changed')

    def on_reset_clicked(self, button):
        """Handle reset button click"""
        # Show confirmation dialog
        dialog = Adw.MessageDialog.new(
            self,
            _("Reset Settings?"),
            _("All settings will be restored to their default values. This cannot be undone.")
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("reset", _("Reset"))
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(dialog, response):
            if response == "reset":
                self.settings.reset_to_defaults()
                self.load_settings()
                self.emit('settings-changed')

        dialog.connect("response", on_response)
        dialog.present()
