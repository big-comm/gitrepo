#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# core/settings_menu.py - Interactive settings menu for CLI
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

from .translation_utils import _

class SettingsMenu:
    """Interactive settings menu for CLI"""

    def __init__(self, settings, logger, menu_system):
        self.settings = settings
        self.logger = logger
        self.menu = menu_system

    def show(self):
        """Show settings menu"""
        while True:
            # Build current status
            mode = self.settings.get("operation_mode", "safe")
            conflict = self.settings.get("conflict_strategy", "interactive")
            auto_fetch = "✓" if self.settings.get("auto_fetch", True) else "✗"
            auto_switch = "✓" if self.settings.get("auto_switch_branch", True) else "✗"
            show_cmds = "✓" if self.settings.get("show_git_commands", False) else "✗"

            options = [
                f"Operation Mode: {mode}",
                f"Conflict Strategy: {conflict}",
                f"{auto_fetch} Auto-fetch before operations",
                f"{auto_switch} Auto-switch to user branch",
                f"{show_cmds} Show git commands",
                _("Reset to defaults"),
                _("Back")
            ]

            result = self.menu.show_menu(_("Settings"), options)

            if result is None or result[0] == 6:  # Back
                return

            choice = result[0]

            if choice == 0:  # Operation mode
                self._change_operation_mode()
            elif choice == 1:  # Conflict strategy
                self._change_conflict_strategy()
            elif choice == 2:  # Auto-fetch
                self._toggle_setting("auto_fetch")
            elif choice == 3:  # Auto-switch
                self._toggle_setting("auto_switch_branch")
            elif choice == 4:  # Show commands
                self._toggle_setting("show_git_commands")
            elif choice == 5:  # Reset
                if self.menu.confirm(_("Reset all settings to defaults?")):
                    self.settings.reset()
                    self.logger.log("green", _("✓ Settings reset to defaults"))

    def _change_operation_mode(self):
        """Change operation mode"""
        current = self.settings.get("operation_mode", "safe")

        modes = [
            ("safe", _("Safe Mode"), _("More control, confirm important actions")),
            ("quick", _("Quick Mode"), _("Fast automation, minimal confirmations")),
            ("expert", _("Expert Mode"), _("Maximum automation, for experienced users"))
        ]

        options = []
        for mode_id, name, desc in modes:
            marker = "●" if mode_id == current else "○"
            options.append(f"{marker} {name} - {desc}")

        options.append(_("Back"))

        result = self.menu.show_menu(_("Select Operation Mode"), options)

        if result is None or result[0] == len(modes):  # Back
            return

        selected_mode = modes[result[0]][0]
        self.settings.set("operation_mode", selected_mode)
        self.logger.log("green", _("✓ Operation mode changed to: {0}").format(selected_mode))

    def _change_conflict_strategy(self):
        """Change conflict resolution strategy"""
        current = self.settings.get("conflict_strategy", "interactive")

        strategies = [
            ("interactive", _("Interactive"), _("Ask for each conflict file")),
            ("auto-ours", _("Auto Keep Ours"), _("Always keep our changes")),
            ("auto-theirs", _("Auto Accept Remote"), _("Always accept remote changes")),
            ("manual", _("Manual"), _("Stop and let me resolve manually"))
        ]

        options = []
        for strat_id, name, desc in strategies:
            marker = "●" if strat_id == current else "○"
            options.append(f"{marker} {name} - {desc}")

        options.append(_("Back"))

        result = self.menu.show_menu(_("Select Conflict Strategy"), options)

        if result is None or result[0] == len(strategies):  # Back
            return

        selected_strategy = strategies[result[0]][0]
        self.settings.set("conflict_strategy", selected_strategy)
        self.logger.log("green", _("✓ Conflict strategy changed to: {0}").format(selected_strategy))

    def _toggle_setting(self, key):
        """Toggle a boolean setting"""
        current = self.settings.get(key, False)
        new_value = not current
        self.settings.set(key, new_value)

        status = _("enabled") if new_value else _("disabled")
        self.logger.log("green", _("✓ {0} {1}").format(key, status))

    def show_current_mode_info(self):
        """Display current mode information"""
        mode = self.settings.get("operation_mode", "safe")
        mode_config = self.settings.get_mode_config()

        mode_names = {
            "safe": _("Safe Mode"),
            "quick": _("Quick Mode"),
            "expert": _("Expert Mode")
        }

        mode_descriptions = {
            "safe": _("More control, confirm important actions"),
            "quick": _("Fast automation, minimal confirmations"),
            "expert": _("Maximum automation, for experienced users")
        }

        self.logger.log("cyan", "═" * 60)
        self.logger.log("cyan", _("Current Mode: {0}").format(mode_names.get(mode, mode)))
        self.logger.log("white", mode_descriptions.get(mode, ""))
        self.logger.log("cyan", "─" * 60)
        self.logger.log("dim", _("Auto-resolve conflicts: {0}").format(
            "✓" if mode_config["auto_resolve_conflicts"] else "✗"))
        self.logger.log("dim", _("Auto-switch branches: {0}").format(
            "✓" if mode_config["auto_switch_branches"] else "✗"))
        self.logger.log("dim", _("Auto-merge: {0}").format(
            "✓" if mode_config["auto_merge"] else "✗"))
        self.logger.log("dim", _("Show preview: {0}").format(
            "✓" if mode_config["show_preview"] else "✗"))
        self.logger.log("cyan", "═" * 60)
