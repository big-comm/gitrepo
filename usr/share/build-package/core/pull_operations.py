#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# core/pull_operations.py - Improved pull operations
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import subprocess
from .git_utils import GitUtils
from .operation_preview import OperationPlan, QuickPlan
from .translation_utils import _

def pull_latest_v2(build_package_instance):
    """
    Improved version of pull_latest with intelligent automation
    Uses settings, conflict resolver, and operation preview

    Args:
        build_package_instance: Instance of BuildPackage class

    Returns:
        bool: True if successful, False otherwise
    """
    bp = build_package_instance

    if not bp.is_git_repo:
        bp.logger.die("red", _("This operation is only available in git repositories."))
        return False

    # Get mode configuration
    mode_config = bp.settings.get_mode_config()
    operation_mode = bp.settings.get("operation_mode", "safe")

    # Create operation plan
    if operation_mode == "expert":
        plan = QuickPlan(bp.logger, bp.menu)
    else:
        dry_run = getattr(bp, 'dry_run_mode', False)
        plan = OperationPlan(bp.logger, bp.menu, show_preview=mode_config["show_preview"], dry_run=dry_run)

    # === PHASE 0: CHECK FOR EXISTING CONFLICTS ===
    # Must check BEFORE doing anything else - can't stash with conflicts
    if bp.conflict_resolver.has_conflicts():
        # Get list of conflicted files
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                capture_output=True,
                text=True,
                check=True
            )
            conflicted_files = result.stdout.strip().split('\n') if result.stdout.strip() else []
            conflict_count = len(conflicted_files)
        except:
            conflict_count = 0
            conflicted_files = []

        # Show detailed summary BEFORE opening resolver
        bp.logger.log("red", "")
        bp.logger.log("red", "═" * 70)
        bp.logger.log("red", _("⚠️  UNRESOLVED CONFLICTS DETECTED"))
        bp.logger.log("red", "═" * 70)
        bp.logger.log("yellow", _("You have unresolved conflicts from a previous operation!"))
        bp.logger.log("yellow", _("You must resolve these conflicts before pulling."))
        bp.logger.log("cyan", "")
        bp.logger.log("cyan", _("Conflicted files: {0}").format(conflict_count))

        if conflicted_files and len(conflicted_files) <= 5:
            for f in conflicted_files:
                bp.logger.log("yellow", f"  • {f}")
        elif len(conflicted_files) > 5:
            # Show first 5 files
            for f in conflicted_files[:5]:
                bp.logger.log("yellow", f"  • {f}")
            bp.logger.log("yellow", f"  ... and {len(conflicted_files) - 5} more files")

        bp.logger.log("cyan", "")
        bp.logger.log("cyan", _("Next: You'll be asked how to resolve each conflict"))
        bp.logger.log("red", "═" * 70)
        bp.logger.log("yellow", "")

        # CRITICAL: Wait for user to read the summary
        user_input = input(_("Press Enter to start resolving conflicts..."))

        # Clear screen before opening resolver to avoid confusion
        bp.logger.log("cyan", "")
        bp.logger.log("cyan", _("Opening conflict resolver..."))
        bp.logger.log("cyan", "")

        # Now open the resolver (will show its own interface)
        if not bp.conflict_resolver.resolve():
            bp.logger.log("red", _("✗ Failed to resolve conflicts"))
            bp.logger.log("yellow", "")
            input(_("Press Enter to return to main menu..."))
            return False

        bp.logger.log("green", _("✓ Conflicts resolved"))

        # After resolving conflicts, files are staged. We need to commit them
        # before continuing with pull operations to keep a clean state
        bp.logger.log("cyan", _("Committing resolved conflicts..."))

        try:
            # Get list of resolved files
            resolved_files_result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                capture_output=True,
                text=True,
                check=True
            )
            resolved_files = resolved_files_result.stdout.strip().split('\n') if resolved_files_result.stdout.strip() else []

            if resolved_files:
                # Create a simple commit message (avoid very long messages)
                file_count = len(resolved_files)
                commit_msg = f"Resolved {file_count} conflicted file(s) before pull"

                # Show which files were resolved
                bp.logger.log("dim", _("Resolved files:"))
                for f in resolved_files[:5]:  # Show first 5
                    bp.logger.log("dim", f"  • {f}")
                if file_count > 5:
                    bp.logger.log("dim", f"  ... and {file_count - 5} more")

                subprocess.run(
                    ["git", "commit", "-m", commit_msg],
                    check=True,
                    capture_output=True
                )
                bp.logger.log("green", _("✓ Resolved conflicts committed ({0} files)").format(file_count))
            else:
                # No staged changes, just reset the index
                subprocess.run(["git", "reset"], capture_output=True, check=False)
        except subprocess.CalledProcessError as e:
            bp.logger.log("red", _("✗ Failed to commit resolved conflicts"))
            if hasattr(e, 'stderr') and e.stderr:
                bp.logger.log("red", _("Error: {0}").format(e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr))
            bp.logger.log("yellow", "")
            input(_("Press Enter to return to main menu..."))
            return False

        bp.logger.log("cyan", _("Continuing with pull operations..."))

    # === PHASE 1: ANALYZE GIT STATE ===
    bp.logger.log("cyan", _("Analyzing repository state..."))

    current_branch = GitUtils.get_current_branch()
    username = bp.github_user_name or "unknown"
    expected_branch = f"dev-{username}"
    has_changes = GitUtils.has_changes()

    bp.logger.log("white", _("Current branch: {0}").format(bp.logger.format_branch_name(current_branch)))
    bp.logger.log("white", _("Your branch: {0}").format(bp.logger.format_branch_name(expected_branch)))
    bp.logger.log("white", _("Local changes: {0}").format("✓" if has_changes else "✗"))

    # === PHASE 2: ENSURE USER'S BRANCH ===
    if current_branch != expected_branch:
        if mode_config["auto_switch_branches"]:
            bp.logger.log("cyan", _("Auto-switching to your branch..."))

            if has_changes:
                plan.add(
                    _("Stash local changes"),
                    ["git", "stash", "push", "-u", "-m", f"auto-stash-pull-to-{expected_branch}"],
                    destructive=False
                )

            plan.add(
                _("Switch to your branch: {0}").format(expected_branch),
                ["git", "checkout", expected_branch],
                destructive=False
            )

            if has_changes:
                plan.add(
                    _("Restore local changes"),
                    ["git", "stash", "pop"],
                    destructive=False
                )
        else:
            # Ask user
            choice = bp.menu.show_menu(
                _("You're in {0}, but your branch is {1}").format(
                    bp.logger.format_branch_name(current_branch),
                    bp.logger.format_branch_name(expected_branch)
                ),
                [
                    _("Switch to my branch and pull there"),
                    _("Pull to current branch"),
                    _("Cancel")
                ]
            )

            if choice is None or choice[0] == 2:  # Cancel
                bp.logger.log("yellow", _("Operation cancelled"))
                return False

            if choice[0] == 0:  # Switch
                if has_changes:
                    subprocess.run(
                        ["git", "stash", "push", "-u", "-m", f"stash-before-pull"],
                        check=True,
                        capture_output=True
                    )

                subprocess.run(["git", "checkout", expected_branch], check=True)
                current_branch = expected_branch

                if has_changes:
                    pop_result = subprocess.run(
                        ["git", "stash", "pop"],
                        capture_output=True,
                        check=False
                    )

                    if pop_result.returncode != 0:
                        if bp.conflict_resolver.has_conflicts():
                            bp.logger.log("yellow", _("⚠️  Conflicts while restoring changes"))
                            if not bp.conflict_resolver.resolve():
                                return False

    # === PHASE 2.5: HANDLE LOCAL CHANGES ===
    # Check if we have uncommitted changes that would block the pull
    has_changes = GitUtils.has_changes()
    stash_needed = False

    if has_changes:
        # Ask user what to do with local changes
        bp.logger.log("yellow", "")
        bp.logger.log("yellow", "⚠️  " + _("You have uncommitted local changes!"))
        bp.logger.log("cyan", "")
        bp.logger.log("cyan", _("What do you want to do?"))
        bp.logger.log("green", _("  [1] Keep my changes and merge with remote (DEFAULT - Git standard behavior)"))
        bp.logger.log("cyan", _("      Your local edits will be preserved and merged with remote code"))
        bp.logger.log("red", _("  [2] ⚠️  DISCARD my changes and use only remote version"))
        bp.logger.log("red", _("      ⚠️  WARNING: You will LOSE all your uncommitted local changes!"))
        bp.logger.log("cyan", "")

        choice = input(_("Choose option [1/2] (press Enter for default=1): ")).strip()

        # Default to option 1 if user just presses Enter
        if not choice:
            choice = "1"

        if choice == "2":
            # User wants to discard local changes
            bp.logger.log("yellow", _("Discarding local changes and using remote version..."))
            subprocess.run(["git", "reset", "--hard", "HEAD"], check=True)
            subprocess.run(["git", "clean", "-fd"], check=True)
        else:
            # User wants to keep local changes (stash before pull)
            bp.logger.log("cyan", _("Preserving your changes..."))
            stash_needed = True

    # === PHASE 3: FETCH LATEST ===
    plan.add(
        "Fetch latest from remote",
        ["git", "fetch", "--all", "--prune"],
        destructive=False
    )

    # === PHASE 4: CHECK WHAT'S AVAILABLE ===
    # Determine most recent branch
    bp.logger.log("cyan", _("Finding most recent code..."))

    try:
        subprocess.run(["git", "fetch", "--all"], check=True, capture_output=True)
    except:
        pass

    most_recent_branch = bp.get_most_recent_branch()

    bp.logger.log("white", _("Most recent branch: {0}").format(
        bp.logger.format_branch_name(most_recent_branch)
    ))

    # === PHASE 5: DETERMINE PULL STRATEGY ===
    if most_recent_branch == current_branch:
        # Same branch, just pull
        bp.logger.log("cyan", _("Pull from remote {0}").format(current_branch))

        # Stash before pull if needed
        if stash_needed:
            plan.add(
                _("Stash local changes"),
                ["git", "stash", "push", "-u", "-m", "auto-stash-before-pull"],
                destructive=False
            )

        plan.add(
            "Pull from remote {0}".format(current_branch),
            ["git", "pull", "origin", current_branch, "--no-edit"],
            destructive=False
        )
    else:
        # Different branch - merge it
        bp.logger.log("cyan", _("Merging latest code from {0}").format(most_recent_branch))

        # Stash before merge if needed
        if stash_needed:
            plan.add(
                _("Stash local changes"),
                ["git", "stash", "push", "-u", "-m", "auto-stash-before-merge"],
                destructive=False
            )

        if mode_config["auto_merge"]:
            # Auto merge
            plan.add(
                _("Merge {0} into {1}").format(most_recent_branch, current_branch),
                ["git", "merge", f"origin/{most_recent_branch}", "--no-edit"],
                destructive=False
            )
        else:
            # Ask user
            if bp.menu.confirm(_("Merge {0} into your branch?").format(most_recent_branch)):
                plan.add(
                    _("Merge {0} into {1}").format(most_recent_branch, current_branch),
                    ["git", "merge", f"origin/{most_recent_branch}", "--no-edit"],
                    destructive=False
                )
            else:
                bp.logger.log("yellow", _("Skipping merge"))

    # === PHASE 6: EXECUTE PLAN ===
    if plan.is_empty():
        bp.logger.log("green", _("✓ Already up to date"))
        bp.logger.log("yellow", "")
        input(_("Press Enter to return to main menu..."))
        return True

    success = plan.execute_with_confirmation()

    if not success:
        bp.logger.log("red", _("✗ Pull operation failed"))
        bp.logger.log("yellow", "")
        input(_("Press Enter to return to main menu..."))
        return False

    # === PHASE 7: CHECK FOR CONFLICTS ===
    if bp.conflict_resolver.has_conflicts():
        # Use enhanced conflict resolver with branch information
        # This will show a detailed comparison and intelligent resolution
        if not bp.conflict_resolver.resolve(current_branch, most_recent_branch):
            bp.logger.log("red", _("✗ Failed to resolve conflicts"))
            bp.logger.log("yellow", "")
            input(_("Press Enter to return to main menu..."))
            return False

        bp.logger.log("green", _("✓ Conflicts resolved"))

    # === PHASE 7.5: RESTORE STASHED CHANGES ===
    if stash_needed:
        bp.logger.log("cyan", _("Restoring your local changes..."))

        pop_result = subprocess.run(
            ["git", "stash", "pop"],
            capture_output=True,
            text=True,
            check=False
        )

        if pop_result.returncode != 0:
            # Check if there are conflicts
            if bp.conflict_resolver.has_conflicts():
                # Show context about what happened
                bp.logger.log("yellow", "")
                bp.logger.log("yellow", "═" * 70)
                bp.logger.log("yellow", _("⚠️  CONFLICTS WHILE RESTORING YOUR CHANGES"))
                bp.logger.log("yellow", "═" * 70)
                bp.logger.log("cyan", _("Your local changes conflict with the pulled code"))
                bp.logger.log("cyan", "")
                bp.logger.log("cyan", _("The conflict resolver will help you merge:"))
                bp.logger.log("cyan", _("  • Your local changes (from stash)"))
                bp.logger.log("cyan", _("  • The newly pulled remote code"))
                bp.logger.log("yellow", "═" * 70)
                bp.logger.log("yellow", "")
                input(_("Press Enter to start resolving conflicts..."))

                # Use enhanced resolver - "current" is the pulled code, "incoming" is stashed changes
                # Note: After stash pop, "ours" is the pulled code, "theirs" is the stashed changes
                if not bp.conflict_resolver.resolve(current_branch, "stashed-changes"):
                    bp.logger.log("red", _("✗ Failed to resolve conflicts"))
                    bp.logger.log("yellow", _("Your changes are still in stash. Use 'git stash pop' manually."))
                    bp.logger.log("yellow", "")
                    input(_("Press Enter to return to main menu..."))
                    return False

                bp.logger.log("green", _("✓ Conflicts resolved, changes restored"))
            else:
                bp.logger.log("red", _("✗ Failed to restore stashed changes"))
                bp.logger.log("yellow", _("Your changes are still in stash. Use 'git stash pop' manually."))
                bp.logger.log("yellow", "")
                input(_("Press Enter to return to main menu..."))
                return False
        else:
            bp.logger.log("green", _("✓ Local changes restored successfully"))

    # === PHASE 8: SHOW SUMMARY ===
    bp.logger.log("green", "")
    bp.logger.log("green", "═" * 70)
    bp.logger.log("green", _("PULL COMPLETED SUCCESSFULLY"))
    bp.logger.log("green", "═" * 70)

    try:
        # Get current branch info
        current_branch = GitUtils.get_current_branch()
        bp.logger.log("cyan", _("Current branch: {0}").format(bp.logger.format_branch_name(current_branch)))

        # Get latest commit info
        result = subprocess.run(
            ["git", "log", "-1", "--pretty=format:%h - %s (%an, %ar)"],
            capture_output=True,
            text=True,
            check=True
        )
        latest_commit = result.stdout.strip()
        bp.logger.log("cyan", _("Latest commit: {0}").format(latest_commit))

        # Get number of commits if there were updates
        try:
            commits_result = subprocess.run(
                ["git", "log", "--oneline", "@{1}..HEAD"],
                capture_output=True,
                text=True,
                check=False
            )
            if commits_result.returncode == 0 and commits_result.stdout.strip():
                commit_count = len(commits_result.stdout.strip().split('\n'))
                bp.logger.log("cyan", _("New commits pulled: {0}").format(commit_count))
        except:
            pass

    except:
        bp.logger.log("green", _("✓ Pull completed"))

    bp.logger.log("green", "═" * 70)
    bp.logger.log("yellow", "")
    input(_("Press Enter to return to main menu..."))

    return True
