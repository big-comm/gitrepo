#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# core/conflict_resolver.py - Intelligent conflict resolution system
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import subprocess
import os
from .translation_utils import _

class ConflictResolver:
    """
    Intelligent conflict resolution with multiple strategies
    Tries automatic resolution first, falls back to interactive
    """

    def __init__(self, logger, menu_system, strategy="interactive"):
        self.logger = logger
        self.menu = menu_system
        self.strategy = strategy

    def has_conflicts(self):
        """Check if there are unresolved conflicts"""
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            capture_output=True,
            text=True,
            check=False
        )
        return bool(result.stdout.strip())

    def get_conflict_files(self):
        """Get list of files with conflicts"""
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            capture_output=True,
            text=True,
            check=False
        )
        files = result.stdout.strip().split('\n')
        return [f for f in files if f]

    def resolve(self):
        """
        Main resolution method - tries strategies in order
        Returns True if resolved, False if needs manual intervention
        """
        if not self.has_conflicts():
            return True

        conflict_files = self.get_conflict_files()
        self.logger.log("yellow", _("⚠️  Detected {0} file(s) with conflicts").format(len(conflict_files)))

        for f in conflict_files:
            self.logger.log("yellow", f"   - {f}")

        # Strategy selection
        if self.strategy == "auto-ours":
            return self._resolve_auto_ours(conflict_files)
        elif self.strategy == "auto-theirs":
            return self._resolve_auto_theirs(conflict_files)
        elif self.strategy == "interactive":
            return self._resolve_interactive(conflict_files)
        else:  # manual
            return self._resolve_manual(conflict_files)

    def _resolve_auto_ours(self, conflict_files):
        """Accept our version for all conflicts"""
        try:
            self.logger.log("cyan", _("Resolving conflicts: keeping our changes..."))

            for file in conflict_files:
                subprocess.run(["git", "checkout", "--ours", file], check=True)
                subprocess.run(["git", "add", file], check=True)

            self.logger.log("green", _("✓ Conflicts resolved (kept our changes)"))
            return True
        except subprocess.CalledProcessError as e:
            self.logger.log("red", _("Failed to auto-resolve: {0}").format(e))
            return False

    def _resolve_auto_theirs(self, conflict_files):
        """Accept their version for all conflicts"""
        try:
            self.logger.log("cyan", _("Resolving conflicts: accepting remote changes..."))

            for file in conflict_files:
                subprocess.run(["git", "checkout", "--theirs", file], check=True)
                subprocess.run(["git", "add", file], check=True)

            self.logger.log("green", _("✓ Conflicts resolved (accepted remote)"))
            return True
        except subprocess.CalledProcessError as e:
            self.logger.log("red", _("Failed to auto-resolve: {0}").format(e))
            return False

    def _resolve_interactive(self, conflict_files):
        """Interactive resolution - ask for each file"""
        self.logger.log("cyan", _("Interactive conflict resolution..."))

        for file in conflict_files:
            # Show file preview
            self._show_conflict_preview(file)

            # Ask user what to do
            options = [
                _("Keep our version"),
                _("Accept remote version"),
                _("Keep both (create .ours and .theirs files)"),
                _("Edit manually (abort and fix)"),
                _("Show diff")
            ]

            result = self.menu.show_menu(
                _("How to resolve: {0}").format(file),
                options
            )

            if result is None:
                return False  # User cancelled

            choice = result[0]

            if choice == 0:  # Keep ours
                subprocess.run(["git", "checkout", "--ours", file], check=True)
                subprocess.run(["git", "add", file], check=True)
                self.logger.log("green", _("✓ Kept our version of {0}").format(file))

            elif choice == 1:  # Accept theirs
                subprocess.run(["git", "checkout", "--theirs", file], check=True)
                subprocess.run(["git", "add", file], check=True)
                self.logger.log("green", _("✓ Accepted remote version of {0}").format(file))

            elif choice == 2:  # Keep both
                self._keep_both_versions(file)
                self.logger.log("green", _("✓ Created both versions of {0}").format(file))

            elif choice == 3:  # Manual
                self.logger.log("yellow", _("Manual resolution required for {0}").format(file))
                self.logger.log("yellow", _("Use 'git status' to see conflicted files"))
                self.logger.log("yellow", _("Edit files, then 'git add' and run this again"))
                return False

            elif choice == 4:  # Show diff
                self._show_detailed_diff(file)
                # Ask again for this file (recursive call for single file)
                return self._resolve_interactive([file])

        self.logger.log("green", _("✓ All conflicts resolved!"))
        return True

    def _resolve_manual(self, conflict_files):
        """Manual resolution - just inform user"""
        self.logger.log("yellow", _("Manual conflict resolution needed"))
        self.logger.log("yellow", _("Conflicted files:"))

        for f in conflict_files:
            self.logger.log("yellow", f"  - {f}")

        self.logger.log("cyan", _("Steps to resolve:"))
        self.logger.log("cyan", _("1. Edit the files above and fix conflicts"))
        self.logger.log("cyan", _("2. Run: git add <file>"))
        self.logger.log("cyan", _("3. Run this command again"))

        return False

    def _show_conflict_preview(self, file):
        """Show brief preview of conflict"""
        try:
            with open(file, 'r', encoding='utf-8') as f:
                content = f.read()

            # Count conflict markers
            conflicts = content.count('<<<<<<<')

            self.logger.log("cyan", _("File: {0}").format(file))
            self.logger.log("cyan", _("Conflicts: {0}").format(conflicts))

            # Show first few lines of conflict
            lines = content.split('\n')
            in_conflict = False
            preview_lines = []

            for line in lines[:50]:  # First 50 lines max
                if '<<<<<<< ' in line:
                    in_conflict = True
                    preview_lines.append(line)
                elif '=======' in line and in_conflict:
                    preview_lines.append(line)
                elif '>>>>>>> ' in line and in_conflict:
                    preview_lines.append(line)
                    break
                elif in_conflict:
                    preview_lines.append(line)

            if preview_lines:
                self.logger.log("dim", "─" * 60)
                for line in preview_lines[:20]:  # Show max 20 lines
                    self.logger.log("dim", line)
                self.logger.log("dim", "─" * 60)

        except Exception as e:
            self.logger.log("yellow", _("Could not preview file: {0}").format(e))

    def _show_detailed_diff(self, file):
        """Show detailed diff for a file"""
        try:
            # Get ours version
            result_ours = subprocess.run(
                ["git", "show", f":2:{file}"],
                capture_output=True,
                text=True,
                check=False
            )

            # Get theirs version
            result_theirs = subprocess.run(
                ["git", "show", f":3:{file}"],
                capture_output=True,
                text=True,
                check=False
            )

            self.logger.log("cyan", "═" * 60)
            self.logger.log("cyan", _("OUR VERSION:"))
            self.logger.log("cyan", "─" * 60)
            for line in result_ours.stdout.split('\n')[:30]:
                self.logger.log("green", line)

            self.logger.log("cyan", "═" * 60)
            self.logger.log("cyan", _("THEIR VERSION:"))
            self.logger.log("cyan", "─" * 60)
            for line in result_theirs.stdout.split('\n')[:30]:
                self.logger.log("yellow", line)

            self.logger.log("cyan", "═" * 60)

        except Exception as e:
            self.logger.log("red", _("Could not show diff: {0}").format(e))

    def _keep_both_versions(self, file):
        """Save both versions in separate files"""
        try:
            # Save ours
            subprocess.run(["git", "checkout", "--ours", file], check=True)
            ours_file = f"{file}.ours"
            subprocess.run(["cp", file, ours_file], check=True)

            # Save theirs
            subprocess.run(["git", "checkout", "--theirs", file], check=True)
            theirs_file = f"{file}.theirs"
            subprocess.run(["cp", file, theirs_file], check=True)

            # Keep theirs as main (user can choose later)
            subprocess.run(["git", "add", file], check=True)

            self.logger.log("cyan", _("Created files:"))
            self.logger.log("cyan", f"  - {ours_file} (our version)")
            self.logger.log("cyan", f"  - {theirs_file} (remote version)")
            self.logger.log("cyan", f"  - {file} (using remote version)")

        except subprocess.CalledProcessError as e:
            self.logger.log("red", _("Error creating versions: {0}").format(e))
            raise
