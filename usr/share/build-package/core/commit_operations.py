#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# core/commit_operations.py - Improved commit and push operations
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import subprocess
from .git_utils import GitUtils
from .operation_preview import OperationPlan, QuickPlan
from .translation_utils import _

def commit_and_push_v2(build_package_instance):
    """
    Improved version of commit_and_push with intelligent automation
    Uses settings, conflict resolver, and operation preview

    Args:
        build_package_instance: Instance of BuildPackage class

    Returns:
        bool: True if successful, False otherwise
    """
    bp = build_package_instance  # Shorthand

    if not bp.is_git_repo:
        bp.logger.die("red", _("This option is only available in git repositories."))
        return False

    # Get mode configuration
    mode_config = bp.settings.get_mode_config()
    operation_mode = bp.settings.get("operation_mode", "safe")

    # Create operation plan (Quick for expert, normal for others)
    if operation_mode == "expert":
        plan = QuickPlan(bp.logger, bp.menu)
    else:
        dry_run = getattr(bp, 'dry_run_mode', False)
        plan = OperationPlan(bp.logger, bp.menu, show_preview=mode_config["show_preview"], dry_run=dry_run)

    # === PHASE 1: ANALYZE GIT STATE ===
    bp.logger.log("cyan", _("Analyzing repository state..."))

    current_branch = GitUtils.get_current_branch()
    username = bp.github_user_name or "unknown"
    expected_branch = f"dev-{username}"
    has_changes = GitUtils.has_changes()
    has_conflicts = bp.conflict_resolver.has_conflicts() if bp.conflict_resolver else False

    bp.logger.log("white", _("Current branch: {0}").format(bp.logger.format_branch_name(current_branch)))
    bp.logger.log("white", _("Your branch: {0}").format(bp.logger.format_branch_name(expected_branch)))
    bp.logger.log("white", _("Changes: {0}").format("✓" if has_changes else "✗"))

    # === PHASE 2: HANDLE CONFLICTS FIRST ===
    if has_conflicts:
        bp.logger.log("yellow", _("⚠️  Conflicts detected!"))

        if mode_config["auto_resolve_conflicts"]:
            bp.logger.log("cyan", _("Auto-resolving conflicts ({0} mode)...").format(operation_mode))
            if not bp.conflict_resolver.resolve():
                bp.logger.log("red", _("Failed to resolve conflicts. Please fix manually."))
                return False
        else:
            bp.logger.log("yellow", _("Conflict resolution required."))
            if not bp.conflict_resolver.resolve():
                return False

    # === PHASE 3: ENSURE CORRECT BRANCH ===
    if current_branch != expected_branch:
        if mode_config["auto_switch_branches"]:
            # Automatic switch
            bp.logger.log("cyan", _("Auto-switching to your branch..."))

            if has_changes:
                plan.add(
                    _("Stash changes before switching"),
                    ["git", "stash", "push", "-u", "-m", f"auto-stash-switch-to-{expected_branch}"],
                    destructive=False
                )

            plan.add(
                _("Switch to your branch: {0}").format(expected_branch),
                ["git", "checkout", expected_branch],
                destructive=False,
                callback=lambda: _ensure_branch_exists(bp, expected_branch)
            )

            if has_changes:
                # Add custom callback to restore stash and check for conflicts
                def restore_stash_safe():
                    result = subprocess.run(
                        ["git", "stash", "pop"],
                        capture_output=True,
                        text=True,
                        check=False
                    )

                    if result.returncode != 0:
                        # Check for conflicts
                        if bp.conflict_resolver and bp.conflict_resolver.has_conflicts():
                            bp.logger.log("yellow", _("⚠️  Conflicts while restoring changes"))
                            if not bp.conflict_resolver.resolve():
                                raise Exception(_("Failed to resolve conflicts"))
                        else:
                            raise Exception(_("Failed to restore stashed changes"))

                plan.add(
                    _("Restore stashed changes"),
                    [],  # Empty command, using callback
                    destructive=False,
                    callback=restore_stash_safe
                )
        else:
            # Ask user
            choice = bp.menu.show_menu(
                _("You're in {0}, but should commit to {1}").format(
                    bp.logger.format_branch_name(current_branch),
                    bp.logger.format_branch_name(expected_branch)
                ),
                [
                    _("Switch to my branch ({0})").format(expected_branch),
                    _("Continue in current branch ({0})").format(current_branch),
                    _("Cancel")
                ]
            )

            if choice is None or choice[0] == 2:  # Cancel
                bp.logger.log("yellow", _("Operation cancelled"))
                return False

            if choice[0] == 0:  # Switch
                # Stash changes before switching
                if has_changes:
                    bp.logger.log("cyan", _("Stashing changes before switching branches..."))
                    try:
                        subprocess.run(
                            ["git", "stash", "push", "-u", "-m", f"auto-stash-switch-to-{expected_branch}"],
                            check=True,
                            capture_output=True
                        )
                    except subprocess.CalledProcessError as e:
                        bp.logger.log("red", _("Failed to stash changes: {0}").format(e))
                        return False

                # Now switch
                _ensure_branch_exists(bp, expected_branch)

                try:
                    subprocess.run(["git", "checkout", expected_branch], check=True)
                except subprocess.CalledProcessError as e:
                    bp.logger.log("red", _("Failed to switch branches: {0}").format(e))
                    # Try to restore stash
                    if has_changes:
                        subprocess.run(["git", "stash", "pop"], capture_output=True, check=False)
                    return False

                # Restore stashed changes
                if has_changes:
                    bp.logger.log("cyan", _("Restoring stashed changes..."))
                    pop_result = subprocess.run(
                        ["git", "stash", "pop"],
                        capture_output=True,
                        text=True,
                        check=False
                    )

                    if pop_result.returncode != 0:
                        # Stash pop failed - likely conflicts
                        bp.logger.log("yellow", _("⚠️  Conflicts detected while restoring changes"))

                        # Check if there are actual conflicts
                        if bp.conflict_resolver and bp.conflict_resolver.has_conflicts():
                            bp.logger.log("cyan", _("Attempting to resolve conflicts..."))

                            if not bp.conflict_resolver.resolve():
                                bp.logger.log("red", _("✗ Could not resolve conflicts automatically"))
                                bp.logger.log("yellow", _("Please resolve conflicts manually and run again"))
                                return False
                        else:
                            bp.logger.log("yellow", _("Could not restore changes. Check 'git stash list'"))
                            return False
                    else:
                        bp.logger.log("green", _("✓ Changes restored successfully"))

                current_branch = expected_branch
            # else: continue in current branch

    # === PHASE 4: FETCH LATEST (info only, don't pull yet) ===
    commits_behind = 0
    should_pull = False

    if bp.settings.get("auto_fetch", True):
        plan.add(
            _("Fetch latest from remote"),
            ["git", "fetch", "origin"],
            destructive=False
        )

    # Check if behind (but DON'T pull yet - we need to commit first!)
    try:
        subprocess.run(["git", "fetch", "origin"], check=True, capture_output=True)
        behind_result = subprocess.run(
            ["git", "rev-list", "--count", f"HEAD..origin/{current_branch}"],
            capture_output=True,
            text=True,
            check=False
        )

        if behind_result.returncode == 0 and behind_result.stdout.strip():
            commits_behind = int(behind_result.stdout.strip())
            if commits_behind > 0:
                bp.logger.log("yellow", _("Your branch is {0} commits behind remote").format(commits_behind))

                # Ask user if they want to pull AFTER committing
                if mode_config["auto_pull"] or bp.settings.get("auto_pull", False):
                    should_pull = True
                else:
                    should_pull = bp.menu.confirm(_("Pull latest changes after committing?"))
    except Exception:
        pass  # Ignore fetch errors

    # === PHASE 5: CHECK FOR CHANGES ===
    has_changes = GitUtils.has_changes()  # Recheck after pull

    if not has_changes:
        bp.logger.log("yellow", _("No changes to commit"))
        return True

    # === PHASE 6: GET COMMIT MESSAGE ===
    bp.last_commit_type = None

    if bp.args.commit:
        commit_message = bp.args.commit
    else:
        commit_message = bp.custom_commit_prompt()
        if not commit_message:
            bp.logger.die("red", _("Commit message cannot be empty."))
            return False

    # === PHASE 7: VERSION BUMP ===
    if bp.settings.get("auto_version_bump", True):
        bp.apply_auto_version_bump(commit_message, bp.last_commit_type)

    # === PHASE 7.5: FINAL CONFLICT CHECK ===
    # Critical: ensure no conflicts before committing
    if bp.conflict_resolver and bp.conflict_resolver.has_conflicts():
        bp.logger.log("red", _("✗ Unresolved conflicts detected!"))
        bp.logger.log("yellow", _("Cannot commit with conflict markers in files"))

        if not bp.conflict_resolver.resolve():
            bp.logger.log("red", _("✗ Failed to resolve conflicts"))
            bp.logger.log("yellow", _("Please resolve manually:"))
            bp.logger.log("white", _("1. Edit conflicted files"))
            bp.logger.log("white", _("2. Remove <<<<<<, =======, >>>>>>> markers"))
            bp.logger.log("white", _("3. Run 'git add <file>'"))
            bp.logger.log("white", _("4. Run this command again"))
            return False

        bp.logger.log("green", _("✓ Conflicts resolved, continuing..."))

    # === PHASE 8: COMMIT AND PUSH ===
    plan.add(
        _("Stage all changes"),
        ["git", "add", "--all"],
        destructive=False
    )

    plan.add(
        _("Commit: {0}").format(commit_message[:50] + "..." if len(commit_message) > 50 else commit_message),
        ["git", "commit", "-m", commit_message],
        destructive=False
    )

    # === PHASE 8.5: PULL AFTER COMMIT (if needed) ===
    # Now that local changes are committed, safe to pull remote changes
    if should_pull and commits_behind > 0:
        plan.add(
            _("Pull {0} commits from remote").format(commits_behind),
            ["git", "pull", "origin", current_branch, "--rebase", "--no-edit"],
            destructive=False
        )

    # === PHASE 9: PUSH ===
    plan.add(
        "Push to {0}".format(current_branch),
        ["git", "push", "-u", "origin", current_branch],
        destructive=False
    )

    # === PHASE 10: EXECUTE PLAN ===
    if not plan.execute_with_confirmation():
        return False

    bp.logger.log("green", _("✓ Successfully committed and pushed to {0}!").format(
        bp.logger.format_branch_name(current_branch)
    ))

    return True


def _ensure_branch_exists(bp, branch_name):
    """Helper: Ensure branch exists locally and remotely"""
    try:
        # Check if exists locally
        local_check = subprocess.run(
            ["git", "rev-parse", "--verify", branch_name],
            capture_output=True,
            check=False
        )

        # Check if exists remotely
        remote_check = subprocess.run(
            ["git", "rev-parse", "--verify", f"origin/{branch_name}"],
            capture_output=True,
            check=False
        )

        if remote_check.returncode == 0:
            # Exists remotely, checkout
            subprocess.run(["git", "checkout", branch_name], check=True)
        elif local_check.returncode == 0:
            # Exists locally only
            subprocess.run(["git", "checkout", branch_name], check=True)
        else:
            # Doesn't exist, create
            bp.logger.log("cyan", _("Creating new branch: {0}").format(branch_name))
            subprocess.run(["git", "checkout", "-b", branch_name], check=True)

        return True

    except subprocess.CalledProcessError as e:
        bp.logger.log("red", _("Error ensuring branch exists: {0}").format(e))
        return False
