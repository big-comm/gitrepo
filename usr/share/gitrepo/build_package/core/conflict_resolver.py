#
# core/conflict_resolver.py - Intelligent conflict resolution system
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import os
from gitrepo.common import child_process as subprocess
from gitrepo.common.child_process import authorize_destructive_git
from datetime import datetime

from .git_utils import GitUtils
from gitrepo.common.translation import _


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
        self.repo_root = GitUtils.get_repo_root_path()

    def _get_absolute_path(self, file_path):
        """Get absolute path for a file relative to git repo root"""
        if os.path.isabs(file_path):
            return file_path
        return os.path.join(self.repo_root, file_path) if self.repo_root else file_path

    def _get_conflict_type(self, file_path):
        """
        Detect the type of conflict for a file.

        Returns a dict with:
            'type': 'content' | 'modify_delete' | 'add_add'
            'ours_exists': bool - whether 'ours' (stage 2) version exists
            'theirs_exists': bool - whether 'theirs' (stage 3) version exists
        """
        try:
            result = subprocess.run(
                ["git", "ls-files", "-u", "--", file_path],
                capture_output=True,
                text=True,
                check=False,
                cwd=self.repo_root,
            )
            lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
            stages = set()
            for line in lines:
                parts = line.split("\t")[0].split()  # mode hash stage
                if len(parts) >= 3:
                    stages.add(int(parts[2]))

            ours_exists = 2 in stages
            theirs_exists = 3 in stages

            if ours_exists and theirs_exists:
                return {"type": "content", "ours_exists": True, "theirs_exists": True}
            elif ours_exists and not theirs_exists:
                # Ours exists but theirs doesn't = theirs deleted the file
                return {"type": "modify_delete", "ours_exists": True, "theirs_exists": False}
            elif theirs_exists and not ours_exists:
                # Theirs exists but ours doesn't = ours deleted the file
                return {"type": "modify_delete", "ours_exists": False, "theirs_exists": True}
            else:
                return {"type": "content", "ours_exists": True, "theirs_exists": True}
        except Exception:
            return {"type": "content", "ours_exists": True, "theirs_exists": True}

    def has_conflicts(self):
        """Check if there are unresolved conflicts"""
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"], capture_output=True, text=True, check=False
        )
        return bool(result.stdout.strip())

    def _confirm_conflict_deletion(self, file_path, reason):
        command = f"git rm -f -- {file_path}"
        if not self.menu.confirm(
            _("Delete {0} while resolving this conflict?\nReason: {1}\n{2}").format(file_path, reason, command),
            default_yes=False,
        ):
            self.logger.log("yellow", _("File deletion cancelled: {0}").format(file_path))
            return False
        with authorize_destructive_git():
            subprocess.run(["git", "rm", "-f", "--", file_path], check=True, cwd=self.repo_root, capture_output=True)
        return True

    def get_conflict_files(self):
        """Get list of files with conflicts"""
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"], capture_output=True, text=True, check=False
        )
        files = result.stdout.strip().split("\n")
        return [f for f in files if f]

    @staticmethod
    def get_branch_last_commit_date(branch_name):
        """Gets the timestamp of the last commit on a branch"""
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%ct", f"origin/{branch_name}"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                return int(result.stdout.strip())

            # Try without origin/ prefix
            result = subprocess.run(
                ["git", "log", "-1", "--format=%ct", branch_name], capture_output=True, text=True, check=False
            )
            if result.returncode == 0 and result.stdout.strip():
                return int(result.stdout.strip())

            return 0
        except (subprocess.CalledProcessError, ValueError):
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
                conflict_info = self._get_conflict_type(file)

                if not conflict_info["ours_exists"]:
                    # Our side deleted the file - remove it
                    self.logger.log("dim", _("  Removing {0} (deleted in our version)").format(file))
                    if not self._confirm_conflict_deletion(file, _("deleted in the local version")):
                        return False
                else:
                    subprocess.run(["git", "checkout", "--ours", file], check=True, cwd=self.repo_root)
                    subprocess.run(["git", "add", file], check=True, cwd=self.repo_root)

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
                conflict_info = self._get_conflict_type(file)

                if not conflict_info["theirs_exists"]:
                    # Remote side deleted the file - remove it
                    self.logger.log("dim", _("  Removing {0} (deleted in remote version)").format(file))
                    if not self._confirm_conflict_deletion(file, _("deleted in the incoming version")):
                        return False
                else:
                    subprocess.run(["git", "checkout", "--theirs", file], check=True, cwd=self.repo_root)
                    subprocess.run(["git", "add", file], check=True, cwd=self.repo_root)

            self.logger.log("green", _("✓ Conflicts resolved (accepted remote)"))
            return True
        except subprocess.CalledProcessError as e:
            self.logger.log("red", _("Failed to auto-resolve: {0}").format(e))
            return False

    def _resolve_interactive(self, conflict_files):
        """Ask for one explicit resolution per conflicted file."""
        conflict_files = self._resolve_compiled_catalogs(conflict_files)
        for file_path in conflict_files:
            if not self._resolve_one_interactive(file_path):
                return False
        self.logger.log("green", _("✓ All conflicts resolved!"))
        return True

    def _resolve_compiled_catalogs(self, conflict_files):
        catalogs = [path for path in conflict_files if path.lower().endswith(".mo")]
        if len(catalogs) <= 3:
            return conflict_files
        question = _("Accept the incoming version for all {0} compiled .mo files?").format(len(catalogs))
        if not self.menu.confirm(question, default_yes=False):
            return conflict_files
        unresolved = []
        for path in catalogs:
            if not self._resolve_index_side(path, "theirs"):
                unresolved.append(path)
        return unresolved + [path for path in conflict_files if path not in catalogs]

    def _resolve_one_interactive(self, file_path):
        options = [
            _("Keep our version"),
            _("Accept remote version"),
            _("Keep both (create .ours and .theirs files)"),
            _("Edit manually"),
            _("Show diff"),
        ]
        while True:
            self._show_conflict_preview(file_path)
            result = self.menu.show_menu(_("How to resolve: {0}").format(file_path), options)
            if result is None or result[0] == 3:
                self.logger.log("yellow", _("Resolve {0} manually, then stage it with git add.").format(file_path))
                return False
            if result[0] == 4:
                self._show_detailed_diff(file_path)
                continue
            if result[0] == 2:
                self._keep_both_versions(file_path)
                return True
            side = "ours" if result[0] == 0 else "theirs"
            return self._resolve_index_side(file_path, side)

    def _resolve_index_side(self, file_path, side):
        conflict = self._get_conflict_type(file_path)
        side_exists = conflict[f"{side}_exists"]
        if not side_exists:
            reason = (
                _("deleted in the selected local version") if side == "ours" else _("deleted in the incoming version")
            )
            return self._confirm_conflict_deletion(file_path, reason)
        try:
            subprocess.run(["git", "checkout", f"--{side}", file_path], check=True, cwd=self.repo_root)
            subprocess.run(["git", "add", file_path], check=True, cwd=self.repo_root)
            return True
        except subprocess.CalledProcessError:
            stage = "2" if side == "ours" else "3"
            return self._restore_index_stage(file_path, stage)

    def _restore_index_stage(self, file_path, stage):
        try:
            result = subprocess.run(
                ["git", "show", f":{stage}:{file_path}"],
                capture_output=True,
                check=True,
                cwd=self.repo_root,
            )
            with open(self._get_absolute_path(file_path), "wb") as target:
                target.write(result.stdout)
            subprocess.run(["git", "add", file_path], check=True, cwd=self.repo_root)
            return True
        except (OSError, subprocess.CalledProcessError) as error:
            self.logger.log("red", _("Could not resolve {0}: {1}").format(file_path, error))
            return False

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
        """Offer the newer branch first while keeping every file decision explicit."""
        newer, older, newer_date, older_date = self.compare_branches(current_branch, incoming_branch)
        self.logger.log(
            "yellow",
            _("Conflicts detected. Newer branch: {0} ({1}); older branch: {2} ({3}).").format(
                newer,
                self._format_commit_date(newer_date),
                older,
                self._format_commit_date(older_date),
            ),
        )
        if self.auto_accept_newer:
            question = _("Use the newer branch '{0}' for all {1} conflicted files?").format(newer, len(conflict_files))
            if self.menu.confirm(question, default_yes=False):
                return self._resolve_with_branch(newer, current_branch, conflict_files)
        for file_path in conflict_files:
            self._show_conflict_preview(file_path)
            options = [
                _("Use {0} version (newer)").format(newer),
                _("Use {0} version (older)").format(older),
                _("Leave unresolved for manual editing"),
            ]
            choice = self.menu.show_menu(_("Choose version for: {0}").format(file_path), options, default_index=0)
            if choice is None or choice[0] == 2:
                self.logger.log("yellow", _("{0} remains unresolved for manual editing.").format(file_path))
                continue
            selected_branch = newer if choice[0] == 0 else older
            if not self._resolve_file_with_branch(file_path, selected_branch, current_branch):
                self.logger.log("red", _("Failed to resolve {0}").format(file_path))
                return False
        remaining = self.get_conflict_files()
        if remaining:
            self.logger.log("yellow", _("Unresolved files: {0}").format(", ".join(remaining)))
            return False
        self.logger.log("green", _("✓ All conflicts resolved successfully!"))
        return True

    @staticmethod
    def _format_commit_date(timestamp):
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M") if timestamp else _("unknown")

    def _resolve_file_with_branch(self, file_path, branch_to_use, current_branch):
        """Resolve a file using the index side represented by the chosen branch."""
        side = "ours" if branch_to_use == current_branch else "theirs"
        return self._resolve_index_side(file_path, side)

    def _resolve_with_branch(self, branch_to_use, current_branch, conflict_files):
        """Resolves all conflicts using the specified branch's version"""
        try:
            for file_path in conflict_files:
                if not self._resolve_file_with_branch(file_path, branch_to_use, current_branch):
                    self.logger.log("red", _("Failed to resolve {0}").format(file_path))
                    return False

            self.logger.log(
                "green",
                _("✓ All conflicts auto-resolved using {0} version").format(
                    self.logger.format_branch_name(branch_to_use)
                ),
            )
            return True
        except Exception as e:
            self.logger.log("red", _("Error during auto-resolution: {0}").format(e))
            return False

    def _show_conflict_preview(self, file):
        """Show brief preview of conflict"""
        try:
            abs_path = self._get_absolute_path(file)
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Count conflict markers
            conflicts = content.count("<<<<<<<")

            self.logger.log("cyan", _("File: {0}").format(file))
            self.logger.log("cyan", _("Conflicts: {0}").format(conflicts))

            # Show first few lines of conflict
            lines = content.split("\n")
            in_conflict = False
            preview_lines = []

            for line in lines[:50]:  # First 50 lines max
                if "<<<<<<< " in line:
                    in_conflict = True
                    preview_lines.append(line)
                elif "=======" in line and in_conflict:
                    preview_lines.append(line)
                elif ">>>>>>> " in line and in_conflict:
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
        """Show a bounded textual combined diff without launching another program."""
        result = subprocess.run(
            ["git", "diff", "--cc", "--", file],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            cwd=self.repo_root,
        )
        if result.returncode not in (0, 1):
            self.logger.log("yellow", _("Could not produce a diff for {0}.").format(file))
            return
        lines = result.stdout.splitlines()
        if not lines:
            self.logger.log("yellow", _("No textual diff is available; the file may be binary."))
            return
        self.logger.log("cyan", _("Conflict diff for {0}:").format(file))
        for line in lines[:120]:
            self.logger.log("dim", line)
        if len(lines) > 120:
            self.logger.log("dim", _("… {0} additional lines omitted").format(len(lines) - 120))

    def _keep_both_versions(self, file):
        """Save both versions in separate files"""
        try:
            abs_path = self._get_absolute_path(file)

            # Save ours
            subprocess.run(["git", "checkout", "--ours", file], check=True, cwd=self.repo_root)
            ours_file_abs = f"{abs_path}.ours"
            subprocess.run(["cp", abs_path, ours_file_abs], check=True)

            # Save theirs
            subprocess.run(["git", "checkout", "--theirs", file], check=True, cwd=self.repo_root)
            theirs_file_abs = f"{abs_path}.theirs"
            subprocess.run(["cp", abs_path, theirs_file_abs], check=True)

            # Keep theirs as main (user can choose later)
            subprocess.run(["git", "add", file], check=True, cwd=self.repo_root)

            self.logger.log("cyan", _("Created files:"))
            self.logger.log("cyan", f"  - {ours_file_abs} (our version)")
            self.logger.log("cyan", f"  - {theirs_file_abs} (remote version)")
            self.logger.log("cyan", f"  - {file} (using remote version)")

        except subprocess.CalledProcessError as e:
            self.logger.log("red", _("Error creating versions: {0}").format(e))
            raise
