#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# core/commit_operations.py - Improved commit and push operations
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import subprocess
import os
import tempfile
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
    
    # Detect if running in GUI mode (GTKMenuSystem doesn't have terminal menus)
    is_gui_mode = hasattr(bp.menu, '__class__') and 'GTK' in bp.menu.__class__.__name__
    
    # In GUI mode, force automatic behavior to avoid blocking menus
    if is_gui_mode:
        mode_config["auto_switch_branches"] = True
        mode_config["auto_pull"] = True
        mode_config["show_preview"] = False  # Don't show CLI preview

    # Create operation plan (Quick for expert/GUI, normal for others)
    if operation_mode == "expert" or is_gui_mode:
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

    # === PHASE 4: FETCH LATEST (info only) ===
    # Fetch to update remote refs, actual sync handled in PHASE 8.5

    if bp.settings.get("auto_fetch", True):
        plan.add(
            _("Fetch latest from remote"),
            ["git", "fetch", "origin"],
            destructive=False
        )

    # === PHASE 4.5: EXECUTE BRANCH SWITCH OPERATIONS ===
    # Critical: Must execute plan now to switch branch BEFORE committing
    if not plan.is_empty():
        bp.logger.log("cyan", _("Executing branch preparation operations..."))
        if not plan.execute(show_progress=True):
            bp.logger.log("red", _("✗ Failed to prepare branch"))
            return False
        plan.clear()  # Clear executed operations
        
        # Update current_branch to reflect actual branch after switch
        current_branch = GitUtils.get_current_branch()
        bp.logger.log("dim", _("Now on branch: {0}").format(current_branch))

    # Quick fetch to check status (divergence check in PHASE 8.5 will handle sync)
    try:
        subprocess.run(["git", "fetch", "origin"], check=True, capture_output=True)
    except Exception:
        pass  # Ignore fetch errors

    # === PHASE 5: CHECK FOR CHANGES ===
    has_changes = GitUtils.has_changes()  # Recheck after pull

    if not has_changes:
        bp.logger.log("yellow", _("No changes to commit"))
        return True

    # === PHASE 6: GET COMMIT MESSAGE ===
    bp.last_commit_type = None

    if bp.args.commit_file:
        # Read message from file
        try:
            with open(bp.args.commit_file, 'r', encoding='utf-8') as f:
                commit_message = f.read().strip()
            if not commit_message:
                bp.logger.die("red", _("Commit message file is empty."))
                return False
            bp.logger.log("cyan", _("Using commit message from file: {0}").format(bp.args.commit_file))
        except FileNotFoundError:
            bp.logger.die("red", _("Commit message file not found: {0}").format(bp.args.commit_file))
            return False
        except Exception as e:
            bp.logger.die("red", _("Error reading commit message file: {0}").format(e))
            return False
    elif bp.args.commit:
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

    # === PHASE 8: COMMIT LOCAL CHANGES FIRST ===
    # Critical: Must commit BEFORE trying to pull/sync with remote
    bp.logger.log("cyan", _("Staging and committing changes..."))
    
    try:
        # Stage all changes
        subprocess.run(["git", "add", "--all"], check=True, capture_output=True)
        
        # Commit - use file for multiline messages
        if '\n' in commit_message:
            # Use temporary file for multiline message
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                f.write(commit_message)
                commit_file = f.name
            try:
                subprocess.run(
                    ["git", "commit", "-F", commit_file],
                    check=True,
                    capture_output=True
                )
            finally:
                os.unlink(commit_file)
        else:
            # Single line message
            subprocess.run(
                ["git", "commit", "-m", commit_message],
                check=True,
                capture_output=True
            )
        bp.logger.log("green", _("✓ Changes committed locally"))
        
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        bp.logger.log("red", _("✗ Commit failed: {0}").format(error_msg))
        return False

    # === PHASE 8.5: CHECK DIVERGENCE AND SYNC ===
    # Now that changes are committed, safe to check divergence and sync
    divergence = GitUtils.check_branch_divergence(current_branch)
    
    if divergence['diverged']:
        # Branches have diverged - need user decision
        bp.logger.log("yellow", "")
        bp.logger.log("yellow", _("⚠️ Your branch has diverged from remote!"))
        bp.logger.log("white", _("   Local: {0} commit(s) ahead").format(divergence['ahead']))
        bp.logger.log("white", _("   Remote: {0} commit(s) behind").format(divergence['behind']))
        
        # Show commit details
        if divergence['local_commits']:
            bp.logger.log("cyan", "\n" + _("   Your local commits:"))
            for sha, msg in divergence['local_commits'][:3]:  # Show max 3
                bp.logger.log("white", f"     • {sha[:7]} {msg}")
            if len(divergence['local_commits']) > 3:
                bp.logger.log("dim", _("     ... and {0} more").format(
                    len(divergence['local_commits']) - 3
                ))
        
        if divergence['remote_commits']:
            bp.logger.log("cyan", "\n" + _("   Remote commits (not in local):"))
            for sha, msg in divergence['remote_commits'][:3]:  # Show max 3
                bp.logger.log("white", f"     • {sha[:7]} {msg}")
            if len(divergence['remote_commits']) > 3:
                bp.logger.log("dim", _("     ... and {0} more").format(
                    len(divergence['remote_commits']) - 3
                ))
        
        bp.logger.log("white", "")
        
        # Show resolution menu
        choice = bp.menu.show_menu(
            _("How do you want to resolve this divergence?"),
            [
                _("📥 Pull with rebase (RECOMMENDED - clean history)"),
                _("🔀 Pull with merge (keeps both histories)"),
                _("⚠️ Force push (DANGEROUS - overwrites remote!)"),
                _("❌ Cancel and resolve manually")
            ]
        )
        
        if choice is None or choice[0] == 3:  # Cancel
            bp.logger.log("yellow", _("Operation cancelled"))
            bp.logger.log("white", _("Your commit is saved locally. To complete:"))
            bp.logger.log("white", _("  1. git pull --rebase origin {0}").format(current_branch))
            bp.logger.log("white", _("  2. Resolve any conflicts"))
            bp.logger.log("white", _("  3. git push origin {0}").format(current_branch))
            return False
        
        resolution_method = ['rebase', 'merge', 'force_push'][choice[0]]
        
        # Resolve the divergence
        if not GitUtils.resolve_divergence(current_branch, resolution_method, bp.logger, bp.menu):
            bp.logger.log("red", _("✗ Failed to resolve divergence"))
            bp.logger.log("yellow", _("Your commit is saved locally. Please resolve manually."))
            return False
        
        # After rebase/merge, push
        if resolution_method != 'force_push':
            try:
                subprocess.run(
                    ["git", "push", "-u", "origin", current_branch],
                    check=True,
                    capture_output=True
                )
            except subprocess.CalledProcessError as e:
                error_msg = e.stderr.decode() if e.stderr else str(e)
                bp.logger.log("red", _("✗ Push failed: {0}").format(error_msg))
                return False
    
    elif divergence['behind'] > 0:
        # Only behind (not diverged) - sync then push
        bp.logger.log("cyan", _("Your branch is {0} commit(s) behind remote").format(
            divergence['behind']
        ))
        
        if mode_config.get("auto_pull", False) or is_gui_mode:
            # Auto pull with rebase
            if not GitUtils.resolve_divergence(current_branch, 'rebase', bp.logger, bp.menu):
                bp.logger.log("yellow", _("Pull failed, trying merge..."))
                if not GitUtils.resolve_divergence(current_branch, 'merge', bp.logger, bp.menu):
                    bp.logger.log("red", _("✗ Could not sync with remote"))
                    return False
        else:
            # Ask user
            if bp.menu.confirm(_("Pull {0} commit(s) from remote before pushing?").format(
                divergence['behind']
            )):
                if not GitUtils.resolve_divergence(current_branch, 'rebase', bp.logger, bp.menu):
                    bp.logger.log("red", _("✗ Pull failed"))
                    return False
        
        # Push after sync
        try:
            subprocess.run(
                ["git", "push", "-u", "origin", current_branch],
                check=True,
                capture_output=True
            )
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            bp.logger.log("red", _("✗ Push failed: {0}").format(error_msg))
            return False
    
    else:
        # Not diverged, not behind - normal push
        try:
            subprocess.run(
                ["git", "push", "-u", "origin", current_branch],
                check=True,
                capture_output=True
            )
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            bp.logger.log("red", _("✗ Push failed: {0}").format(error_msg))
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

        if remote_check.returncode == 0 and local_check.returncode != 0:
            # Exists remotely but NOT locally - create local branch tracking remote
            bp.logger.log("cyan", _("Creating local branch from remote: {0}").format(branch_name))
            subprocess.run(
                ["git", "checkout", "-b", branch_name, f"origin/{branch_name}"],
                check=True
            )
        elif remote_check.returncode == 0:
            # Exists both locally and remotely - just checkout
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
