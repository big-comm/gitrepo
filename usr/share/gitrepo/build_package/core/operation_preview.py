#
# core/operation_preview.py - Preview and confirm operations before execution
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

from gitrepo.common import child_process as subprocess
from gitrepo.common.child_process import authorize_destructive_git
from gitrepo.common.translation import _


class Operation:
    """Represents a single git operation"""

    def __init__(self, description, commands, destructive=False, callback=None):
        """
        Args:
            description: Human-readable description
            commands: List of command arrays or single command array
            destructive: Whether this operation modifies history or forces changes
            callback: Optional function to call instead of running commands
        """
        self.description = description
        # Handle empty commands (callback-only operations)
        if commands and len(commands) > 0:
            self.commands = commands if isinstance(commands[0], list) else [commands]
        else:
            self.commands = []
        self.destructive = destructive
        self.callback = callback
        self.success = False

    def _execute_callback(self, logger):
        try:
            self.callback()
            return True
        except Exception as error:
            logger.log("red", _("Failed: {0}").format(error))
            return False

    @staticmethod
    def _is_merge_conflict(command, error) -> bool:
        output = f"{error.stdout or ''}\n{error.stderr or ''}".lower()
        is_merge_command = len(command) >= 2 and command[:2] in (["git", "merge"], ["git", "pull"])
        return is_merge_command and any(marker in output for marker in ("conflict", "automatic merge failed"))

    def _run_command(self, command):
        if self.destructive:
            with authorize_destructive_git():
                return subprocess.run_git(command, capture_output=True, text=True, check=True, intent="destructive")
        return subprocess.run_git(command, capture_output=True, text=True, check=True, intent="ordinary")

    def _handle_command_failure(self, logger, command, error):
        if self._is_merge_conflict(command, error):
            logger.log("yellow", _("Merge conflict detected; resolution is required."))
            return "conflict"
        detail = (error.stderr or error.stdout or str(error)).strip()
        logger.log("red", _("Command failed: {0}").format(" ".join(command)))
        logger.log("red", detail)
        return False

    def execute(self, logger):
        """Execute the callback or argv sequence and retain its result state."""
        if self.callback:
            result = self._execute_callback(logger)
        else:
            result = self._execute_commands(logger)
        self.success = result is True
        return result

    def _execute_commands(self, logger):
        for command in self.commands:
            try:
                result = self._run_command(command)
            except subprocess.CalledProcessError as error:
                return self._handle_command_failure(logger, command, error)
            if result.stdout:
                logger.log("dim", result.stdout.strip())
        return True

    def get_command_preview(self):
        """Get readable command preview"""
        previews = []
        for cmd in self.commands:
            if isinstance(cmd, list):
                previews.append(" ".join(cmd))
            else:
                previews.append(str(cmd))
        return " && ".join(previews)


class OperationPlan:
    """
    Manages a sequence of operations with preview and execution
    """

    def __init__(self, logger, menu_system, show_preview=True, dry_run=False):
        self.logger = logger
        self.menu = menu_system
        self.show_preview = show_preview
        self.dry_run = dry_run
        self.operations = []

    def add(self, description, commands, destructive=False, callback=None):
        """Add operation to the plan"""
        op = Operation(description, commands, destructive, callback)
        self.operations.append(op)
        return op

    def has_destructive_operations(self):
        """Check if plan contains destructive operations"""
        return any(op.destructive for op in self.operations)

    def preview(self):
        """Show preview of all operations"""
        if not self.operations:
            self.logger.log("yellow", _("No operations planned"))
            return

        self.logger.log("cyan", "")
        self.logger.log("cyan", "═" * 70)
        self.logger.log("cyan", _("OPERATION PLAN"))
        self.logger.log("cyan", "═" * 70)

        for i, op in enumerate(self.operations, 1):
            # Icon and color based on operation type
            if op.destructive:
                icon = "⚠️ "
                style = "yellow"
            else:
                icon = "▶ "
                style = "cyan"

            # Show description
            self.logger.log(style, f"{icon}{i}. {op.description}")

            # Show command if available
            if not op.callback:
                cmd_preview = op.get_command_preview()
                self.logger.log("dim", f"   $ {cmd_preview}")

        self.logger.log("cyan", "═" * 70)

        # Summary
        total = len(self.operations)
        destructive = sum(1 for op in self.operations if op.destructive)

        if destructive > 0:
            self.logger.log("yellow", _("⚠️  {0} destructive operation(s) out of {1} total").format(destructive, total))
        else:
            self.logger.log("green", _("ℹ️  {0} safe operation(s)").format(total))

        self.logger.log("cyan", "")

    def confirm(self):
        """Show preview and ask for confirmation"""
        if not self.operations:
            return True

        has_destructive_operations = self.has_destructive_operations()
        if not self.show_preview and not has_destructive_operations:
            return True

        self.preview()

        # Ask for confirmation
        if has_destructive_operations:
            question = _("⚠️  Proceed with these operations? (includes destructive actions)")
        else:
            question = _("Proceed with these operations?")

        return self.menu.confirm(question)

    def _simulate(self):
        self.logger.log("yellow", _("Dry-run mode; no operations will execute."))
        for index, operation in enumerate(self.operations, 1):
            self.logger.log("cyan", f"[{index}/{len(self.operations)}] {operation.description}")
            if operation.commands:
                self.logger.log("dim", f"$ {operation.get_command_preview()}")
        return True

    def _execute_operations(self, show_progress):
        for index, operation in enumerate(self.operations, 1):
            if show_progress:
                self.logger.log("cyan", f"[{index}/{len(self.operations)}] {operation.description}")
            result = operation.execute(self.logger)
            if result == "conflict":
                self.logger.log("yellow", _("Conflicts detected; resolution is required."))
                return "conflict"
            if result is not True:
                self.logger.log("red", _("Operation failed; remaining steps were not executed."))
                return False
        return True

    def execute(self, show_progress=True):
        """Execute the reviewed sequence or simulate it in dry-run mode."""
        if not self.operations:
            return True
        if self.dry_run:
            return self._simulate()
        if show_progress:
            self.logger.log("cyan", _("Executing {0} operation(s)...").format(len(self.operations)))
        return self._execute_operations(show_progress)

    def execute_with_confirmation(self, show_progress=True):
        """Show preview, confirm, then execute"""
        if not self.confirm():
            self.logger.log("yellow", _("Operation cancelled by user"))
            return False

        return self.execute(show_progress)

    def clear(self):
        """Clear all operations"""
        self.operations = []
