#
# core/settings_menu.py - Interactive settings menu for CLI
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

from gitrepo.common.translation import _


class SettingsMenu:
    """Interactive settings menu for CLI"""

    def __init__(self, settings, logger, menu_system):
        self.settings = settings
        self.logger = logger
        self.menu = menu_system

    def show(self):
        """Show settings menu"""
        while True:
            conflict = self.settings.get("conflict_strategy", "interactive")

            options = [
                _("Conflict Strategy: {0}").format(conflict),
                _("Reset to defaults"),
                _("Back"),
            ]

            result = self.menu.show_menu(_("Settings"), options)

            if result is None or result[0] == 2:  # Back
                return

            choice = result[0]

            if choice == 0:  # Conflict strategy
                self._change_conflict_strategy()
            elif choice == 1:  # Reset
                if self.menu.confirm(_("Reset all settings to defaults?")):
                    self.settings.reset()
                    self.logger.log("green", _("✓ Settings reset to defaults"))

    def _change_conflict_strategy(self):
        """Change conflict resolution strategy"""
        current = self.settings.get("conflict_strategy", "interactive")

        strategies = [
            ("interactive", _("Interactive"), _("Ask for each conflict file")),
            ("auto-ours", _("Auto Keep Ours"), _("Always keep our changes")),
            ("auto-theirs", _("Auto Accept Remote"), _("Always accept remote changes")),
            ("manual", _("Manual"), _("Stop and let me resolve manually")),
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
