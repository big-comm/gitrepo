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


def _merge_to_main(bp, source_branch):
    """Merge a source branch without rewriting either branch history."""
    question = _(
        "Merge {0} into main and push origin/main?\n"
        "git fetch origin main\n"
        "git merge --ff-only origin/main\n"
        "git merge {0} --no-edit\n"
        "git push origin main"
    ).format(source_branch)
    if not bp.menu.confirm(question, default_yes=False):
        return False
    try:
        subprocess.run(["git", "fetch", "origin", "main"], check=True, capture_output=True)
        subprocess.run(["git", "checkout", "main"], check=True)
        subprocess.run(["git", "merge", "--ff-only", "origin/main"], check=True)
        merge_result = subprocess.run(
            ["git", "merge", source_branch, "--no-edit"], capture_output=True, text=True, check=False
        )
        if merge_result.returncode != 0:
            subprocess.run(["git", "merge", "--abort"], capture_output=True, check=False)
            bp.logger.log(
                "red",
                _("Merge stopped because it requires conflict resolution. No history was rewritten."),
            )
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
