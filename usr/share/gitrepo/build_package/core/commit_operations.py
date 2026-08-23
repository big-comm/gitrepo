"""Commit/push entry point shared by CLI and package generation."""

from dataclasses import replace
from pathlib import Path

from gitrepo.common import child_process as subprocess

from .commit_handler import execute_commit, publish_existing_commit
from .confirmation import StructuredConfirmation, parse_confirmation_content
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


def _ensure_initial_branch(bp, expected: str) -> str:
    """Create the user's development branch in a repository without commits."""
    branch = GitUtils.get_current_branch()
    if GitUtils.has_commits():
        return branch
    if branch == expected:
        return expected
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
    """Honor an explicit override without moving ordinary committed work."""
    repo_path = getattr(bp, "repo_path", None)
    configured = GitUtils.get_configured_personal_branch(repo_path)
    if configured:
        return configured
    if GitUtils.has_commits():
        return GitUtils.get_current_branch()
    return GitUtils.get_personal_branch(bp.github_user_name, repo_path)


def _display_commit_message(message: str) -> str:
    """Quote user text and keep its line boundaries visible in the preview."""
    lines = message.split("\n")
    visible_message = lines[0]
    if len(lines) > 1:
        continuation = "\n".join(f"│ {line}" if line else "│" for line in lines[1:])
        visible_message = f"{visible_message}\n{continuation}"
    return f"“{visible_message}”"


def _commit_confirmation_prompt(
    branch: str,
    message: str,
    version_line: str,
    file_preview: str,
    push: bool = True,
) -> StructuredConfirmation:
    """Keep the CLI preview clear and the graphical message truly multiline."""
    message_marker = "\0gitrepo-commit-message\0"
    display_message = "\n".join(message.splitlines()) or message
    # The preview names the commands it is about to run, so a commit that stops
    # short of the remote must not promise a push.
    template = (
        _(
            "Publish these changes?\n"
            'Commands: git add -A → git commit -m "MESSAGE" → git push -u origin BRANCH\n'
            "Branch: {0}\nMessage: {1}\n{2}Files:\n{3}"
        )
        if push
        else _(
            "Commit these changes locally?\n"
            'Commands: git add -A → git commit -m "MESSAGE"\n'
            "Nothing is pushed; origin/BRANCH stays unchanged.\n"
            "Branch: {0}\nMessage: {1}\n{2}Files:\n{3}"
        )
    )
    semantic_question = template.format(branch, message_marker, version_line, file_preview)
    content = parse_confirmation_content(semantic_question)
    content = replace(
        content,
        blocks=tuple(
            replace(block, value=display_message) if block.value == message_marker else block
            for block in content.blocks
        ),
    )
    question = template.format(branch, _display_commit_message(display_message), version_line, file_preview)
    return StructuredConfirmation.from_content(question, content)


def _confirm_commit(bp, branch: str, message: str, bump=None, push: bool = True) -> bool:
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
            bump.current_version,
            bump.new_version,
            bump.bump_level,
            display_path(bump.relative_path),
        )
        if bump
        else ""
    )
    question = _commit_confirmation_prompt(
        branch,
        message,
        version_line,
        file_preview or _("No changed paths detected"),
        push,
    )
    return bp.menu.confirm(question, default_yes=False)


def _pending_publication(bp) -> dict | None:
    """Describe a clean local branch tip that still needs publication."""
    branch = GitUtils.get_current_branch()
    commit_sha = GitUtils.get_head_sha()
    if not branch or branch == "HEAD" or not commit_sha:
        return None

    details = getattr(bp, "last_operation_details", {}) or {}
    known_pending = bool(details.get("local_commit_created") and details.get("remote_unchanged"))
    if known_pending:
        pending_branch = details.get("current_branch", "")
        pending_sha = details.get("local_commit_created", "")
        if pending_branch != branch:
            bp.logger.log(
                "yellow",
                _("Commit {0} is still waiting on {1}; switch to that branch before retrying.").format(
                    pending_sha[:12], pending_branch
                ),
            )
            return {"blocked": True}
        if pending_sha != commit_sha:
            bp.logger.log(
                "yellow",
                _("The branch tip changed after commit {0} failed to publish; review it before retrying.").format(
                    pending_sha[:12]
                ),
            )
            return {"blocked": True}

    if not GitUtils.get_origin_url():
        if known_pending:
            bp.logger.log("red", _("The local commit cannot be published because origin is not configured."))
            return {"blocked": True}
        return None

    divergence = GitUtils.check_branch_divergence(branch)
    if divergence.get("error"):
        if known_pending:
            bp.logger.log("red", _("Could not verify whether the local commit reached origin."))
            return {"blocked": True}
        return None

    remote_exists = GitUtils.ref_exists(f"refs/remotes/origin/{branch}")
    ahead = int(divergence.get("ahead", 0))
    behind = int(divergence.get("behind", 0))
    if remote_exists and ahead == 0 and behind == 0:
        if known_pending:
            bp.last_operation_details = {}
            bp.logger.log(
                "green", _("The previously created commit is already published on origin/{0}.").format(branch)
            )
            return {"published": True}
        return None
    if behind > 0:
        if known_pending or ahead > 0:
            bp.logger.log(
                "red",
                _("origin/{0} changed; download and review those updates before retrying the push.").format(branch),
            )
            return {"blocked": True}
        return None
    if ahead > 0 or not remote_exists:
        return {
            "branch": branch,
            "commit_sha": commit_sha,
            "ahead": ahead,
            "remote_exists": remote_exists,
        }
    return None


def _retry_pending_publication(bp) -> bool | None:
    """Confirm and publish an existing clean branch tip, or return None."""
    pending = _pending_publication(bp)
    if pending is None:
        return None
    if pending.get("blocked"):
        return False
    if pending.get("published"):
        return True

    branch = pending["branch"]
    commit_sha = pending["commit_sha"]
    refspec = f"refs/heads/{branch}:refs/heads/{branch}"
    retry_command = f"git push -u origin {refspec}"
    remote_state = (
        _("Local commits not on origin: {0}").format(pending["ahead"])
        if pending["remote_exists"]
        else _("The branch origin/{0} does not exist yet.").format(branch)
    )
    question = _(
        "Publish the existing local commit?\n"
        "No new commit will be created.\n"
        "Branch: {0}\n"
        "Commit: {1}\n"
        "{2}\n"
        "Command: {3}"
    ).format(branch, commit_sha[:12], remote_state, retry_command)
    if not bp.menu.confirm(StructuredConfirmation(question), default_yes=False):
        bp.logger.log("yellow", _("Publication retry cancelled."))
        return False
    if getattr(bp, "dry_run_mode", False):
        bp.logger.log("green", _("Dry run completed; the pending commit was not pushed."))
        return True

    try:
        result = publish_existing_commit(bp, branch)
    except (RuntimeError, subprocess.SubprocessError) as error:
        bp.logger.log("red", _("Publication retry failed: {0}").format(error))
        return False
    bp.last_operation_details = {}
    return result


@journey("publishing changes", False)
def commit_and_push(build_package_instance, push: bool = True) -> bool:
    """Validate, preview, commit, and — unless *push* is false — publish once.

    With ``push=False`` the journey stops at the commit. A clean tree is then
    left alone rather than offered for publication: the caller asked not to
    touch the remote, so pushing an earlier pending commit would be exactly the
    thing they declined.
    """
    bp = build_package_instance
    if not bp.is_git_repo:
        bp.logger.log("red", _("This option is only available in Git repositories."))
        return False
    if bp.conflict_resolver and bp.conflict_resolver.has_conflicts() and not bp.conflict_resolver.resolve():
        bp.logger.log("red", _("Resolve all conflicts before committing."))
        return False
    if not GitUtils.has_changes():
        if not push:
            bp.logger.log("yellow", _("No changes to commit"))
            return True
        retry_result = _retry_pending_publication(bp)
        if retry_result is not None:
            return retry_result
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
    if not _confirm_commit(bp, branch, message, bump, push):
        bp.logger.log("yellow", _("Commit cancelled."))
        return False
    if getattr(bp, "dry_run_mode", False):
        bp.logger.log("green", _("Dry run completed; no files or refs were changed."))
        return True

    # A bump the user approved but that cannot be written must stop the
    # publication; committing without it ships a version nobody reviewed.
    if bump and not publish_version_bump(bp, bump):
        bp.logger.log("red", _("Publication stopped because the reviewed version bump could not be written."))
        return False

    if GitUtils.has_commits() and GitUtils.get_current_branch() != branch:
        from .branch_handler import switch_and_commit

        return switch_and_commit(bp, branch, message, push=push)

    branch = _ensure_initial_branch(bp, branch)
    if not branch:
        bp.logger.log("red", _("Could not create or select the target branch."))
        return False

    try:
        return execute_commit(bp, message, branch, push=push)
    except (RuntimeError, subprocess.SubprocessError) as error:
        bp.logger.log("red", _("Commit failed: {0}").format(error))
        return False
