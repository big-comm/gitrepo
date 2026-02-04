#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# core/package_operations.py - Improved package generation operations
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import subprocess
from .git_utils import GitUtils
from .operation_preview import OperationPlan, QuickPlan
from .translation_utils import _
from .commit_operations import commit_and_push_v2

def commit_and_generate_package_v2(build_package_instance, branch_type, commit_message=None, tmate_option=False):
    """
    Improved version of commit_and_generate_package
    Simplified logic using commit_operations_v2

    Args:
        build_package_instance: Instance of BuildPackage class
        branch_type: "testing", "stable", or "extra"
        commit_message: Optional commit message
        tmate_option: Enable TMATE debug session

    Returns:
        bool: True if successful, False otherwise
    """
    bp = build_package_instance

    if not bp.is_git_repo:
        bp.logger.die("red", _("This operation is only available in git repositories."))
        return False

    # Check dry-run mode
    if getattr(bp, 'dry_run_mode', False):
        bp.logger.log("yellow", "")
        bp.logger.log("yellow", _("🔍 DRY-RUN MODE - Package generation simulation:"))
        bp.logger.log("yellow", "")
        bp.logger.log("cyan", _("Would perform:"))
        bp.logger.log("cyan", _("  1. Commit changes (if any)"))
        bp.logger.log("cyan", _("  2. Merge to main (if {0} = stable/extra)").format(branch_type))
        bp.logger.log("cyan", _("  3. Trigger GitHub Actions workflow"))
        bp.logger.log("cyan", _("     - Package type: {0}").format(branch_type))
        bp.logger.log("cyan", _("     - TMATE: {0}").format(_('enabled') if tmate_option else _('disabled')))
        bp.logger.log("yellow", "")
        bp.logger.log("green", _("✓ Dry-run completed (no workflow triggered)"))
        return True

    # Get mode configuration
    mode_config = bp.settings.get_mode_config()
    operation_mode = bp.settings.get("operation_mode", "safe")
    
    # Detect if running in GUI mode (GTKMenuSystem doesn't have terminal menus)
    is_gui_mode = hasattr(bp.menu, '__class__') and 'GTK' in bp.menu.__class__.__name__
    
    # In GUI mode, force automatic behavior to avoid blocking menus
    if is_gui_mode:
        mode_config["auto_merge"] = True
        mode_config["confirm_destructive"] = False
        operation_mode = "expert"  # Skip all confirmations in GUI

    # === PHASE 1: HANDLE COMMIT ===
    has_changes = GitUtils.has_changes()

    if has_changes:
        if commit_message:
            bp.args.commit = commit_message

        bp.logger.log("cyan", _("═" * 60))
        bp.logger.log("cyan", _("STEP 1: Commit Changes"))
        bp.logger.log("cyan", _("═" * 60))

        # Use the improved commit function
        if not commit_and_push_v2(bp):
            bp.logger.log("red", _("✗ Commit failed, cannot proceed with package generation"))
            return False

        bp.logger.log("green", _("✓ Commit completed successfully"))
    else:
        bp.logger.log("cyan", _("No changes to commit, proceeding with package generation"))

    # === PHASE 2: DETERMINE WORKING BRANCH ===
    current_branch = GitUtils.get_current_branch()
    username = bp.github_user_name or "unknown"

    if branch_type == "testing":
        # Testing uses dev-username branch
        working_branch = f"dev-{username}"
    else:
        # Stable/Extra use main
        working_branch = "main"

        # Merge to main if needed
        if current_branch != "main":
            bp.logger.log("cyan", _("═" * 60))
            bp.logger.log("cyan", _("STEP 2: Merge to Main"))
            bp.logger.log("cyan", _("═" * 60))

            if mode_config["auto_merge"]:
                bp.logger.log("cyan", _("Auto-merging {0} to main...").format(current_branch))
            else:
                if not bp.menu.confirm(_("Merge {0} to main for {1} package?").format(current_branch, branch_type)):
                    bp.logger.log("yellow", _("Cancelled merge to main"))
                    return False

            # Perform merge
            success = _merge_to_main(bp, current_branch, mode_config)

            if not success:
                bp.logger.log("red", _("✗ Failed to merge to main"))
                return False

            bp.logger.log("green", _("✓ Successfully merged to main"))

    # === PHASE 3: GET PACKAGE NAME ===
    package_name = GitUtils.get_package_name()

    if package_name in ["error2", "error3"]:
        error_msg = _("Error: PKGBUILD file not found.") if package_name == "error2" else _("Error: Package name not found in PKGBUILD.")
        bp.logger.die("red", error_msg)
        return False

    # === PHASE 4: SHOW BUILD SUMMARY ===
    bp.logger.log("cyan", _("═" * 60))
    bp.logger.log("cyan", _("STEP 3: Package Build Summary"))
    bp.logger.log("cyan", _("═" * 60))

    _show_package_summary(bp, package_name, branch_type, working_branch, tmate_option)

    # === PHASE 5: CONFIRM BUILD ===
    if mode_config["confirm_destructive"] or operation_mode == "safe":
        if not bp.menu.confirm(_("🚀 Trigger package build on GitHub Actions?")):
            bp.logger.log("red", _("Package build cancelled"))
            return False

    # === PHASE 6: TRIGGER WORKFLOW ===
    bp.logger.log("cyan", _("═" * 60))
    bp.logger.log("cyan", _("STEP 4: Triggering GitHub Actions Workflow"))
    bp.logger.log("cyan", _("═" * 60))

    repo_type = branch_type
    new_branch = working_branch if working_branch != "main" else ""

    success = bp.github_api.trigger_workflow(
        package_name, repo_type, new_branch, False, tmate_option, bp.logger
    )

    if success:
        bp.logger.log("green", _("✓ Package build triggered successfully!"))
        bp.logger.log("cyan", _("Monitor build at: https://github.com/{0}/build-package/actions").format(bp.organization))
    else:
        bp.logger.log("red", _("✗ Failed to trigger package build"))

    return success


def _merge_to_main(bp, source_branch, mode_config):
    """Helper: Merge source branch to main"""
    try:
        # Fetch latest
        subprocess.run(["git", "fetch", "origin", "main"], check=True, capture_output=True)

        # Switch to main
        subprocess.run(["git", "checkout", "main"], check=True)

        # Update main
        subprocess.run(["git", "reset", "--hard", "origin/main"], check=True)

        # Try merge
        merge_result = subprocess.run(
            ["git", "merge", source_branch, "--no-edit"],
            capture_output=True,
            text=True,
            check=False
        )

        if merge_result.returncode != 0:
            # Merge failed, try with strategy
            bp.logger.log("yellow", _("Merge conflict, using automatic resolution..."))

            subprocess.run(["git", "merge", "--abort"], capture_output=True, check=False)

            merge_result = subprocess.run(
                ["git", "merge", source_branch, "--strategy-option=theirs", "--no-edit"],
                capture_output=True,
                check=False
            )

            if merge_result.returncode != 0:
                # Still failed, use reset
                bp.logger.log("yellow", _("Using force merge strategy..."))
                subprocess.run(["git", "reset", "--hard", source_branch], check=True)

        # Push to remote
        if mode_config["confirm_destructive"]:
            if not bp.menu.confirm(_("Push merged main to remote?")):
                return False

        subprocess.run(["git", "push", "origin", "main"], check=True)

        return True

    except subprocess.CalledProcessError as e:
        bp.logger.log("red", _("Error during merge: {0}").format(e))
        return False


def _show_package_summary(bp, package_name, branch_type, working_branch, tmate_option):
    """Helper: Show package build summary"""
    repo_name = GitUtils.get_repo_name()

    data = [
        (_("Organization"), bp.organization),
        (_("User Name"), bp.github_user_name),
        (_("Package Name"), package_name),
        (_("Repository Type"), branch_type),
        (_("Working Branch"), working_branch),
    ]

    if repo_name:
        data.append((_("Repository"), repo_name))

    data.append((_("TMATE Debug"), "✓" if tmate_option else "✗"))

    bp.logger.display_summary(_("📦 Package Build Configuration"), data)
