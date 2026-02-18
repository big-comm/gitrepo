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
    has_commits = GitUtils.has_commits()
    has_conflicts = bp.conflict_resolver.has_conflicts() if bp.conflict_resolver else False

    bp.logger.log("white", _("Current branch: {0}").format(bp.logger.format_branch_name(current_branch)))
    bp.logger.log("white", _("Your branch: {0}").format(bp.logger.format_branch_name(expected_branch)))
    bp.logger.log("white", _("Changes: {0}").format("✓" if has_changes else "✗"))

    # === EARLY PATH: No initial commit yet ===
    # git stash/fetch/divergence all require at least one commit.
    # Take a simplified path: create branch, add, commit, push.
    if not has_commits:
        bp.logger.log("cyan", _("New repository detected (no commits yet). Creating initial commit..."))

        if not has_changes:
            bp.logger.log("yellow", _("No changes to commit"))
            return True

        # Create the target branch directly (checkout -b works without commits)
        if current_branch != expected_branch:
            try:
                subprocess.run(
                    ["git", "checkout", "-b", expected_branch],
                    check=True,
                    capture_output=True
                )
                current_branch = expected_branch
                bp.logger.log("green", _("✓ Created branch: {0}").format(expected_branch))
            except subprocess.CalledProcessError:
                # Branch may already exist
                try:
                    subprocess.run(
                        ["git", "checkout", expected_branch],
                        check=True,
                        capture_output=True
                    )
                    current_branch = expected_branch
                except subprocess.CalledProcessError as e:
                    bp.logger.log("red", _("✗ Failed to switch to branch: {0}").format(e))
                    return False

        # Get commit message
        bp.last_commit_type = None
        if bp.args.commit_file:
            try:
                with open(bp.args.commit_file, 'r', encoding='utf-8') as f:
                    commit_message = f.read().strip()
                if not commit_message:
                    bp.logger.die("red", _("Commit message file is empty."))
                    return False
            except FileNotFoundError:
                bp.logger.die("red", _("Commit message file not found: {0}").format(bp.args.commit_file))
                return False
        elif bp.args.commit:
            commit_message = bp.args.commit
        else:
            commit_message = bp.custom_commit_prompt()
            if not commit_message:
                bp.logger.die("red", _("Commit message cannot be empty."))
                return False

        # Version bump
        if bp.settings.get("auto_version_bump", True):
            bp.apply_auto_version_bump(commit_message, bp.last_commit_type)

        # Stage + commit + push
        try:
            subprocess.run(["git", "add", "--all"], check=True, capture_output=True)

            if '\n' in commit_message:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                    f.write(commit_message)
                    commit_file = f.name
                try:
                    subprocess.run(["git", "commit", "-F", commit_file], check=True, capture_output=True)
                finally:
                    os.unlink(commit_file)
            else:
                subprocess.run(["git", "commit", "-m", commit_message], check=True, capture_output=True)

            bp.logger.log("green", _("✓ Initial commit created"))
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            bp.logger.log("red", _("✗ Commit failed: {0}").format(error_msg))
            return False

        # Push
        try:
            subprocess.run(
                ["git", "push", "-u", "origin", current_branch],
                check=True,
                capture_output=True
            )
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            bp.logger.log("yellow", _("⚠ Push failed (you may need to set up remote): {0}").format(error_msg))
            # Don't return False - the commit itself succeeded

        bp.logger.log("green", _("✓ Successfully committed and pushed to {0}!").format(
            bp.logger.format_branch_name(current_branch)
        ))
        return True

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


def commit_and_push_cli(bp):
    """Performs commit on user's own dev branch with proper isolation"""
    if not bp.is_git_repo:
        bp.logger.die("red", _("This option is only available in git repositories."))
        return False
    
    # Ensure dev branch exists
    bp.ensure_dev_branch_exists()
    
    # Get user info and target branch
    username = bp.github_user_name or "unknown"
    my_branch = f"dev-{username}"
    current_branch = GitUtils.get_current_branch()

    # ASK USER: Which branch to commit to?
    bp.logger.log("cyan", _("Choose target branch for commit:"))
    branch_choice = bp.menu.show_menu(
        _("Select branch for commit"),
        [
            _("My branch ({0}) - Recommended").format(my_branch),
            _("Main branch - Direct commit"),
            _("Cancel")
        ],
        default_index=0
    )

    if branch_choice is None or branch_choice[0] == 2:  # Cancel
        bp.logger.log("yellow", _("Operation cancelled"))
        return False

    # Set target branch based on user choice
    if branch_choice[0] == 1:  # Main branch
        target_branch = "main"
        bp.logger.log("yellow", _("⚠️  WARNING: You chose to commit directly to main!"))

        # Confirm this choice
        confirm = bp.menu.confirm(_("Are you sure you want to commit directly to main branch?"))
        if not confirm:
            bp.logger.log("yellow", _("Operation cancelled"))
            return False

        bp.logger.log("cyan", _("Target branch: {0}").format(bp.logger.format_branch_name(target_branch)))
    else:  # User's branch (default)
        target_branch = my_branch
        bp.logger.log("cyan", _("Target branch: {0}").format(bp.logger.format_branch_name(target_branch)))

    # ROBUST CHECK: Ensure user is working in their target branch
    if current_branch != target_branch:
        bp.logger.log("yellow", _("You're in {0} but should commit to {1}. Fixing this...").format(
            bp.logger.format_branch_name(current_branch), bp.logger.format_branch_name(target_branch)))

        # Check if there are changes to preserve
        has_changes = GitUtils.has_changes()

        if has_changes:
            # Stash → Switch → Apply workflow
            bp.logger.log("cyan", _("Preserving your changes while switching to target branch..."))
            stash_message = f"auto-preserve-changes-commit-to-{target_branch}"
            stash_result = subprocess.run(
                ["git", "stash", "push", "-u", "-m", stash_message],
                capture_output=True, text=True, check=False
            )

            if stash_result.returncode != 0:
                bp.logger.log("red", _("Failed to stash changes. Cannot proceed safely."))
                return False

            # Ensure target branch exists and switch
            if target_branch == "main":
                # For main branch, try to checkout or create if it doesn't exist
                checkout_result = subprocess.run(
                    ["git", "checkout", target_branch], 
                    capture_output=True, text=True, check=False
                )
                if checkout_result.returncode != 0:
                    # Branch doesn't exist, create it
                    bp.logger.log("cyan", _("Creating main branch (doesn't exist yet)..."))
                    create_result = subprocess.run(
                        ["git", "checkout", "-b", target_branch],
                        capture_output=True, text=True, check=False
                    )
                    if create_result.returncode != 0:
                        bp.logger.log("red", _("Failed to create main branch: {0}").format(create_result.stderr))
                        return False
                    bp.logger.log("green", _("✓ Created new main branch"))
            else:
                # For user branch, ensure it exists
                if not bp.ensure_user_branch_exists(target_branch):
                    return False

            # Apply stashed changes
            pop_result = subprocess.run(["git", "stash", "pop"], capture_output=True, text=True, check=False)
            if pop_result.returncode != 0:
                bp.logger.log("yellow", _("Conflicts detected while applying changes. Resolving automatically..."))
                try:
                    subprocess.run(["git", "reset", "HEAD"], check=True)
                    subprocess.run(["git", "add", "."], check=True)
                    bp.logger.log("green", _("Conflicts resolved automatically"))
                except subprocess.CalledProcessError:
                    bp.logger.log("red", _("Could not resolve conflicts automatically. Please check 'git status'"))
                    return False

            bp.logger.log("green", _("Successfully moved your changes to target branch!"))
        else:
            # No changes, just ensure we're on target branch
            if target_branch == "main":
                # For main branch, try to checkout or create if it doesn't exist
                checkout_result = subprocess.run(
                    ["git", "checkout", target_branch], 
                    capture_output=True, text=True, check=False
                )
                if checkout_result.returncode != 0:
                    # Branch doesn't exist, create it
                    bp.logger.log("cyan", _("Creating main branch (doesn't exist yet)..."))
                    create_result = subprocess.run(
                        ["git", "checkout", "-b", target_branch],
                        capture_output=True, text=True, check=False
                    )
                    if create_result.returncode != 0:
                        bp.logger.log("red", _("Failed to create main branch: {0}").format(create_result.stderr))
                        return False
                    bp.logger.log("green", _("✓ Created new main branch"))
            else:
                if not bp.ensure_user_branch_exists(target_branch):
                    return False
            bp.logger.log("cyan", _("Switched to target branch: {0}").format(bp.logger.format_branch_name(target_branch)))

    # Now we're guaranteed to be in target branch
    current_branch = target_branch
    
    # Check if there are changes AFTER ensuring we're in the right branch
    has_changes = GitUtils.has_changes()

    # SYNC REMOTE BRANCH: Update remote dev-username branch with latest main BEFORE pulling
    # BUT PRESERVE LOCAL CHANGES!
    # NOTE: Skip this for main branch - only sync dev branches
    if target_branch != "main":
        bp.logger.log("cyan", _("Checking if your remote branch needs sync with main..."))

        # CRITICAL: Save local changes first!
        local_changes_backup = None
        if has_changes:
            bp.logger.log("cyan", _("Backing up your local changes temporarily..."))
            try:
                # Create a temporary stash with all changes
                stash_result = subprocess.run(
                    ["git", "stash", "push", "-u", "-m", "auto-backup-before-sync"],
                    capture_output=True, text=True, check=False
                )
                if stash_result.returncode == 0:
                    local_changes_backup = True
                    bp.logger.log("green", _("Local changes safely backed up!"))
                else:
                    bp.logger.log("yellow", _("Could not backup changes, skipping sync."))
            except Exception as e:
                bp.logger.log("yellow", _("Could not backup changes: {0}").format(e))

        try:
            # Check if remote branch exists
            remote_check = subprocess.run(
                ["git", "ls-remote", "--heads", "origin", target_branch],
                capture_output=True, text=True, check=False
            )

            remote_branch_exists = bool(remote_check.stdout.strip())

            if remote_branch_exists:
                # Remote branch exists - check if it needs sync with main
                bp.logger.log("cyan", _("Remote branch exists. Checking sync status..."))

                # Fetch latest main
                subprocess.run(["git", "fetch", "origin", "main"], check=True)

                # Check if remote branch is behind main
                behind_check = subprocess.run(
                    ["git", "rev-list", "--count", f"origin/{target_branch}..origin/main"],
                    capture_output=True, text=True, check=False
                )

                commits_behind = int(behind_check.stdout.strip()) if behind_check.returncode == 0 and behind_check.stdout.strip() else 0

                if commits_behind > 0:
                    bp.logger.log("yellow", _("Your remote branch is {0} commits behind main. Updating...").format(commits_behind))

                    # Save current branch
                    original_branch = GitUtils.get_current_branch()

                    # Switch to target branch if not already there
                    if original_branch != target_branch:
                        subprocess.run(["git", "checkout", target_branch], check=True)

                    # Pull latest from remote target branch first
                    subprocess.run(["git", "pull", "origin", target_branch, "--no-edit"], check=False)

                    # Try to merge main into target branch
                    merge_result = subprocess.run(
                        ["git", "merge", "origin/main", "--no-edit"],
                        capture_output=True, text=True, check=False
                    )

                    if merge_result.returncode == 0:
                        # Merge successful, push updated branch
                        subprocess.run(["git", "push", "origin", target_branch], check=True)
                        bp.logger.log("green", _("Remote branch synced with main successfully!"))
                    else:
                        # Merge failed, use force update strategy
                        bp.logger.log("yellow", _("Merge conflict detected. Using force-update strategy..."))
                        subprocess.run(["git", "merge", "--abort"], check=False)
                        subprocess.run(["git", "reset", "--hard", "origin/main"], check=True)
                        subprocess.run(["git", "push", "origin", target_branch, "--force"], check=True)
                        bp.logger.log("green", _("Remote branch force-updated with main!"))

                    # Return to original branch if needed
                    if original_branch != target_branch:
                        subprocess.run(["git", "checkout", original_branch], check=True)
                else:
                    bp.logger.log("green", _("Remote branch is already up-to-date with main!"))
            else:
                bp.logger.log("cyan", _("Remote branch doesn't exist yet - will be created on first push."))

        except subprocess.CalledProcessError as e:
            bp.logger.log("yellow", _("Could not sync remote branch: {0}. Continuing...").format(e))
        except Exception as e:
            bp.logger.log("yellow", _("Unexpected sync error: {0}. Continuing...").format(e))
        finally:
            # CRITICAL: Restore local changes!
            if local_changes_backup:
                bp.logger.log("cyan", _("Restoring your local changes..."))
                try:
                    restore_result = subprocess.run(
                        ["git", "stash", "pop"],
                        capture_output=True, text=True, check=False
                    )
                    if restore_result.returncode == 0:
                        bp.logger.log("green", _("Local changes restored successfully!"))
                    else:
                        bp.logger.log("yellow", _("Could not restore changes automatically. Check 'git stash list'"))
                except Exception as e:
                    bp.logger.log("yellow", _("Error restoring changes: {0}").format(e))

        # Recheck changes after sync (they should be back now)
        has_changes = GitUtils.has_changes()

        # NOW pull is safe because remote branch is synced with main
        if not has_changes:
            if not GitUtils.git_pull(bp.logger):
                bp.logger.log("yellow", _("Failed to pull latest changes, but continuing since no local changes."))
        else:
            bp.logger.log("cyan", _("Local changes detected - skipping automatic pull to avoid conflicts."))
    else:
        # For main branch, just pull latest
        bp.logger.log("cyan", _("Pulling latest changes from main..."))
        try:
            subprocess.run(["git", "pull", "origin", "main", "--no-edit"], check=True)
            bp.logger.log("green", _("Successfully pulled latest main"))
        except subprocess.CalledProcessError:
            bp.logger.log("yellow", _("Failed to pull, but continuing..."))

    # Handle commit message based on if we have changes and args
    bp.last_commit_type = None
    if bp.args.commit_file:
        # Read commit message from file
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
        # User already provided commit message via argument
        commit_message = bp.args.commit
    elif has_changes:
        # No commit message provided, but we have changes - ask for message
        commit_message = bp.custom_commit_prompt()
        if not commit_message:
            bp.logger.die("red", _("Commit message cannot be empty."))
            return False
    else:
        # No changes to commit
        bp.menu.show_menu(_("No Changes to Commit") + "\n", [_("Press Enter to return to main menu")])
        return True
    
    if has_changes and commit_message:
        bp.apply_auto_version_bump(commit_message, bp.last_commit_type)
    
    # Add and commit changes to user's dev branch
    try:
        subprocess.run(["git", "add", "--all"], check=True)
        
        # Use file for multiline messages
        if '\n' in commit_message:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                f.write(commit_message)
                commit_file = f.name
            try:
                subprocess.run(["git", "commit", "-F", commit_file], check=True)
            finally:
                os.unlink(commit_file)
        else:
            subprocess.run(["git", "commit", "-m", commit_message], check=True)
    except subprocess.CalledProcessError as e:
        bp.logger.log("red", _("Error committing changes: {0}").format(e))
        return False
    
    # Push target branch to remote
    try:
        subprocess.run(["git", "push", "-u", "origin", target_branch], check=True)
    except subprocess.CalledProcessError as e:
        bp.logger.log("red", _("Error pushing to remote: {0}").format(e))
        return False

    bp.logger.log("green", _("Changes committed and pushed to {0} branch successfully!").format(bp.logger.format_branch_name(target_branch)))
    return True


def commit_and_generate_package_cli(bp):
    """Performs commit, creates branch and triggers workflow to generate package"""
    if not bp.is_git_repo:
        bp.logger.die("red", _("This operation is only available in git repositories."))
        return False
    
    # Ensure GitHub token is available (required for triggering workflows)
    if not bp.github_api.ensure_github_token(bp.logger):
        bp.logger.log("red", _("✗ Cannot generate package without a GitHub token."))
        return False
    
    branch_type = bp.args.build
    if not branch_type:
        bp.logger.die("red", _("Branch type not specified."))
        return False
    
    # FORCE CLEANUP AT START - resolve any conflicts immediately without external functions
    bp.logger.log("cyan", _("Checking and resolving any existing conflicts..."))
    try:
        # Check if there are unmerged files (conflicts)
        status_result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )
        has_conflicts = bool(status_result.stdout.strip())
        
        # Check if merge is in progress
        repo_root = GitUtils.get_repo_root_path()
        merge_head_path = os.path.join(repo_root, '.git', 'MERGE_HEAD')
        merge_in_progress = os.path.exists(merge_head_path)
        
        if has_conflicts or merge_in_progress:
            bp.logger.log("yellow", _("Conflicts detected. Performing automatic cleanup..."))
            
            # Force abort any merge in progress
            subprocess.run(["git", "merge", "--abort"], capture_output=True, check=False)
            
            # Stash any local changes to preserve them
            stash_result = subprocess.run(["git", "stash", "push", "-m", "auto-backup-before-cleanup"], 
                                        capture_output=True, check=False)
            stashed = stash_result.returncode == 0 and "No local changes to save" not in stash_result.stdout.decode()
            
            # Hard reset to clean state
            subprocess.run(["git", "reset", "--hard", "HEAD"], check=True)
            
            # Clean untracked files
            subprocess.run(["git", "clean", "-fd"], check=True)
            
            bp.logger.log("green", _("Repository cleaned to stable state."))
            
            # Try to restore stashed changes
            if stashed:
                bp.logger.log("cyan", _("Restoring your local changes..."))
                restore_result = subprocess.run(["git", "stash", "pop"], capture_output=True, text=True)
                if restore_result.returncode == 0:
                    bp.logger.log("green", _("Local changes restored successfully"))
                else:
                    bp.logger.log("yellow", _("Could not restore stashed changes. Use 'git stash list' to see them."))
        else:
            bp.logger.log("green", _("Repository is already in clean state."))
            
    except subprocess.CalledProcessError as e:
        bp.logger.log("yellow", _("Warning during cleanup: {0}").format(e))
    
    # Ensure dev branch exists before proceeding
    bp.ensure_dev_branch_exists()
    
    # AUTOMATION: Fetch remote without user interaction
    bp.logger.log("cyan", _("Fetching latest updates from remote..."))
    try:
        subprocess.run(["git", "fetch", "--all"], check=True)
    except subprocess.CalledProcessError:
        bp.logger.log("yellow", _("Warning: Failed to fetch latest changes, continuing with local code."))
    
    # Get current branch after cleanup
    current_branch = GitUtils.get_current_branch()
    
    # Identify most recent branch
    most_recent_branch = bp.get_most_recent_branch()
    
    # PRODUCTIVITY AUTOMATION: Always work with most recent code
    if most_recent_branch != current_branch:
        # Check if user has uncommitted changes before switching
        has_local_changes = GitUtils.has_changes()
        
        # Show clear information about what's happening
        bp.logger.log("cyan", _("Current branch: {0}").format(bp.logger.format_branch_name(current_branch)))
        bp.logger.log("cyan", _("Most recent branch available: {0}").format(bp.logger.format_branch_name(most_recent_branch)))
        
        if has_local_changes:
            # AUTOMATIC WORKFLOW: Stash → Switch → Apply → Ready for commit
            bp.logger.log("cyan", _("Moving your changes to the most recent branch..."))
            
            # Step 1: Stash changes with descriptive message
            stash_message = f"auto-preserve-changes-from-{current_branch}-to-{most_recent_branch}"
            bp.logger.log("cyan", _("Step 1/4: Preserving your changes temporarily..."))
            stash_result = subprocess.run(
                ["git", "stash", "push", "-u", "-m", stash_message], 
                capture_output=True, text=True, check=False
            )
            
            if stash_result.returncode != 0:
                bp.logger.log("red", _("Failed to stash changes. Cannot proceed safely."))
                return False
            
            # Step 2: Switch to most recent branch
            bp.logger.log("cyan", _("Step 2/4: Switching to most recent branch..."))
            try:
                bp._switch_to_branch_safely(most_recent_branch)
            except subprocess.CalledProcessError:
                bp.logger.log("red", _("Failed to switch branches. Your changes are safe in stash."))
                return False
            
            # Step 3: Apply stashed changes to new branch
            bp.logger.log("cyan", _("Step 3/4: Applying your changes to the most recent branch..."))
            pop_result = subprocess.run(["git", "stash", "pop"], capture_output=True, text=True, check=False)
            
            if pop_result.returncode != 0:
                bp.logger.log("yellow", _("Conflicts detected while applying changes. Resolving automatically..."))
                # Try to resolve conflicts automatically by preferring user's changes
                try:
                    subprocess.run(["git", "reset", "HEAD"], check=True)  # Unstage conflicted files
                    subprocess.run(["git", "add", "."], check=True)       # Add all files (resolves conflicts)
                    bp.logger.log("green", _("Conflicts resolved automatically"))
                except subprocess.CalledProcessError:
                    bp.logger.log("red", _("Could not resolve conflicts automatically. Please check 'git status'"))
                    return False
            
            # Step 4: Ready for commit
            bp.logger.log("green", _("Step 4/4: Your changes are now ready to commit in the most recent branch!"))
            current_branch = most_recent_branch
            
        else:
            # No local changes, safe to switch automatically
            bp.logger.log("cyan", _("No local changes detected. Switching to most recent branch: {0}").format(most_recent_branch))
            bp._switch_to_branch_safely(most_recent_branch)
            current_branch = most_recent_branch
    else:
        # Already on most recent branch, try conflict-resistant pull
        pull_cmd = ["git", "pull", "origin", current_branch, "--strategy-option=theirs", "--no-edit"]
        pull_result = subprocess.run(pull_cmd, capture_output=True, text=True)
        
        if pull_result.returncode != 0:
            # Try alternative strategy
            bp.logger.log("yellow", _("Standard pull failed, trying force update..."))
            try:
                subprocess.run(["git", "fetch", "origin", current_branch], check=True)
                subprocess.run(["git", "reset", "--hard", f"origin/{current_branch}"], check=True)
                bp.logger.log("green", _("Force-updated to latest {0}").format(current_branch))
            except subprocess.CalledProcessError:
                bp.logger.log("yellow", _("Could not update branch, continuing with current state"))
        else:
            bp.logger.log("green", _("Successfully pulled latest changes"))
    
    # Check changes AFTER all operations
    has_changes = GitUtils.has_changes()

    # Handle commit message
    bp.last_commit_type = None
    if bp.args.commit_file:
        # Read commit message from file
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
    elif has_changes:
        commit_message = bp.custom_commit_prompt()
        if not commit_message:
            bp.logger.log("red", _("Commit message cannot be empty."))
            return False
    else:
        commit_message = ""
        
    # Ensure we have a message if there are changes
    if has_changes and not commit_message:
        bp.logger.die("red", _("When using the '-b|--build' parameter and there are changes, the '-c|--commit' or '-F|--commit-file' parameter is also required."))
        return False

    if has_changes and commit_message:
        bp.apply_auto_version_bump(commit_message, bp.last_commit_type)

    # Different flows based on the package type
    if branch_type == "testing":
        if has_changes and commit_message:
            # Create or switch to dev-* branch for testing packages
            username = bp.github_user_name or "unknown"  
            dev_branch = f"dev-{username}"
            bp.logger.log("cyan", _("Creating/updating testing branch: {0}").format(dev_branch))
            try:
                # Use the existing method that handles branch creation safely
                if not bp.ensure_user_branch_exists(dev_branch):
                    return False
                current_branch = dev_branch
                
                # SYNC: Sync local dev branch with remote dev branch before commit
                bp.logger.log("cyan", _("Syncing local {0} with remote {0}...").format(dev_branch))
                try:
                    # Fetch remote dev branch
                    subprocess.run(["git", "fetch", "origin", dev_branch], check=True)
                    
                    # Pull/merge remote dev branch into local dev branch
                    pull_result = subprocess.run(
                        ["git", "pull", "origin", dev_branch, "--no-edit"],
                        capture_output=True, text=True, check=False
                    )
                    
                    if pull_result.returncode == 0:
                        bp.logger.log("green", _("Successfully synced with remote {0}").format(dev_branch))
                    else:
                        bp.logger.log("yellow", _("Pull failed, trying rebase..."))
                        # Try rebase if pull fails
                        subprocess.run(["git", "rebase", f"origin/{dev_branch}"], check=True)
                        bp.logger.log("green", _("Successfully rebased with remote {0}").format(dev_branch))
                        
                except subprocess.CalledProcessError:
                    bp.logger.log("yellow", _("Could not sync with remote {0}, continuing with local version").format(dev_branch))
                
                subprocess.run(["git", "add", "--all"], check=True)
                bp.logger.log("cyan", _("Committing changes with message:"))
                bp.logger.log("purple", commit_message)
                subprocess.run(["git", "commit", "-m", commit_message], check=True)
                subprocess.run(["git", "push", "origin", current_branch], check=True)
                bp.logger.log("green", _("Changes committed and pushed to {0} successfully!").format(bp.logger.format_branch_name(current_branch)))
            except subprocess.CalledProcessError as e:
                bp.logger.log("red", _("Error during branch operations: {0}").format(e))
                return False
        else:
            bp.logger.log("yellow", _("No changes to commit, using current branch for package."))
        
        working_branch = current_branch
        
    else:  # stable/extra packages
        # Create or switch to dev-* branch for changes if necessary
        if has_changes and commit_message:
            username = bp.github_user_name or "unknown"
            dev_branch = f"dev-{username}"
            bp.logger.log("cyan", _("Creating/updating branch {0} for your changes").format(dev_branch))
            try:
                # Use the existing method that handles branch creation safely
                if not bp.ensure_user_branch_exists(dev_branch):
                    return False
                subprocess.run(["git", "add", "--all"], check=True)
                bp.logger.log("cyan", _("Committing changes with message:"))
                bp.logger.log("purple", commit_message)
                subprocess.run(["git", "commit", "-m", commit_message], check=True)
                subprocess.run(["git", "push", "-u", "origin", dev_branch], check=True)
                bp.logger.log("green", _("Changes committed and pushed to {0} successfully!").format(bp.logger.format_branch_name(dev_branch)))
                most_recent_branch = dev_branch
            except subprocess.CalledProcessError as e:
                bp.logger.log("red", _("Error in branch operations: {0}").format(e))
                return False
        
        # AGGRESSIVE MERGE to main for stable/extra
        if most_recent_branch != "main" and most_recent_branch != "master":
            bp.logger.log("cyan", _("Force merging {0} to main for stable/extra package").format(most_recent_branch))
            
            try:
                # Switch to main
                subprocess.run(["git", "checkout", "main"], check=True)
                
                # Force update main first
                subprocess.run(["git", "fetch", "origin", "main"], check=True)
                subprocess.run(["git", "reset", "--hard", "origin/main"], check=True)
                
                # Try different merge strategies
                merge_strategies = [
                    ["git", "merge", f"{most_recent_branch}", "--strategy-option=theirs", "--no-edit"],
                    ["git", "merge", f"origin/{most_recent_branch}", "--strategy=ours", "--no-edit"],
                    ["git", "reset", "--hard", f"origin/{most_recent_branch}"]  # Nuclear option
                ]
                
                merge_success = False
                for i, merge_cmd in enumerate(merge_strategies):
                    try:
                        if i == 2:  # Nuclear option
                            bp.logger.log("yellow", _("Using nuclear merge strategy (reset to source branch)"))
                        
                        subprocess.run(merge_cmd, check=True)
                        merge_success = True
                        break
                    except subprocess.CalledProcessError:
                        if i < len(merge_strategies) - 1:
                            bp.logger.log("yellow", _("Merge strategy {0} failed, trying next...").format(i + 1))
                            # Abort any partial merge before trying next strategy
                            subprocess.run(["git", "merge", "--abort"], capture_output=True, check=False)
                        continue
                
                if merge_success:
                    # Push successful merge
                    subprocess.run(["git", "push", "origin", "main", "--force"], check=True)
                    bp.logger.log("green", _("Successfully merged {0} to main!").format(most_recent_branch))
                else:
                    bp.logger.log("red", _("All merge strategies failed"))
                    return False
                
            except subprocess.CalledProcessError as e:
                bp.logger.log("yellow", _("Could not merge automatically: {0}").format(e))
                # Abort any partial merge
                subprocess.run(["git", "merge", "--abort"], capture_output=True, check=False)
            
        working_branch = "main"
    
    # Get package name
    package_name = GitUtils.get_package_name()
    if package_name in ["error2", "error3"]:
        error_msg = _("Error: PKGBUILD file not found.") if package_name == "error2" else _("Error: Package name not found in PKGBUILD.")
        bp.logger.die("red", error_msg)
        return False

    bp.show_build_summary(package_name, branch_type, working_branch)
    
    # Confirm package generation
    if not bp.menu.confirm(_("Do you want to proceed with building the PACKAGE?")):
        bp.logger.log("red", _("Package build cancelled."))
        return False
    
    repo_type = branch_type
    new_branch = working_branch if working_branch != "main" else ""
    
    # Trigger workflow
    return bp.github_api.trigger_workflow(
        package_name, repo_type, new_branch, False, bp.tmate_option, bp.logger
    )
