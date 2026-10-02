"""Is my branch in main? And bring every copy of it to the same commit.

origin/main is the main that counts: it is where pull requests land and where
stable packages are built from. The status compares the checked-out branch,
its copy on origin and the local main against it; ``sync_with_main`` then
fast-forwards whatever is only behind, so after a merged pull request all four
point at the same commit without typing a Git command.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from gitrepo.common import child_process as subprocess
from gitrepo.common.child_process import authorize_destructive_git
from gitrepo.common.translation import _

from . import branch_overview as overview
from .confirmation import StructuredConfirmation

MAIN = "main"
ORIGIN_MAIN = "origin/main"

# Verdicts, most reassuring first.
SYNCED = "synced"  # every copy on the same commit
CATCH_UP = "catch-up"  # the work is in origin/main; local copies are behind
WORK_PENDING = "work-pending"  # the branch holds commits origin/main lacks
UNAVAILABLE = "unavailable"  # nothing to compare: no repository, no origin/main, detached HEAD


@dataclass(frozen=True)
class RefState:
    """One of the four copies, and how it relates to origin/main."""

    label: str
    tip: overview.BranchTip | None
    # Against origin/main; None when this ref is origin/main or does not exist.
    vs_main: overview.Divergence | None
    is_reference: bool = False


@dataclass(frozen=True)
class SyncStatus:
    state: str
    branch: str = ""
    refs: tuple[RefState, ...] = ()
    # Commits on the branch that origin/main does not have yet.
    work_not_in_main: int = 0
    # Commits on the branch that origin/BRANCH does not have yet.
    unpushed: int = 0
    last_fetch: float | None = None
    last_fetch_failed: bool = False
    reason: str = ""

    @property
    def main_tip(self) -> overview.BranchTip | None:
        return next((ref.tip for ref in self.refs if ref.is_reference), None)


@dataclass(frozen=True)
class SyncStep:
    argv: tuple[str, ...]
    description: str
    # Steps that publish or move a branch away from commits only it holds.
    needs_confirmation: bool = False
    destructive: bool = False

    @property
    def command(self) -> str:
        return " ".join(self.argv)


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    return (
        subprocess.run_git(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            capture_output=True,
            check=False,
            intent="ordinary",
        ).returncode
        == 0
    )


def capture_sync_status() -> SyncStatus:
    """Compare the checked-out branch, its origin copy and local main with origin/main."""
    if overview._run(["git", "rev-parse", "--is-inside-work-tree"]).returncode != 0:
        return SyncStatus(state=UNAVAILABLE, reason=_("This folder is not a Git repository."))
    last_fetch, last_fetch_failed = overview._last_fetch()
    branch = overview._current_branch()
    if not branch:
        return SyncStatus(
            state=UNAVAILABLE,
            reason=_("No branch is checked out (detached HEAD)."),
            last_fetch=last_fetch,
            last_fetch_failed=last_fetch_failed,
        )
    local, remote = overview._read_tips()
    main_remote = remote.get(MAIN)
    if not main_remote:
        return SyncStatus(
            state=UNAVAILABLE,
            branch=branch,
            reason=_("origin has no main branch to compare with."),
            last_fetch=last_fetch,
            last_fetch_failed=last_fetch_failed,
        )

    def ref(label, tip):
        return RefState(label, tip, overview._divergence(tip.sha, main_remote.sha) if tip else None)

    refs = [ref(branch, local.get(branch))]
    if branch != MAIN:
        refs.append(ref(f"origin/{branch}", remote.get(branch)))
        refs.append(ref(MAIN, local.get(MAIN)))
    refs.append(RefState(ORIGIN_MAIN, main_remote, None, is_reference=True))

    branch_tip, branch_remote = local.get(branch), remote.get(branch)
    work = refs[0].vs_main.ahead if refs[0].vs_main else 0
    unpushed = overview._divergence(branch_tip.sha, branch_remote.sha).ahead if branch_tip and branch_remote else 0
    if work:
        state = WORK_PENDING
    elif all(item.tip and item.tip.sha == main_remote.sha for item in refs):
        state = SYNCED
    else:
        state = CATCH_UP
    return SyncStatus(
        state=state,
        branch=branch,
        refs=tuple(refs),
        work_not_in_main=work,
        unpushed=unpushed,
        last_fetch=last_fetch,
        last_fetch_failed=last_fetch_failed,
    )


# ---------------------------------------------------------------------------
# Plain-language presentation shared by the terminal and the window
# ---------------------------------------------------------------------------


def verdict(status: SyncStatus) -> tuple[str, str, str]:
    """Return (tone, title, description) for the whole status."""
    if status.state == UNAVAILABLE:
        return overview.TONE_NEUTRAL, _("Nothing to compare"), status.reason
    tip = status.main_tip
    if status.state == SYNCED:
        if status.branch == MAIN:
            description = _("main and origin/main are on the same commit ({0}).").format(tip.short_sha)
        else:
            description = _("{0}, origin/{0}, main and origin/main are on the same commit ({1}).").format(
                status.branch, tip.short_sha
            )
        return overview.TONE_OK, _("Everything is in sync"), description
    if status.state == CATCH_UP:
        return (
            overview.TONE_BEHIND,
            _("Your work is already in main"),
            _(
                "origin/main has everything from {0}, but some copies on this computer or on origin "
                "are still on older commits. Synchronize brings them all to {1}."
            ).format(status.branch, tip.short_sha),
        )
    description = _(
        "{0} has commits that origin/main does not have yet ({1}). Take them to main with a pull "
        "request or by building a stable package."
    ).format(status.branch, status.work_not_in_main)
    if status.unpushed:
        description += " " + _("{0} of them are not on origin yet: publish your changes first.").format(status.unpushed)
    return overview.TONE_AHEAD, _("{0} has work that is not in main").format(status.branch), description


def describe_ref(ref: RefState) -> tuple[str, str]:
    """Return (tone, text) for one copy against origin/main."""
    if ref.is_reference:
        return overview.TONE_NEUTRAL, _("Reference")
    if ref.tip is None:
        return overview.TONE_NEUTRAL, _("Does not exist")
    if ref.vs_main is None:
        return overview.TONE_NEUTRAL, _("Cannot compare")
    ahead, behind = ref.vs_main.ahead, ref.vs_main.behind
    return {
        overview.SAME: (overview.TONE_OK, _("Same as origin/main")),
        overview.AHEAD: (overview.TONE_AHEAD, _("{0} ahead of origin/main").format(ahead)),
        overview.BEHIND: (overview.TONE_BEHIND, _("{0} behind origin/main").format(behind)),
        overview.DIVERGED: (
            overview.TONE_DIVERGED,
            _("{0} ahead and {1} behind origin/main").format(ahead, behind),
        ),
    }[ref.vs_main.state]


# ---------------------------------------------------------------------------
# Synchronize
# ---------------------------------------------------------------------------


def _backup_name() -> str:
    base = f"backup/main-before-sync-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    name, suffix = base, 2
    while overview._run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"]).returncode == 0:
        name, suffix = f"{base}-{suffix}", suffix + 1
    return name


def plan_sync(status: SyncStatus) -> list[SyncStep]:
    """Return the fast-forwards and publications that align every copy with origin/main."""
    if status.state == UNAVAILABLE:
        return []
    branch = status.branch
    refs = {ref.label: ref for ref in status.refs}
    main_sha = status.main_tip.sha
    steps: list[SyncStep] = []

    branch_ref = refs[branch]
    branch_sha = branch_ref.tip.sha if branch_ref.tip else ""
    remote_ref = refs.get(f"origin/{branch}")
    # Commits someone else published on origin/BRANCH come first.
    if (
        branch != MAIN
        and branch_sha
        and remote_ref
        and remote_ref.tip
        and remote_ref.tip.sha != branch_sha
        and _is_ancestor(branch_sha, remote_ref.tip.sha)
    ):
        steps.append(
            SyncStep(
                ("git", "merge", "--ff-only", f"origin/{branch}"),
                _("Bring into {0} the commits already published on origin/{0}.").format(branch),
            )
        )
        branch_sha = remote_ref.tip.sha
    if branch_sha and branch_sha != main_sha and _is_ancestor(branch_sha, main_sha):
        steps.append(
            SyncStep(
                ("git", "merge", "--ff-only", ORIGIN_MAIN),
                _("Move {0} forward to origin/main; it only gains commits.").format(branch),
            )
        )
        branch_sha = main_sha

    if branch != MAIN:
        main_ref = refs[MAIN]
        if main_ref.tip is None:
            steps.append(
                SyncStep(("git", "branch", "--track", MAIN, ORIGIN_MAIN), _("Create the local main from origin/main."))
            )
        elif main_ref.tip.sha != main_sha:
            if _is_ancestor(main_ref.tip.sha, main_sha):
                steps.append(
                    SyncStep(
                        ("git", "fetch", ".", "refs/remotes/origin/main:refs/heads/main"),
                        _("Move the local main forward to origin/main; it only gains commits."),
                    )
                )
            else:
                backup = _backup_name()
                steps.append(
                    SyncStep(
                        ("git", "branch", backup, MAIN),
                        _("The local main has commits that origin/main does not have ({0}); keep them in {1}.").format(
                            main_ref.vs_main.ahead, backup
                        ),
                        needs_confirmation=True,
                    )
                )
                steps.append(
                    SyncStep(
                        ("git", "branch", "-f", MAIN, ORIGIN_MAIN),
                        _("Point the local main at origin/main."),
                        needs_confirmation=True,
                        destructive=True,
                    )
                )
        # Once the branch sits on origin/main, its copy on origin should too.
        if (
            branch_sha == main_sha
            and remote_ref
            and remote_ref.tip
            and remote_ref.tip.sha != main_sha
            and _is_ancestor(remote_ref.tip.sha, main_sha)
        ):
            steps.append(
                SyncStep(
                    ("git", "push", "origin", f"refs/heads/{branch}:refs/heads/{branch}"),
                    _("Publish {0} on origin so origin/{0} matches main too.").format(branch),
                    needs_confirmation=True,
                )
            )
    return steps


def _run_step(step: SyncStep):
    argv = list(step.argv)
    if step.destructive:
        with authorize_destructive_git():
            return subprocess.run_git(argv, capture_output=True, text=True, check=False, intent="destructive")
    return subprocess.run_git(argv, capture_output=True, text=True, check=False, intent="ordinary")


def _log_verdict(bp, status: SyncStatus) -> None:
    tone, title, description = verdict(status)
    color = {
        overview.TONE_OK: "green",
        overview.TONE_AHEAD: "cyan",
        overview.TONE_BEHIND: "yellow",
        overview.TONE_DIVERGED: "red",
    }.get(tone, "white")
    bp.logger.log(color, f"{title}: {description}")


def sync_with_main(bp, *, confirm: bool = True) -> bool:
    """Fetch origin, then fast-forward and publish what is only behind origin/main.

    Nothing that exists in a single place is lost: a local main holding its
    own commits is kept in a backup branch first, and only fast-forwards are
    pushed. Publishing or moving main away from its commits is confirmed
    unless *confirm* is false.
    """
    bp.logger.log("cyan", _("Running git fetch --prune origin..."))
    fetched, error = overview.fetch_origin()
    if not fetched:
        bp.logger.log("red", _("git fetch failed: {0}").format(error or _("unknown error")))
        return False

    status = capture_sync_status()
    if status.state == UNAVAILABLE:
        bp.logger.log("yellow", status.reason)
        return False
    steps = plan_sync(status)
    if not steps:
        _log_verdict(bp, status)
        return True

    if confirm and any(step.needs_confirmation for step in steps):
        # Each command follows the sentence that says what it changes.
        lines = [
            _("Synchronize with origin/main?"),
            _("Only fast-forwards run, so nothing is merged and no work is discarded."),
        ]
        for step in steps:
            lines.extend([step.description, step.command])
        question = "\n".join(lines)
        if not bp.menu.confirm(StructuredConfirmation(question), default_yes=True):
            bp.logger.log("yellow", _("Synchronization cancelled; only git fetch ran."))
            return False

    for step in steps:
        bp.logger.log("white", step.description)
        bp.logger.log("dim", f"  {step.command}")
        result = _run_step(step)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            bp.logger.log("red", _("Synchronization stopped at {0}: {1}").format(step.command, detail))
            if step.argv[:3] == ("git", "merge", "--ff-only"):
                bp.logger.log(
                    "yellow",
                    _("If Git mentions local changes, commit or stash them and synchronize again."),
                )
            return False

    _log_verdict(bp, capture_sync_status())
    return True
