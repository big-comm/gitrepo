#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# core/operation_preview.py - Preview and confirm operations before execution
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import subprocess
from .translation_utils import _

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
        self.executed = False
        self.success = False
        self.has_conflict = False  # Flag para indicar conflito de merge

    def execute(self, logger):
        """Execute the operation"""
        if self.callback:
            try:
                self.callback()
                self.executed = True
                self.success = True
                return True
            except Exception as e:
                logger.log("red", _("✗ Failed: {0}").format(e))
                self.executed = True
                self.success = False
                return False

        for cmd in self.commands:
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=True
                )
                if result.stdout:
                    logger.log("dim", result.stdout.strip())
            except subprocess.CalledProcessError as e:
                # Check stderr and stdout for error analysis
                stderr_lower = e.stderr.lower() if e.stderr else ""
                stdout_lower = e.stdout.lower() if e.stdout else ""
                combined = stderr_lower + stdout_lower
                
                # Detect git command type
                is_git_pull = len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "pull"
                is_git_push = len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "push"
                is_git_merge = len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "merge"

                # === CONFLICT DETECTION ===
                # Check if this is a merge conflict (not a fatal error)
                conflict_indicators = ["conflict", "merge conflict", "automatic merge failed"]
                has_conflict = any(indicator in combined for indicator in conflict_indicators)
                
                if has_conflict and (is_git_merge or is_git_pull):
                    # This is a CONFLICT - not a fatal error!
                    # Log informatively and return "conflict" status
                    logger.log("yellow", "")
                    logger.log("yellow", _("⚠️ Merge conflict detected!"))
                    logger.log("cyan", _("The conflict resolver will help you resolve this."))
                    
                    # Show conflict details
                    if e.stdout and e.stdout.strip():
                        for line in e.stdout.strip().split('\n'):
                            if 'CONFLICT' in line or 'conflict' in line.lower():
                                logger.log("yellow", f"  {line}")
                    
                    self.executed = True
                    self.success = False
                    self.has_conflict = True  # Mark as conflict
                    return "conflict"  # Special return value

                if is_git_pull:
                    # These are REAL errors for pull (not conflicts)
                    real_error_indicators = [
                        "error:",
                        "fatal:",
                        "could not",
                        "failed to",
                        "unable to",
                        "refusing to merge",
                        "unrelated histories"
                    ]

                    # Check if it contains real error keywords
                    has_real_error = any(indicator in combined for indicator in real_error_indicators)

                    # If no real error, just show informational output and continue
                    if not has_real_error:
                        # Show the output as informational
                        if e.stderr:
                            logger.log("dim", e.stderr.strip())
                        if e.stdout:
                            logger.log("dim", e.stdout.strip())
                        continue  # Continue to next command - treat as success
                
                if is_git_push:
                    # Check for push rejection (branches diverged)
                    push_rejection_indicators = [
                        "rejected",
                        "non-fast-forward",
                        "updates were rejected",
                        "failed to push",
                        "your branch is behind"
                    ]
                    
                    is_rejection = any(indicator in combined for indicator in push_rejection_indicators)
                    
                    if is_rejection:
                        # Extract branch name from command if possible
                        branch = cmd[-1] if len(cmd) > 3 else "your branch"
                        
                        logger.log("yellow", "")
                        logger.log("yellow", _("⚠️ Push rejected - your branch has diverged from remote!"))
                        logger.log("white", _(""))
                        logger.log("white", _("This happens when both you and someone else made changes."))
                        logger.log("white", _(""))
                        logger.log("cyan", _("To resolve this, you can:"))
                        logger.log("white", _(""))
                        logger.log("white", _("  Option 1 (RECOMMENDED): Pull with rebase"))
                        logger.log("dim", _("    git pull --rebase origin {0}").format(branch))
                        logger.log("dim", _("    git push origin {0}").format(branch))
                        logger.log("white", _(""))
                        logger.log("white", _("  Option 2: Pull with merge"))
                        logger.log("dim", _("    git pull origin {0}").format(branch))
                        logger.log("dim", _("    git push origin {0}").format(branch))
                        logger.log("white", _(""))
                        logger.log("yellow", _("  Option 3 (DANGEROUS): Force push (overwrites remote!)"))
                        logger.log("dim", _("    git push --force-with-lease origin {0}").format(branch))
                        logger.log("white", "")
                        
                        self.executed = True
                        self.success = False
                        return False

                # Real error - show details
                logger.log("red", _("✗ Command failed: {0}").format(' '.join(cmd)))

                # Show error details
                if e.stderr and e.stderr.strip():
                    logger.log("red", _("Error: {0}").format(e.stderr.strip()))
                elif e.stdout and e.stdout.strip():
                    logger.log("yellow", _("Output: {0}").format(e.stdout.strip()))
                else:
                    logger.log("red", _("Exit code: {0}").format(e.returncode))

                self.executed = True
                self.success = False
                return False

        self.executed = True
        self.success = True
        return True

    def get_command_preview(self):
        """Get readable command preview"""
        previews = []
        for cmd in self.commands:
            if isinstance(cmd, list):
                previews.append(' '.join(cmd))
            else:
                previews.append(str(cmd))
        return ' && '.join(previews)


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

    def add_operation(self, operation):
        """Add a pre-created Operation object"""
        self.operations.append(operation)

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
        if not self.show_preview or not self.operations:
            return True

        self.preview()

        # Ask for confirmation
        if self.has_destructive_operations():
            question = _("⚠️  Proceed with these operations? (includes destructive actions)")
        else:
            question = _("Proceed with these operations?")

        return self.menu.confirm(question)

    def execute(self, show_progress=True):
        """
        Execute all operations in sequence
        Returns True if all succeeded, False otherwise
        """
        if not self.operations:
            return True

        # DRY-RUN MODE: Just show what would be done
        if self.dry_run:
            self.logger.log("yellow", "")
            self.logger.log("yellow", "🔍 DRY-RUN MODE - Simulating operations:")
            self.logger.log("yellow", "")

            for i, op in enumerate(self.operations, 1):
                self.logger.log("cyan", f"[{i}/{len(self.operations)}] Would execute: {op.description}")
                if not op.callback and op.commands:
                    cmd_preview = op.get_command_preview()
                    self.logger.log("dim", f"   $ {cmd_preview}")

            self.logger.log("yellow", "")
            self.logger.log("green", "✓ Dry-run completed (no operations were executed)")
            self.logger.log("yellow", "")
            return True

        # NORMAL EXECUTION
        if show_progress:
            self.logger.log("cyan", _("Executing {0} operation(s)...").format(len(self.operations)))
            self.logger.log("cyan", "")

        for i, op in enumerate(self.operations, 1):
            if show_progress:
                self.logger.log("cyan", f"[{i}/{len(self.operations)}] {op.description}")

            result = op.execute(self.logger)

            # Handle special "conflict" status
            if result == "conflict":
                self.logger.log("yellow", _("⚠️ Conflicts detected - resolution needed."))
                return "conflict"  # Propagate conflict status
            
            if not result:
                self.logger.log("red", _("✗ Operation failed. Stopping execution."))
                return False

            if show_progress:
                self.logger.log("green", _("✓ Completed"))
                self.logger.log("cyan", "")

        return True

    def execute_with_confirmation(self, show_progress=True):
        """Show preview, confirm, then execute"""
        if not self.confirm():
            self.logger.log("yellow", _("Operation cancelled by user"))
            return False

        return self.execute(show_progress)

    def clear(self):
        """Clear all operations"""
        self.operations = []

    def is_empty(self):
        """Check if plan is empty"""
        return len(self.operations) == 0


class QuickPlan(OperationPlan):
    """
    Quick operation plan - no preview, direct execution
    Use for expert mode
    """

    def __init__(self, logger, menu_system):
        super().__init__(logger, menu_system, show_preview=False)

    def confirm(self):
        """Skip confirmation in quick mode"""
        return True

    def execute_with_confirmation(self, show_progress=False):
        """Execute without confirmation"""
        return self.execute(show_progress)
