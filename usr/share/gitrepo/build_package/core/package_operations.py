#
# core/package_operations.py - Improved package generation operations
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

from datetime import datetime

from gitrepo.common import child_process as subprocess
from gitrepo.common.child_process import authorize_destructive_git
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


def _prepare_working_branch(bp, branch_type: str, expected_testing_branch: str = "") -> str:
    if branch_type == "testing":
        branch = _testing_branch_for_current(bp, expected_testing_branch)
        if not branch:
            return ""
        return branch if _publish_testing_branch(bp, branch) else ""
    current = GitUtils.get_current_branch()
    if getattr(bp, "dry_run_mode", False):
        return "main"
    if current == "main":
        return "main" if _publish_main(bp) else ""
    if current != "main" and not _merge_to_main(bp, current):
        return ""
    return "main"


def _valid_development_branch(branch: str) -> bool:
    """Accept one syntactically valid development branch."""
    if not branch or not branch.startswith("dev-"):
        return False
    result = subprocess.run_git(
        ["git", "check-ref-format", "--branch", branch],
        capture_output=True,
        text=True,
        check=False,
        intent="ordinary",
    )
    return result.returncode == 0


def _testing_branch_for_current(bp, expected_branch: str = "") -> str:
    """Return the personal branch only when it is still the active branch."""
    branch = GitUtils.get_personal_branch(bp.github_user_name)
    if not _valid_development_branch(branch):
        bp.logger.log("red", _("Invalid target branch: {0}").format(branch or _("unknown branch")))
        return ""

    current = GitUtils.get_current_branch()
    if expected_branch and branch != expected_branch:
        bp.logger.log(
            "red",
            _(
                "The selected testing branch changed while preparing the package.\n"
                "Expected branch: {0}\n"
                "Selected branch: {1}"
            ).format(expected_branch, branch),
        )
        return ""
    if current != branch:
        bp.logger.log(
            "red",
            _(
                "Testing packages can only publish the active personal branch.\n"
                "Selected branch: {0}\n"
                "Current branch: {1}\n"
                "Switch to {0} before committing or starting the workflow."
            ).format(branch, current or _("unknown branch")),
        )
        return ""
    return branch


def _publish_testing_branch(bp, branch: str) -> bool:
    """Publish the exact reviewed development ref before dispatch."""
    if not _valid_development_branch(branch):
        bp.logger.log("red", _("Invalid target branch: {0}").format(branch or _("unknown branch")))
        return False
    if not GitUtils.ref_exists(f"refs/heads/{branch}"):
        bp.logger.log("red", _("The testing branch does not exist locally: {0}").format(branch))
        return False
    if getattr(bp, "dry_run_mode", False):
        return True

    refspec = f"refs/heads/{branch}:refs/heads/{branch}"
    question = _(
        "Publish the testing branch before starting its package workflow?\nBranch: {0}\nCommand: git push -u origin {1}"
    ).format(branch, refspec)
    if not bp.menu.confirm(question, default_yes=False):
        bp.logger.log("yellow", _("Package build cancelled."))
        return False

    result = subprocess.run_git(
        ["git", "push", "-u", "origin", refspec],
        capture_output=True,
        text=True,
        check=False,
        intent="ordinary",
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        bp.logger.log("red", _("Push failed: {0}").format(detail))
        return False
    bp.logger.log("green", _("✓ Successfully pushed '{0}' to remote!").format(branch))
    return True


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
    testing_branch = ""
    if branch_type == "testing":
        testing_branch = _testing_branch_for_current(bp)
        if not testing_branch:
            return False
    if not bp.github_api.ensure_github_token(bp.logger):
        bp.logger.log("red", _("Configure a GitHub token before generating a package."))
        return False
    if not _commit_pending_changes(bp, commit_message):
        return False

    if not _package_name(bp):
        return False
    working_branch = _prepare_working_branch(bp, branch_type, testing_branch)
    if not working_branch:
        return False
    package_name = _package_name(bp)
    if not package_name:
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


def _git_output(*args: str) -> str:
    """Return stripped output from a checked Git command."""
    return subprocess.run_git(
        ["git", *args],
        capture_output=True,
        text=True,
        check=True,
        intent="ordinary",
    ).stdout.strip()


def _abort_merge() -> None:
    """Abort an active merge without masking the original failure."""
    subprocess.run_git(["git", "merge", "--abort"], capture_output=True, check=False, intent="ordinary")


def _create_main_backup_if_needed(bp) -> str:
    """Preserve commits that exist only on the local main branch."""
    if not GitUtils.ref_exists("refs/heads/main"):
        return ""

    revision_args = ["rev-list", "--count", "refs/heads/main"]
    if GitUtils.ref_exists("refs/remotes/origin/main"):
        revision_args.extend(["--not", "refs/remotes/origin/main"])
    if int(_git_output(*revision_args)) == 0:
        return ""

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base_name = f"backup/main-before-stable-{timestamp}"
    backup_name = base_name
    suffix = 2
    while GitUtils.ref_exists(f"refs/heads/{backup_name}"):
        backup_name = f"{base_name}-{suffix}"
        suffix += 1

    subprocess.run_git(
        ["git", "branch", backup_name, "refs/heads/main"],
        capture_output=True,
        text=True,
        check=True,
        intent="ordinary",
    )
    bp.logger.log("yellow", _("Created a recovery branch for local main: {0}").format(backup_name))
    return backup_name


def _push_was_rejected(result) -> bool:
    """Return whether the remote moved while an atomic push was attempted."""
    output = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
    return result.returncode != 0 and any(
        marker in output
        for marker in (
            "[rejected]",
            "fetch first",
            "non-fast-forward",
            "stale info",
        )
    )


def _raise_push_error(result) -> None:
    """Raise one checked-process error retaining Git diagnostics."""
    raise subprocess.CalledProcessError(
        result.returncode,
        result.args,
        output=result.stdout,
        stderr=result.stderr,
    )


def _sync_source_and_promote_main(bp, source_branch: str, attempts: int = 3) -> bool:
    """Synchronize source and atomically publish it as source and main."""
    source_ref = f"refs/heads/{source_branch}"
    source_remote_ref = f"refs/remotes/origin/{source_branch}"
    source_refspec = f"{source_ref}:{source_ref}"

    for attempt in range(1, attempts + 1):
        subprocess.run_git(
            ["git", "fetch", "origin", "--prune"],
            check=True,
            capture_output=True,
            intent="ordinary",
        )

        if GitUtils.ref_exists(source_remote_ref) and not _merge_without_conflicts(bp, source_remote_ref):
            return False
        if not GitUtils.ref_exists("refs/remotes/origin/main"):
            bp.logger.log("red", _("The origin/main branch is required for stable and extra packages."))
            return False
        if not _merge_without_conflicts(bp, "refs/remotes/origin/main"):
            return False

        promotion = subprocess.run_git(
            [
                "git",
                "push",
                "--atomic",
                "origin",
                source_refspec,
                f"{source_ref}:refs/heads/main",
            ],
            capture_output=True,
            text=True,
            check=False,
            intent="ordinary",
        )
        if promotion.returncode == 0:
            return True
        if _push_was_rejected(promotion) and attempt < attempts:
            bp.logger.log("yellow", _("Remote refs changed during publication; retrying with their latest commits."))
            continue
        _raise_push_error(promotion)

    return False


def _sync_and_publish_main(bp, attempts: int = 3) -> bool:
    """Synchronize and publish main without constructing duplicate refspecs."""
    main_ref = "refs/heads/main"
    main_remote_ref = "refs/remotes/origin/main"
    for attempt in range(1, attempts + 1):
        subprocess.run_git(
            ["git", "fetch", "origin", "--prune"],
            check=True,
            capture_output=True,
            intent="ordinary",
        )
        if GitUtils.ref_exists(main_remote_ref) and not _merge_without_conflicts(bp, main_remote_ref):
            return False

        publication = subprocess.run_git(
            ["git", "push", "origin", f"{main_ref}:{main_ref}"],
            capture_output=True,
            text=True,
            check=False,
            intent="ordinary",
        )
        if publication.returncode == 0:
            return True
        if _push_was_rejected(publication) and attempt < attempts:
            bp.logger.log("yellow", _("Remote refs changed during publication; retrying with their latest commits."))
            continue
        _raise_push_error(publication)

    return False


def _publish_main(bp) -> bool:
    """Ensure the reviewed local main is the branch visible to the workflow."""
    if GitUtils.has_changes():
        bp.logger.log("red", _("Commit or stash local changes before building a stable package."))
        return False
    if not GitUtils.ref_exists("refs/heads/main"):
        bp.logger.log("red", _("Invalid target branch: {0}").format("main"))
        return False

    question = _(
        "Synchronize and publish main before starting its package workflow?\n"
        "git fetch origin --prune\n"
        "git merge refs/remotes/origin/main --no-edit (when present)\n"
        "git push origin refs/heads/main:refs/heads/main"
    )
    if not bp.menu.confirm(question, default_yes=False):
        return False

    try:
        return _sync_and_publish_main(bp)
    except subprocess.CalledProcessError as error:
        _abort_merge()
        detail = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr
        bp.logger.log("red", _("Error during merge: {0}").format((detail or str(error)).strip()))
        return False


def _align_local_main() -> None:
    """Align local main with the successfully promoted remote branch."""
    subprocess.run_git(
        ["git", "fetch", "origin", "+refs/heads/main:refs/remotes/origin/main"],
        check=True,
        capture_output=True,
        intent="ordinary",
    )
    with authorize_destructive_git():
        subprocess.run_git(
            ["git", "branch", "-f", "main", "refs/remotes/origin/main"],
            check=True,
            capture_output=True,
            intent="destructive",
        )
    subprocess.run_git(
        ["git", "branch", "--set-upstream-to=origin/main", "main"],
        check=True,
        capture_output=True,
        intent="ordinary",
    )


def _merge_to_main(bp, source_branch):
    """Safely synchronize a development branch and promote it to main."""
    if source_branch == "main":
        return _publish_main(bp)
    if GitUtils.has_changes():
        bp.logger.log("red", _("Commit or stash local changes before building a stable package."))
        return False

    source_ref = f"refs/heads/{source_branch}"
    if not GitUtils.ref_exists(source_ref):
        bp.logger.log("red", _("Invalid target branch: {0}").format(source_branch))
        return False

    question = _(
        "Publish {0} through main?\n"
        "git fetch origin --prune\n"
        "git checkout {0}\n"
        "git merge refs/remotes/origin/{0} --no-edit (when present)\n"
        "git merge refs/remotes/origin/main --no-edit\n"
        "git push --atomic origin refs/heads/{0}:refs/heads/{0} "
        "refs/heads/{0}:refs/heads/main\n"
        "Local-only main commits are preserved in backup/main-before-stable-*."
    ).format(source_branch)
    if not bp.menu.confirm(question, default_yes=False):
        return False

    original_branch = GitUtils.get_current_branch()
    success = False
    try:
        subprocess.run_git(["git", "fetch", "origin", "--prune"], check=True, capture_output=True, intent="ordinary")
        subprocess.run_git(["git", "checkout", source_branch], check=True, capture_output=True, intent="ordinary")
        _create_main_backup_if_needed(bp)
        if _sync_source_and_promote_main(bp, source_branch):
            try:
                _align_local_main()
                success = True
            except subprocess.CalledProcessError as error:
                detail = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr
                bp.logger.log(
                    "red",
                    _("Remote branches {0} and main were published, but local main could not be aligned: {1}").format(
                        source_branch, (detail or str(error)).strip()
                    ),
                )

    except subprocess.CalledProcessError as e:
        _abort_merge()
        detail = e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else e.stderr
        bp.logger.log("red", _("Error during merge: {0}").format((detail or str(e)).strip()))
    finally:
        if not _restore_branch(bp, original_branch):
            success = False
    return success


def _restore_branch(bp, branch: str) -> bool:
    """Return to the branch the user started from, reporting any failure."""
    if not branch or GitUtils.get_current_branch() == branch:
        return True
    result = subprocess.run_git(
        ["git", "checkout", branch], capture_output=True, text=True, check=False, intent="ordinary"
    )
    if result.returncode != 0:
        bp.logger.log("yellow", _("Could not switch back to {0}: {1}").format(branch, result.stderr.strip()))
        return False
    return True


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
