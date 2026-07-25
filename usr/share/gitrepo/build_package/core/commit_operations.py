"""Commit/push entry point shared by CLI and package generation."""

from pathlib import Path

from gitrepo.common import child_process as subprocess

from .commit_handler import execute_commit
from .git_status import display_path
from .repository_lock import journey
from .git_utils import GitUtils
from .version_bumper import plan_version_bump, publish_version_bump
from gitrepo.common.translation import _


def _read_commit_message(bp) -> str:
    """Resolve one non-empty message from file, argv, or interactive input."""
    if bp.args.commit_file:
        try:
            message = Path(bp.args.commit_file).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as error:
            bp.logger.log("red", _("Could not read commit message file: {0}").format(error))
            return ""
    elif bp.args.commit:
        message = bp.args.commit.strip()
    else:
        message = (bp.custom_commit_prompt() or "").strip()
    if not message:
        bp.logger.log("red", _("Commit message cannot be empty."))
    return message


def _ensure_initial_branch(bp) -> str:
    """Create the user's development branch in a repository without commits."""
    branch = GitUtils.get_current_branch()
    if GitUtils.has_commits():
        return branch
    expected = f"dev-{bp.github_user_name or 'unknown'}"
    result = subprocess.run_git(
        ["git", "checkout", "-b", expected], capture_output=True, text=True, check=False, intent="ordinary"
    )
    if result.returncode == 0:
        return expected
    existing = subprocess.run_git(
        ["git", "checkout", expected], capture_output=True, text=True, check=False, intent="ordinary"
    )
    return expected if existing.returncode == 0 else ""


def _planned_branch(bp) -> str:
    """Return the target branch without changing an unborn repository."""
    if GitUtils.has_commits():
        return GitUtils.get_current_branch()
    return f"dev-{bp.github_user_name or 'unknown'}"


def _confirm_commit(bp, branch: str, message: str, bump=None) -> bool:
    """Show the exact branch, message, paths, and version change before mutation."""
    # get_changed_files() yields (status, path); the preview wants the paths.
    files = [path for _status, path in GitUtils.get_changed_files()]
    # The bump is published by this same journey, so it belongs in the review.
    if bump and bump.relative_path not in files:
        files.append(bump.relative_path)
    file_preview = "\n".join(f"• {display_path(path)}" for path in files[:30])
    if len(files) > 30:
        file_preview += _("\n• … and {0} more").format(len(files) - 30)
    version_line = (
        _("Version: {0} → {1} ({2}) in {3}\n").format(
            bump.current_version, bump.new_version, bump.bump_level, bump.relative_path
        )
        if bump
        else ""
    )
    question = _(
        "Publish these changes?\n"
        'Commands: git add -A → git commit -m "MESSAGE" → git push -u origin BRANCH\n'
        "Branch: {0}\nMessage: {1}\n{2}Files:\n{3}"
    ).format(
        branch,
        message,
        version_line,
        file_preview or _("No changed paths detected"),
    )
    return bp.menu.confirm(question, default_yes=False)


@journey("publishing changes", False)
def commit_and_push(build_package_instance) -> bool:
    """Validate, preview, commit, synchronize safely, and push once."""
    bp = build_package_instance
    if not bp.is_git_repo:
        bp.logger.log("red", _("This option is only available in Git repositories."))
        return False
    if bp.conflict_resolver and bp.conflict_resolver.has_conflicts() and not bp.conflict_resolver.resolve():
        bp.logger.log("red", _("Resolve all conflicts before committing."))
        return False
    if not GitUtils.has_changes():
        bp.logger.log("yellow", _("No changes to commit"))
        return True

    branch = _planned_branch(bp)
    message = _read_commit_message(bp)
    if not branch or not message:
        return False

    bump = (
        plan_version_bump(bp, message, getattr(bp, "last_commit_type", None))
        if bp.settings.get("auto_version_bump", True)
        else None
    )
    if not _confirm_commit(bp, branch, message, bump):
        bp.logger.log("yellow", _("Commit cancelled."))
        return False
    if getattr(bp, "dry_run_mode", False):
        bp.logger.log("green", _("Dry run completed; no files or refs were changed."))
        return True

    branch = _ensure_initial_branch(bp)
    if not branch:
        bp.logger.log("red", _("Could not create or select the target branch."))
        return False

    # A bump the user approved but that cannot be written must stop the
    # publication; committing without it ships a version nobody reviewed.
    if bump and not publish_version_bump(bp, bump):
        bp.logger.log("red", _("Publication stopped because the reviewed version bump could not be written."))
        return False
    try:
        return execute_commit(bp, message, branch)
    except (RuntimeError, subprocess.SubprocessError) as error:
        bp.logger.log("red", _("Commit failed: {0}").format(error))
        return False
