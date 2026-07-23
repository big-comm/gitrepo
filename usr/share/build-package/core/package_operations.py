#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# core/package_operations.py - Improved package generation operations
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import subprocess
from datetime import datetime

from .git_utils import GitUtils
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

    # Ensure GitHub token is available (required for triggering workflows)
    if not bp.github_api.ensure_github_token(bp.logger):
        bp.logger.log("red", _("✗ Cannot generate package without a GitHub token."))
        bp.logger.log("white", _("Please configure your token and try again."))
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
    if branch_type == "testing":
        # Testing uses the configured personal branch.
        working_branch = (
            bp.get_personal_branch()
            if hasattr(bp, "get_personal_branch")
            else f"dev-{bp.github_user_name or 'unknown'}"
        )
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


def _git_ref_exists(ref):
    """Return whether a local or remote Git ref exists."""
    return subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref],
        capture_output=True,
        check=False,
    ).returncode == 0


def _abort_merge():
    """Abort a merge without masking the original error."""
    subprocess.run(["git", "merge", "--abort"], capture_output=True, check=False)


def _merge_with_resolution(bp, incoming_branch, current_branch):
    """Merge one branch and leave no conflict state when cancelled."""
    result = subprocess.run(
        ["git", "merge", incoming_branch, "--no-edit"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True

    resolver = getattr(bp, "conflict_resolver", None)
    if not resolver or not resolver.has_conflicts():
        _abort_merge()
        bp.logger.log(
            "red",
            _("Merge failed: {0}").format(result.stderr.strip() or result.stdout.strip()),
        )
        return False

    if not resolver.resolve(current_branch, incoming_branch):
        _abort_merge()
        bp.logger.log("yellow", _("Merge cancelled. Repository restored."))
        return False

    if resolver.has_conflicts():
        _abort_merge()
        bp.logger.log("red", _("Unresolved conflicts remain. Merge aborted."))
        return False

    commit_result = subprocess.run(
        ["git", "commit", "--no-edit"],
        capture_output=True,
        text=True,
        check=False,
    )
    if commit_result.returncode != 0:
        _abort_merge()
        bp.logger.log(
            "red",
            _("Could not finish merge: {0}").format(
                commit_result.stderr.strip() or commit_result.stdout.strip()
            ),
        )
        return False

    return True


def _git_output(*args):
    """Return stripped output from a checked Git command."""
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _create_main_backup_if_needed(bp):
    """Preserve commits that exist only on the local main branch."""
    if not _git_ref_exists("main"):
        return None

    unique_commits = int(
        _git_output("rev-list", "--count", "main", "--not", "origin/main")
    )
    if unique_commits == 0:
        return None

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base_name = f"backup/main-before-stable-{timestamp}"
    backup_name = base_name
    suffix = 2
    while _git_ref_exists(backup_name):
        backup_name = f"{base_name}-{suffix}"
        suffix += 1

    subprocess.run(
        ["git", "branch", backup_name, "main"],
        capture_output=True,
        text=True,
        check=True,
    )
    bp.logger.log("yellow", _("Preserving your changes..."))
    bp.logger.log("yellow", _("✓ Created branch: {0}").format(backup_name))
    return backup_name


def _push_was_rejected(result):
    """Return whether a push failed because its remote ref moved."""
    output = f"{result.stdout}\n{result.stderr}".lower()
    return result.returncode != 0 and any(
        marker in output
        for marker in (
            "[rejected]",
            "fetch first",
            "non-fast-forward",
            "stale info",
        )
    )


def _raise_push_error(result):
    """Raise a checked-process error retaining Git's diagnostic output."""
    raise subprocess.CalledProcessError(
        result.returncode,
        result.args,
        output=result.stdout,
        stderr=result.stderr,
    )


def _sync_source_and_promote_main(bp, source_branch, attempts=3):
    """Sync source refs and promote source to remote main without force."""
    for attempt in range(1, attempts + 1):
        subprocess.run(
            ["git", "fetch", "origin", "--prune"],
            check=True,
            capture_output=True,
        )

        if _git_ref_exists(f"origin/{source_branch}"):
            bp.logger.log(
                "cyan",
                _("Updating {0} from its remote branch...").format(source_branch),
            )
            if not _merge_with_resolution(
                bp, f"origin/{source_branch}", source_branch
            ):
                return False

        bp.logger.log(
            "cyan",
            _("Updating {0} with the latest main...").format(source_branch),
        )
        if not _merge_with_resolution(bp, "origin/main", source_branch):
            return False

        promotion = subprocess.run(
            [
                "git",
                "push",
                "--atomic",
                "origin",
                f"{source_branch}:{source_branch}",
                f"{source_branch}:main",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if promotion.returncode == 0:
            return True
        if _push_was_rejected(promotion) and attempt < attempts:
            bp.logger.log("yellow", _("Fetching latest updates from remote..."))
            bp.logger.log("yellow", _("Retrying..."))
            continue
        _raise_push_error(promotion)

    return False


def _align_local_main():
    """Make local main match the successfully promoted remote main."""
    subprocess.run(
        ["git", "fetch", "origin", "main"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "branch", "-f", "main", "origin/main"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "branch", "--set-upstream-to=origin/main", "main"],
        check=True,
        capture_output=True,
    )


def _merge_to_main(bp, source_branch, mode_config):
    """Safely sync a development branch and promote it to remote main."""
    del mode_config  # Kept in the signature for API compatibility.

    original_branch = GitUtils.get_current_branch()
    if GitUtils.has_changes():
        bp.logger.log("red", _("Commit or stash local changes before building stable."))
        return False

    try:
        subprocess.run(["git", "fetch", "origin", "--prune"], check=True, capture_output=True)

        subprocess.run(["git", "checkout", source_branch], check=True, capture_output=True)

        _create_main_backup_if_needed(bp)
        if not _sync_source_and_promote_main(bp, source_branch):
            return False

        _align_local_main()
        return True

    except subprocess.CalledProcessError as e:
        _abort_merge()
        stderr = e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else e.stderr
        bp.logger.log("red", _("Error during merge: {0}").format((stderr or str(e)).strip()))
        return False
    finally:
        if original_branch and GitUtils.get_current_branch() != original_branch:
            if not GitUtils.has_changes():
                subprocess.run(
                    ["git", "checkout", original_branch],
                    capture_output=True,
                    check=False,
                )


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
