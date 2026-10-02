"""Where every branch points, compared with origin and with the main branch.

Everything here reads refs that are already on disk: the origin side is only as
fresh as the last ``git fetch``, so the overview also reports when that was.
``fetch_origin`` is the one call that touches the network.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from gitrepo.common import child_process as subprocess
from gitrepo.common.translation import _

# The branch every other one is measured against, in order of preference.
BASE_CANDIDATES = ("main", "master")

SAME = "same"
AHEAD = "ahead"
BEHIND = "behind"
DIVERGED = "diverged"


@dataclass(frozen=True)
class Divergence:
    """Commits only the left side has (ahead) and only the right side has (behind)."""

    ahead: int
    behind: int

    @property
    def state(self) -> str:
        if self.ahead and self.behind:
            return DIVERGED
        if self.ahead:
            return AHEAD
        if self.behind:
            return BEHIND
        return SAME


@dataclass(frozen=True)
class BranchTip:
    sha: str
    short_sha: str
    subject: str
    # Committer date, seconds since the epoch.
    committed_at: int


@dataclass(frozen=True)
class BranchComparison:
    name: str
    local: BranchTip | None
    remote: BranchTip | None
    is_current: bool
    is_base: bool
    # Local branch against origin/NAME; None when either side is missing.
    vs_remote: Divergence | None
    # This branch against the base branch; None for the base itself.
    vs_base: Divergence | None


@dataclass(frozen=True)
class BranchOverview:
    base: str = ""
    # The ref the base side of vs_base was read from: "main" or "origin/main".
    base_ref: str = ""
    branches: tuple[BranchComparison, ...] = ()
    # Seconds since the epoch of the last fetch from any remote; None if never.
    last_fetch: float | None = None
    # A failed fetch still touches FETCH_HEAD, leaving it empty: its time then
    # says when origin was last asked, not when it was last read.
    last_fetch_failed: bool = False
    error: str = ""

    @property
    def needs_attention(self) -> tuple[BranchComparison, ...]:
        """Local branches that differ from their own copy on origin."""
        return tuple(
            branch for branch in self.branches if branch.vs_remote is not None and branch.vs_remote.state != SAME
        )


def _run(command: list[str]):
    return subprocess.run_git(command, capture_output=True, text=True, check=False, intent="ordinary")


def _output(command: list[str]) -> str:
    result = _run(command)
    return result.stdout.strip() if result.returncode == 0 else ""


_TIP_FORMAT = "%(refname)%00%(objectname)%00%(objectname:short)%00%(committerdate:unix)%00%(contents:subject)"


def _read_tips() -> tuple[dict[str, BranchTip], dict[str, BranchTip]]:
    """Return local and origin tips by branch name, read in a single Git call."""
    local: dict[str, BranchTip] = {}
    remote: dict[str, BranchTip] = {}
    output = _output(["git", "for-each-ref", f"--format={_TIP_FORMAT}", "refs/heads", "refs/remotes/origin"])
    for line in output.splitlines():
        parts = line.split("\0")
        if len(parts) != 5:
            continue
        refname, sha, short_sha, committed_at, subject = parts
        tip = BranchTip(
            sha=sha,
            short_sha=short_sha,
            subject=subject,
            committed_at=int(committed_at) if committed_at.isdigit() else 0,
        )
        if refname.startswith("refs/heads/"):
            local[refname.removeprefix("refs/heads/")] = tip
        elif refname.startswith("refs/remotes/origin/"):
            name = refname.removeprefix("refs/remotes/origin/")
            # origin/HEAD is a pointer to the default branch, not a branch.
            if name != "HEAD":
                remote[name] = tip
    return local, remote


def _divergence(left: str, right: str) -> Divergence | None:
    """Count commits on each side of ``left...right``; equal SHAs need no Git call."""
    if left == right:
        return Divergence(0, 0)
    counts = _output(["git", "rev-list", "--left-right", "--count", f"{left}...{right}"]).split()
    if len(counts) != 2 or not all(count.isdigit() for count in counts):
        return None
    return Divergence(int(counts[0]), int(counts[1]))


def _last_fetch() -> tuple[float | None, bool]:
    """Return when FETCH_HEAD was last written and whether that fetch failed."""
    path = _output(["git", "rev-parse", "--path-format=absolute", "--git-path", "FETCH_HEAD"])
    try:
        status = os.stat(path) if path else None
    except OSError:
        return None, False
    return (status.st_mtime, status.st_size == 0) if status else (None, False)


def _current_branch() -> str:
    return _output(["git", "symbolic-ref", "--quiet", "--short", "HEAD"])


def capture_branch_overview() -> BranchOverview:
    """Compare every local and origin branch without touching the network."""
    if _run(["git", "rev-parse", "--is-inside-work-tree"]).returncode != 0:
        return BranchOverview(error="not a git repository")
    local, remote = _read_tips()
    current = _current_branch()
    # origin/main is where pull requests land and stable packages come from;
    # a local main only stands in for it when origin has none.
    base = next((name for name in BASE_CANDIDATES if name in remote), "")
    base_tip = remote.get(base)
    base_ref = f"origin/{base}" if base else ""
    if not base_tip:
        base = next((name for name in BASE_CANDIDATES if name in local), "")
        base_tip = local.get(base)
        base_ref = base

    comparisons = []
    for name in sorted(set(local) | set(remote), key=lambda item: (item != base, item != current, item)):
        local_tip = local.get(name)
        remote_tip = remote.get(name)
        vs_remote = _divergence(local_tip.sha, remote_tip.sha) if local_tip and remote_tip else None
        tip = local_tip or remote_tip
        is_base = name == base
        vs_base = None if is_base or not base_tip or not tip else _divergence(tip.sha, base_tip.sha)
        comparisons.append(
            BranchComparison(
                name=name,
                local=local_tip,
                remote=remote_tip,
                is_current=name == current,
                is_base=is_base,
                vs_remote=vs_remote,
                vs_base=vs_base,
            )
        )
    last_fetch, last_fetch_failed = _last_fetch()
    return BranchOverview(
        base=base,
        base_ref=base_ref,
        branches=tuple(comparisons),
        last_fetch=last_fetch,
        last_fetch_failed=last_fetch_failed,
    )


def fetch_origin() -> tuple[bool, str]:
    """Refresh every origin/* ref; return success and Git's error text."""
    result = _run(["git", "fetch", "--prune", "origin"])
    return result.returncode == 0, (result.stderr or "").strip()


# ---------------------------------------------------------------------------
# Presentation shared by the CLI table and the GUI rows
# ---------------------------------------------------------------------------

# Symbolic icon per tone for the window; the terminal prints TONE_GLYPHS.
TONE_ICONS = {
    "ok": "object-select-symbolic",
    "ahead": "go-up-symbolic",
    "behind": "go-down-symbolic",
    "diverged": "dialog-warning-symbolic",
    "neutral": "",
}
TONE_GLYPHS = {"ok": "=", "ahead": "↑", "behind": "↓", "diverged": "↕", "neutral": "·"}

# One semantic tone per state; each interface maps it to its own colour.
TONE_OK = "ok"  # same commit: nothing to do
TONE_AHEAD = "ahead"  # holds commits the other side lacks
TONE_BEHIND = "behind"  # lacks commits the other side has
TONE_DIVERGED = "diverged"  # both: needs a merge or rebase
TONE_NEUTRAL = "neutral"  # nothing to compare

_STATE_TONES = {SAME: TONE_OK, AHEAD: TONE_AHEAD, BEHIND: TONE_BEHIND, DIVERGED: TONE_DIVERGED}


def describe_age(timestamp: float | None, now: float | None = None) -> str:
    """Say how long ago *timestamp* was, coarse enough to read at a glance."""
    if not timestamp:
        return _("never")
    seconds = max(0, int((now if now is not None else time.time()) - timestamp))
    if seconds < 60:
        return _("just now")
    if seconds < 3600:
        return _("{0} min ago").format(seconds // 60)
    if seconds < 86400:
        return _("{0} h ago").format(seconds // 3600)
    return _("{0} d ago").format(seconds // 86400)


def describe_freshness(overview: BranchOverview) -> tuple[str, str]:
    """Return (tone, text) saying how current the origin side of the overview is."""
    if overview.last_fetch_failed:
        return TONE_DIVERGED, _("the last git fetch failed ({0}); origin may be outdated").format(
            describe_age(overview.last_fetch)
        )
    text = _("origin as of the last git fetch: {0}").format(describe_age(overview.last_fetch))
    stale = overview.last_fetch is None or time.time() - overview.last_fetch > 86400
    return (TONE_BEHIND if stale else TONE_NEUTRAL), text


def describe_vs_remote(branch: BranchComparison) -> tuple[str, str]:
    """Return (tone, text) for a branch against its own copy on origin."""
    if branch.local is None:
        return TONE_NEUTRAL, _("Only on origin")
    if branch.remote is None:
        return TONE_NEUTRAL, _("Not on origin")
    if branch.vs_remote is None:
        return TONE_NEUTRAL, _("Cannot compare")
    ahead, behind = branch.vs_remote.ahead, branch.vs_remote.behind
    text = {
        SAME: _("Same as origin"),
        AHEAD: _("{0} to push").format(ahead),
        BEHIND: _("{0} to pull").format(behind),
        DIVERGED: _("{0} to push, {1} to pull").format(ahead, behind),
    }[branch.vs_remote.state]
    return _STATE_TONES[branch.vs_remote.state], text


def describe_vs_base(branch: BranchComparison, overview: BranchOverview) -> tuple[str, str]:
    """Return (tone, text) for a branch against the base branch."""
    if branch.is_base:
        return TONE_NEUTRAL, _("Base branch")
    if branch.vs_base is None:
        return TONE_NEUTRAL, _("No base to compare")
    ahead, behind, base = branch.vs_base.ahead, branch.vs_base.behind, overview.base_ref
    text = {
        SAME: _("Same as {0}").format(base),
        AHEAD: _("{0} ahead of {1}").format(ahead, base),
        BEHIND: _("{0} behind {1}").format(behind, base),
        DIVERGED: _("{0} ahead and {1} behind {2}").format(ahead, behind, base),
    }[branch.vs_base.state]
    return _STATE_TONES[branch.vs_base.state], text


def legend() -> tuple[tuple[str, str], ...]:
    """What each tone means, in the order the colours are explained."""
    return (
        (TONE_OK, _("same commit")),
        (TONE_AHEAD, _("has commits the other side lacks")),
        (TONE_BEHIND, _("lacks commits the other side has")),
        (TONE_DIVERGED, _("both: needs a merge or rebase")),
    )
