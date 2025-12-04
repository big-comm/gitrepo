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
        bp.logger.log("cyan", "Pull from remote {0}".format(current_branch))

        plan.add(
            "Pull from remote {0}".format(current_branch),
            ["git", "pull", "origin", current_branch, "--no-edit"],
            destructive=False
        )
    else:
        # Different branch - merge it
        bp.logger.log("cyan", _("Merging latest code from {0}").format(most_recent_branch))

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
        return True

    success = plan.execute_with_confirmation()

    if not success:
        return False

    # === PHASE 7: CHECK FOR CONFLICTS ===
    if bp.conflict_resolver.has_conflicts():
        bp.logger.log("yellow", _("⚠️  Conflicts detected after pull"))

        if not bp.conflict_resolver.resolve():
            bp.logger.log("red", _("✗ Failed to resolve conflicts"))
            return False

        bp.logger.log("green", _("✓ Conflicts resolved"))

    # === PHASE 8: SHOW SUMMARY ===
    try:
        # Get commit info
        result = subprocess.run(
            ["git", "log", "-1", "--oneline"],
            capture_output=True,
            text=True,
            check=True
        )

        latest_commit = result.stdout.strip()
        bp.logger.log("green", _("✓ Successfully updated to latest code"))
        bp.logger.log("dim", _("Latest commit: {0}").format(latest_commit))
    except:
        bp.logger.log("green", _("✓ Pull completed"))

    return True
