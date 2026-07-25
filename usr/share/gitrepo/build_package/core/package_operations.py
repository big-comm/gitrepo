#
# core/package_operations.py - Improved package generation operations
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

from gitrepo.common import child_process as subprocess
from .git_utils import GitUtils
from gitrepo.common.translation import _
from .commit_operations import commit_and_push
from .repository_lock import journey


def _commit_pending_changes(bp, commit_message: str | None) -> bool:
    if not GitUtils.has_changes():
        return True
    if commit_message:
        bp.args.commit = commit_message
    return commit_and_push(bp)


def _prepare_working_branch(bp, branch_type: str) -> str:
    current = GitUtils.get_current_branch()
    if branch_type == "testing":
        return f"dev-{bp.github_user_name or 'unknown'}"
    if current != "main" and not _merge_to_main(bp, current):
        return ""
    return "main"


def _package_name(bp) -> str:
    package_name = GitUtils.get_package_name()
    if not package_name:
        bp.logger.log("red", _("Could not read a package name with makepkg --printsrcinfo."))
        return ""
    return package_name


def _trigger_package_workflow(bp, package_name, branch_type, working_branch, tmate_option):
    new_branch = working_branch if working_branch != "main" else ""
    return bp.github_api.trigger_workflow(
        package_name,
        branch_type,
        new_branch,
        False,
        tmate_option,
        bp.logger,
    )


@journey("generating a package", False)
def commit_and_generate_package(build_package_instance, branch_type, commit_message=None, tmate_option=False):
    """Commit pending work, prepare the target branch, and trigger one reviewed build."""
    bp = build_package_instance
    if not bp.is_git_repo:
        bp.logger.log("red", _("This operation is only available in Git repositories."))
        return False
    if not bp.github_api.ensure_github_token(bp.logger):
        bp.logger.log("red", _("Configure a GitHub token before generating a package."))
        return False
    if not _commit_pending_changes(bp, commit_message):
        return False

    working_branch = _prepare_working_branch(bp, branch_type)
    package_name = _package_name(bp)
    if not working_branch or not package_name:
        return False
    _show_package_summary(bp, package_name, branch_type, working_branch, tmate_option)
    if getattr(bp, "dry_run_mode", False):
        bp.logger.log("green", _("Dry run completed; no workflow was triggered."))
        return True

    question = _("Trigger this GitHub Actions package build?\nPackage: {0}\nType: {1}\nBranch: {2}").format(
        package_name, branch_type, working_branch
    )
    if not bp.menu.confirm(question, default_yes=False):
        bp.logger.log("yellow", _("Package build cancelled."))
        return False
    success = _trigger_package_workflow(bp, package_name, branch_type, working_branch, tmate_option)
    bp.logger.log("green" if success else "red", _("Package workflow started.") if success else _("Workflow failed."))
    return success


def _merge_without_conflicts(bp, incoming_ref: str) -> bool:
    """Merge one ref, leaving no conflict state behind when it fails."""
    result = subprocess.run_git(
        ["git", "merge", incoming_ref, "--no-edit"], capture_output=True, text=True, check=False, intent="ordinary"
    )
    if result.returncode == 0:
        return True
    subprocess.run_git(["git", "merge", "--abort"], capture_output=True, check=False, intent="ordinary")
    bp.logger.log(
        "red",
        _("Merging {0} stopped because it requires conflict resolution. No history was rewritten.").format(
            incoming_ref
        ),
    )
    return False


def _merge_to_main(bp, source_branch):
    """Sync the working branch, then fast-forward main onto it."""
    if GitUtils.has_changes():
        bp.logger.log("red", _("Commit or stash local changes before building a stable package."))
        return False

    question = _(
        "Publish {0} through main?\n"
        "git fetch origin --prune\n"
        "git merge origin/{0} --no-edit\n"
        "git merge origin/main --no-edit\n"
        "git push origin {0}\n"
        "git checkout main\n"
        "git merge --ff-only origin/main\n"
        "git merge {0} --no-edit\n"
        "git push origin main"
    ).format(source_branch)
    if not bp.menu.confirm(question, default_yes=False):
        return False

    original_branch = GitUtils.get_current_branch()
    try:
        subprocess.run_git(["git", "fetch", "origin", "--prune"], check=True, capture_output=True, intent="ordinary")

        # The working branch is published first, so main only ever receives
        # commits that already exist on its own remote branch.
        if GitUtils.ref_exists(f"origin/{source_branch}") and not _merge_without_conflicts(
            bp, f"origin/{source_branch}"
        ):
            return False
        if not _merge_without_conflicts(bp, "origin/main"):
            return False
        subprocess.run_git(["git", "push", "origin", f"refs/heads/{source_branch}"], check=True, intent="ordinary")

        subprocess.run_git(["git", "checkout", "main"], check=True, intent="ordinary")
        subprocess.run_git(["git", "merge", "--ff-only", "origin/main"], check=True, intent="ordinary")
        if not _merge_without_conflicts(bp, source_branch):
            _restore_branch(bp, original_branch)
            return False

        subprocess.run_git(["git", "push", "origin", "main"], check=True, intent="ordinary")
        _restore_branch(bp, original_branch)
        return True

    except subprocess.CalledProcessError as e:
        bp.logger.log("red", _("Error during merge: {0}").format(e))
        _restore_branch(bp, original_branch)
        return False


def _restore_branch(bp, branch: str) -> None:
    """Return to the branch the user started from, reporting any failure."""
    if not branch or GitUtils.get_current_branch() == branch:
        return
    result = subprocess.run_git(
        ["git", "checkout", branch], capture_output=True, text=True, check=False, intent="ordinary"
    )
    if result.returncode != 0:
        bp.logger.log("yellow", _("Could not switch back to {0}: {1}").format(branch, result.stderr.strip()))


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
