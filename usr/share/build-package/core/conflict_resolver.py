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
from datetime import datetime
from .translation_utils import _

class ConflictResolver:
    """
    Intelligent conflict resolution with multiple strategies
    Tries automatic resolution first, falls back to interactive
    """

    def __init__(self, logger, menu_system, strategy="interactive", auto_accept_newer=False):
        self.logger = logger
        self.menu = menu_system
        self.strategy = strategy
        self.auto_accept_newer = auto_accept_newer

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

    @staticmethod
    def get_branch_last_commit_date(branch_name):
        """Gets the timestamp of the last commit on a branch"""
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%ct", f"origin/{branch_name}"],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode == 0 and result.stdout.strip():
                return int(result.stdout.strip())

            # Try without origin/ prefix
            result = subprocess.run(
                ["git", "log", "-1", "--format=%ct", branch_name],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode == 0 and result.stdout.strip():
                return int(result.stdout.strip())

            return 0
        except:
            return 0

    @staticmethod
    def compare_branches(branch1, branch2):
        """
        Compares two branches and returns which is more recent

        Returns:
            tuple: (newer_branch, older_branch, newer_date, older_date)
        """
        date1 = ConflictResolver.get_branch_last_commit_date(branch1)
        date2 = ConflictResolver.get_branch_last_commit_date(branch2)

        if date1 > date2:
            return (branch1, branch2, date1, date2)
        else:
            return (branch2, branch1, date2, date1)

    def get_conflict_preview(self, file_path, max_lines=15):
        """
        Gets a preview of the conflict in a file

        Returns:
            dict: {
                'ours': lines from current branch,
                'theirs': lines from incoming branch,
                'conflict_start': line number where conflict starts
            }
        """
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

            conflict_data = {
                'ours': [],
                'theirs': [],
                'conflict_start': -1,
                'conflict_count': 0
            }

            in_conflict = False
            in_ours = False
            conflict_num = 0

            for i, line in enumerate(lines):
                if line.startswith('<<<<<<< '):
                    in_conflict = True
                    in_ours = True
                    conflict_num += 1
                    if conflict_data['conflict_start'] == -1:
                        conflict_data['conflict_start'] = i + 1
                    conflict_data['conflict_count'] += 1
                elif line.startswith('======='):
                    in_ours = False
                elif line.startswith('>>>>>>> '):
                    in_conflict = False
                    in_ours = False
                elif in_conflict:
                    if in_ours:
                        if len(conflict_data['ours']) < max_lines:
                            conflict_data['ours'].append(line.rstrip())
                    else:
                        if len(conflict_data['theirs']) < max_lines:
                            conflict_data['theirs'].append(line.rstrip())

            return conflict_data
        except Exception as e:
            return {'ours': [f"Error reading file: {e}"], 'theirs': [], 'conflict_start': -1, 'conflict_count': 0}

    def resolve(self, current_branch=None, incoming_branch=None):
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

        # If branches provided, use enhanced interactive resolution
        if current_branch and incoming_branch:
            return self._resolve_interactive_enhanced(conflict_files, current_branch, incoming_branch)

        # Strategy selection (legacy mode)
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

    def _resolve_interactive_enhanced(self, conflict_files, current_branch, incoming_branch):
        """
        Enhanced interactive resolution with branch comparison
        Shows which branch is newer and allows file-by-file resolution
        """
        # Determine which branch is newer
        newer_branch, older_branch, newer_date, older_date = self.compare_branches(
            current_branch, incoming_branch
        )

        newer_date_str = datetime.fromtimestamp(newer_date).strftime("%Y-%m-%d %H:%M")
        older_date_str = datetime.fromtimestamp(older_date).strftime("%Y-%m-%d %H:%M")

        # Show conflict summary header
        self.logger.log("yellow", "")
        self.logger.log("yellow", "═" * 70)
        self.logger.log("yellow", _("⚠️  MERGE CONFLICTS DETECTED"))
        self.logger.log("yellow", "═" * 70)
        self.logger.log("cyan", _("Branch comparison:"))
        self.logger.log("green", "  ✓ {0} - {1} [{2}]".format(
            self.logger.format_branch_name(newer_branch),
            newer_date_str,
            _("NEWER")
        ))
        self.logger.log("dim", "  ✗ {0} - {1} [{2}]".format(
            self.logger.format_branch_name(older_branch),
            older_date_str,
            _("older")
        ))
        self.logger.log("yellow", "")
        self.logger.log("white", _("Conflicted files: {0}").format(len(conflict_files)))

        # If auto-accept newer is enabled, use it automatically
        if self.auto_accept_newer:
            self.logger.log("cyan", _("⚙️  Auto-resolution enabled: Using code from {0} (newer branch)").format(newer_branch))
            return self._resolve_with_branch(newer_branch, current_branch, conflict_files)

        # Interactive resolution: file by file
        self.logger.log("cyan", _("Starting interactive conflict resolution..."))
        self.logger.log("dim", _("You'll review each file and choose which version to keep"))
        input(_("\nPress Enter to start..."))

        for idx, file_path in enumerate(conflict_files):
            self.logger.log("cyan", "")
            self.logger.log("cyan", "─" * 70)
            self.logger.log("white", _("File {0}/{1}: {2}").format(idx + 1, len(conflict_files), file_path))
            self.logger.log("cyan", "─" * 70)

            # Get conflict preview
            conflict_info = self.get_conflict_preview(file_path)

            if conflict_info['conflict_count'] > 0:
                self.logger.log("yellow", _("Found {0} conflict(s) starting at line {1}").format(
                    conflict_info['conflict_count'],
                    conflict_info['conflict_start']
                ))

                # Show preview of conflict with branch labels
                self.logger.log("white", "")
                self.logger.log("dim", _("Preview of changes:"))

                # Determine labels based on which branch is current
                if current_branch == newer_branch:
                    current_label = _("{0} (YOUR branch, NEWER)").format(current_branch)
                    incoming_label = _("{0} (older)").format(incoming_branch)
                else:
                    current_label = _("{0} (YOUR branch, older)").format(current_branch)
                    incoming_label = _("{0} (NEWER)").format(incoming_branch)

                current_lines = conflict_info['ours']
                incoming_lines = conflict_info['theirs']

                # Show ours (current branch)
                self.logger.log("cyan", "╔═══ {0}".format(current_label))
                for line in current_lines[:10]:
                    self.logger.log("cyan", "║ {0}".format(line))
                if len(current_lines) > 10:
                    self.logger.log("cyan", "║ ... ({0} {1})".format(
                        len(current_lines) - 10,
                        _("more lines")
                    ))

                self.logger.log("yellow", "╠═══ {0} ═══".format(_("VS")))

                # Show theirs (incoming branch)
                self.logger.log("green", "╠═══ {0}".format(incoming_label))
                for line in incoming_lines[:10]:
                    self.logger.log("green", "║ {0}".format(line))
                if len(incoming_lines) > 10:
                    self.logger.log("green", "║ ... ({0} {1})".format(
                        len(incoming_lines) - 10,
                        _("more lines")
                    ))
                self.logger.log("white", "╚═══")

            # Ask user which version to use
            options = [
                _("Use {0} version [{1}] - Recommended").format(
                    self.logger.format_branch_name(newer_branch),
                    _("NEWER")
                ),
                _("Use {0} version [{1}]").format(
                    self.logger.format_branch_name(older_branch),
                    _("older")
                ),
                _("Skip - I'll edit manually")
            ]

            choice = self.menu.show_menu(
                _("Choose version for: {0}").format(file_path),
                options,
                default_index=0  # Default to newer
            )

            if choice is None or choice[0] == 2:
                # Manual edit
                self.logger.log("yellow", _("⚠️  Skipping {0} - you'll need to edit it manually").format(file_path))
                self.logger.log("white", _("To resolve manually:"))
                self.logger.log("white", f"  1. Edit: {file_path}")
                self.logger.log("white", _("  2. Remove conflict markers: <<<<<<< ======= >>>>>>>"))
                self.logger.log("white", f"  3. Run: git add {file_path}")
                continue

            # Determine which branch to use based on choice
            if choice[0] == 0:
                branch_to_use = newer_branch
            else:
                branch_to_use = older_branch

            # Resolve the file
            if self._resolve_file_with_branch(file_path, branch_to_use, current_branch):
                self.logger.log("green", _("✓ Resolved: Using {0} version").format(self.logger.format_branch_name(branch_to_use)))
            else:
                self.logger.log("red", _("✗ Failed to resolve {0}").format(file_path))
                return False

        # Check if all conflicts are resolved
        remaining_conflicts = self.get_conflict_files()

        if remaining_conflicts:
            self.logger.log("yellow", "")
            self.logger.log("yellow", _("⚠️  Some files still have unresolved conflicts:"))
            for file in remaining_conflicts:
                self.logger.log("yellow", f"  • {file}")
            self.logger.log("white", _("Please resolve them manually and run 'git add <file>'"))
            input(_("\nPress Enter to continue..."))
            return False

        # All resolved!
        self.logger.log("green", "")
        self.logger.log("green", "═" * 70)
        self.logger.log("green", _("✓ All conflicts resolved successfully!"))
        self.logger.log("green", "═" * 70)
        input(_("\nPress Enter to continue..."))
        return True

    def _resolve_file_with_branch(self, file_path, branch_to_use, current_branch):
        """Resolves a single file conflict using the specified branch's version"""
        try:
            if branch_to_use == current_branch:
                # Keep current version (ours)
                subprocess.run(["git", "checkout", "--ours", file_path], check=True)
            else:
                # Keep incoming version (theirs)
                subprocess.run(["git", "checkout", "--theirs", file_path], check=True)

            # Stage the resolved file
            subprocess.run(["git", "add", file_path], check=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def _resolve_with_branch(self, branch_to_use, current_branch, conflict_files):
        """Resolves all conflicts using the specified branch's version"""
        try:
            for file_path in conflict_files:
                if not self._resolve_file_with_branch(file_path, branch_to_use, current_branch):
                    self.logger.log("red", _("Failed to resolve {0}").format(file_path))
                    return False

            self.logger.log("green", _("✓ All conflicts auto-resolved using {0} version").format(
                self.logger.format_branch_name(branch_to_use)
            ))
            input(_("\nPress Enter to continue..."))
            return True
        except Exception as e:
            self.logger.log("red", _("Error during auto-resolution: {0}").format(e))
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
