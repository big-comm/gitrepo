"""Where branches were, what a move changes, and how to take it back.

Every GitRepo operation that moves a branch leaves a checkpoint in
``.git/gitrepo-undo.json``: which branch heads it moved, from where to where,
and which of them it published to origin. Undo puts those heads back, keeping
uncommitted work (``git reset --keep``), and republishes the old commit only
for pushes GitRepo itself made, never on a shared branch.

Going back to an older commit is the same move started by hand: the branch
points at the chosen commit, and the commits after it stay reachable through
the checkpoint until it is undone or replaced.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field

from gitrepo.common import child_process as subprocess
from gitrepo.common.child_process import authorize_destructive_git
from gitrepo.common.translation import _

JOURNAL_NAME = "gitrepo-undo.json"
KEEP = 20
# Branches others build on: never rewritten on origin, never moved back by hand.
SHARED_BRANCHES = frozenset({"main", "master"})


@dataclass(frozen=True)
class FileChange:
    status: str  # A added, M modified, D deleted, R renamed
    path: str


@dataclass(frozen=True)
class RefMove:
    branch: str
    before: str
    after: str


@dataclass(frozen=True)
class Checkpoint:
    id: str
    operation: str
    at: float
    moves: tuple[RefMove, ...]
    pushes: tuple[RefMove, ...] = ()


@dataclass(frozen=True)
class PreviewStep:
    icon: str
    text: str
    command: str = ""


@dataclass(frozen=True)
class Preview:
    """Everything a confirmation shows, independent of the interface drawing it."""

    heading: str
    summary: str
    steps: tuple[PreviewStep, ...] = ()
    files_title: str = ""
    files: tuple[FileChange, ...] = ()
    notices: tuple[tuple[str, str], ...] = ()  # (tone, text): "warning" or "info"
    # Set when part of the change could also be applied on origin.
    remote_title: str = ""
    remote_steps: tuple[PreviewStep, ...] = ()
    extra: dict = field(default_factory=dict, compare=False)


# ---------------------------------------------------------------------------
# Git reads
# ---------------------------------------------------------------------------


def _git(args: list[str], *, destructive: bool = False):
    if destructive:
        with authorize_destructive_git():
            return subprocess.run_git(args, capture_output=True, text=True, check=False, intent="destructive")
    return subprocess.run_git(args, capture_output=True, text=True, check=False, intent="ordinary")


def _out(args: list[str]) -> str:
    result = _git(args)
    return result.stdout.strip() if result.returncode == 0 else ""


def short(sha: str) -> str:
    return sha[:8]


def current_branch() -> str:
    return _out(["git", "symbolic-ref", "--quiet", "--short", "HEAD"])


def branch_heads() -> dict[str, str]:
    """Every local branch and the commit it points at."""
    heads = {}
    for line in _out(["git", "for-each-ref", "--format=%(refname:short)%00%(objectname)", "refs/heads"]).splitlines():
        name, _sep, sha = line.partition("\0")
        if name and sha:
            heads[name] = sha
    return heads


def remote_head(branch: str) -> str:
    return _out(["git", "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"])


def is_ancestor(ancestor: str, descendant: str) -> bool:
    return _git(["git", "merge-base", "--is-ancestor", ancestor, descendant]).returncode == 0


def file_changes(before: str, after: str) -> tuple[FileChange, ...]:
    """Files that differ between two commits, as the working tree would see them change."""
    if not before or not after or before == after:
        return ()
    result = subprocess.run_git(
        ["git", "diff", "--name-status", "-z", "--find-renames", before, after],
        capture_output=True,
        check=False,
        intent="ordinary",
    )
    if result.returncode != 0:
        return ()
    records = [os.fsdecode(part) for part in result.stdout.split(b"\0")]
    changes, index = [], 0
    while index < len(records) and records[index]:
        status = records[index][:1]
        if status in ("R", "C") and index + 2 < len(records):
            changes.append(FileChange(status, f"{records[index + 1]} → {records[index + 2]}"))
            index += 3
        else:
            changes.append(FileChange(status, records[index + 1] if index + 1 < len(records) else ""))
            index += 2
    return tuple(changes)


def commits_between(older: str, newer: str, limit: int = 50) -> list[tuple[str, str]]:
    """(short sha, subject) of the commits *newer* has and *older* lacks, newest first."""
    if not older or not newer or older == newer:
        return []
    output = _out(["git", "log", f"-{limit}", "--format=%h%x00%s", f"{older}..{newer}"])
    return [tuple(line.split("\0", 1)) for line in output.splitlines() if "\0" in line]


def recent_commits(limit: int = 30) -> list[dict]:
    """The latest commits reachable from the checked-out branch, newest first.

    Not --first-parent: after a sync lands the branch on a merge made from
    main, the branch's own previous commit is that merge's second parent, and
    it is exactly the one someone going back is looking for.
    """
    output = _out(["git", "log", f"-{limit}", "--format=%H%x00%h%x00%s%x00%an%x00%ct"])
    commits = []
    for line in output.splitlines():
        parts = line.split("\0")
        if len(parts) == 5:
            commits.append(
                {
                    "sha": parts[0],
                    "short": parts[1],
                    "subject": parts[2],
                    "author": parts[3],
                    "time": int(parts[4]) if parts[4].isdigit() else 0,
                }
            )
    return commits


# ---------------------------------------------------------------------------
# Checkpoint journal
# ---------------------------------------------------------------------------


def _journal_path() -> str:
    return _out(["git", "rev-parse", "--path-format=absolute", "--git-path", JOURNAL_NAME])


def load_checkpoints() -> list[Checkpoint]:
    path = _journal_path()
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return []
    checkpoints = []
    for entry in raw if isinstance(raw, list) else []:
        try:
            checkpoints.append(
                Checkpoint(
                    id=str(entry["id"]),
                    operation=str(entry["operation"]),
                    at=float(entry["at"]),
                    moves=tuple(RefMove(**move) for move in entry.get("moves", [])),
                    pushes=tuple(RefMove(**move) for move in entry.get("pushes", [])),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return checkpoints


def _save_checkpoints(checkpoints: list[Checkpoint]) -> None:
    path = _journal_path()
    if not path:
        return
    document = [
        {
            "id": checkpoint.id,
            "operation": checkpoint.operation,
            "at": checkpoint.at,
            "moves": [move.__dict__ for move in checkpoint.moves],
            "pushes": [move.__dict__ for move in checkpoint.pushes],
        }
        for checkpoint in checkpoints[-KEEP:]
    ]
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=1)
    os.replace(temporary, path)


def record(operation: str, before: dict[str, str], pushes: tuple[RefMove, ...] = ()) -> Checkpoint | None:
    """Keep a checkpoint for the branch heads that moved since *before*; None if nothing moved."""
    after = branch_heads()
    moves = tuple(
        RefMove(branch, before[branch], after[branch])
        for branch in sorted(set(before) & set(after))
        if before[branch] != after[branch]
    )
    if not moves and not pushes:
        return None
    checkpoint = Checkpoint(uuid.uuid4().hex, operation, time.time(), moves, tuple(pushes))
    _save_checkpoints([*load_checkpoints(), checkpoint])
    return checkpoint


def latest_checkpoint() -> tuple[Checkpoint | None, str]:
    """The checkpoint Undo would take back, or None with the reason it cannot."""
    checkpoints = load_checkpoints()
    if not checkpoints:
        return None, _("Nothing to undo yet.")
    checkpoint = checkpoints[-1]
    heads = branch_heads()
    moved_since = [move.branch for move in checkpoint.moves if heads.get(move.branch) != move.after]
    if moved_since:
        return None, _("{0} changed after “{1}”, so it can no longer be undone safely.").format(
            ", ".join(moved_since), checkpoint.operation
        )
    return checkpoint, ""


def _forget(checkpoint_id: str) -> None:
    _save_checkpoints([checkpoint for checkpoint in load_checkpoints() if checkpoint.id != checkpoint_id])


# ---------------------------------------------------------------------------
# Moving a branch, here and on origin
# ---------------------------------------------------------------------------


def _move_branch(branch: str, before: str, target: str) -> tuple[bool, str]:
    """Point *branch* at *target*; the checked-out branch keeps uncommitted work."""
    if branch == current_branch():
        result = _git(["git", "reset", "--keep", target], destructive=True)
    else:
        # Compare-and-swap: refuses when the branch is no longer where we expect it.
        result = _git(["git", "update-ref", f"refs/heads/{branch}", target, before], destructive=True)
    return result.returncode == 0, (result.stderr or result.stdout or "").strip()


def _republish(branch: str, expected_on_origin: str, target: str) -> tuple[bool, str]:
    """Put origin/BRANCH on *target* only if it still holds *expected_on_origin*."""
    result = _git(
        [
            "git",
            "push",
            f"--force-with-lease=refs/heads/{branch}:{expected_on_origin}",
            "origin",
            f"{target}:refs/heads/{branch}",
        ],
        destructive=True,
    )
    return result.returncode == 0, (result.stderr or result.stdout or "").strip()


def _move_steps(moves, *, back: bool) -> tuple[PreviewStep, ...]:
    steps = []
    current = current_branch()
    for move in moves:
        source, target = (move.after, move.before) if back else (move.before, move.after)
        command = (
            f"git reset --keep {short(target)}"
            if move.branch == current
            else f"git update-ref refs/heads/{move.branch} {short(target)}"
        )
        steps.append(
            PreviewStep(
                "edit-undo-symbolic" if back else "go-next-symbolic",
                _("{0}: from {1} back to {2}").format(move.branch, short(source), short(target))
                if back
                else _("{0}: from {1} to {2}").format(move.branch, short(source), short(target)),
                command,
            )
        )
    return tuple(steps)


def _files_of_current(moves, *, back: bool) -> tuple[str, tuple[FileChange, ...]]:
    current = current_branch()
    for move in moves:
        if move.branch == current:
            source, target = (move.after, move.before) if back else (move.before, move.after)
            return _("Files that change in {0}").format(current), file_changes(source, target)
    return "", ()


def _deletion_notice(files) -> tuple[tuple[str, str], ...]:
    deleted = sum(1 for change in files if change.status == "D")
    if not deleted:
        return ()
    return (("warning", _("{0} file(s) will be deleted from your branch. Check the list below.").format(deleted)),)


def preview_undo(checkpoint: Checkpoint) -> Preview:
    files_title, files = _files_of_current(checkpoint.moves, back=True)
    remote = [push for push in checkpoint.pushes if push.branch not in SHARED_BRANCHES]
    notices = list(_deletion_notice(files))
    kept = [push.branch for push in checkpoint.pushes if push.branch in SHARED_BRANCHES]
    if kept:
        notices.append(("info", _("{0} is shared: what was published there stays on GitHub.").format(", ".join(kept))))
    return Preview(
        heading=_("Undo “{0}”?").format(checkpoint.operation),
        summary=_("The branches go back to where they were before this operation. Uncommitted files are kept."),
        steps=_move_steps(checkpoint.moves, back=True),
        files_title=files_title,
        files=files,
        notices=tuple(notices),
        remote_title=_("Also put GitHub back") if remote else "",
        remote_steps=tuple(
            PreviewStep(
                "network-server-symbolic",
                _("origin/{0}: from {1} back to {2}").format(push.branch, short(push.after), short(push.before)),
                f"git push --force-with-lease origin {short(push.before)}:{push.branch}",
            )
            for push in remote
        ),
    )


def undo(bp, checkpoint: Checkpoint, *, include_remote: bool) -> bool:
    """Take *checkpoint* back; on origin only when asked and only for unshared branches."""
    current, reason = latest_checkpoint()
    if current is None or current.id != checkpoint.id:
        bp.logger.log("red", reason or _("This operation can no longer be undone."))
        return False
    for move in checkpoint.moves:
        bp.logger.log("white", _("{0}: back to {1}").format(move.branch, short(move.before)))
        ok, detail = _move_branch(move.branch, move.after, move.before)
        if not ok:
            bp.logger.log("red", _("Could not move {0} back: {1}").format(move.branch, detail))
            bp.logger.log("yellow", _("If Git mentions local changes, commit or stash them and undo again."))
            return False
    if include_remote:
        for push in checkpoint.pushes:
            if push.branch in SHARED_BRANCHES:
                continue
            bp.logger.log("white", _("origin/{0}: back to {1}").format(push.branch, short(push.before)))
            ok, detail = _republish(push.branch, push.after, push.before)
            if not ok:
                bp.logger.log("red", _("GitHub was not changed: {0}").format(detail))
                _forget(checkpoint.id)
                return False
    _forget(checkpoint.id)
    bp.logger.log("green", _("“{0}” was undone.").format(checkpoint.operation))
    return True


def preview_go_back(target: str) -> Preview:
    """What pointing the checked-out branch at *target* changes, here and possibly on origin."""
    branch = current_branch()
    head = _out(["git", "rev-parse", "HEAD"])
    dropped = commits_between(target, head)
    files = file_changes(head, target)
    notices = list(_deletion_notice(files))
    notices.append(
        (
            "info",
            _("The commits leaving {0} are not lost: Undo brings them back.").format(branch),
        )
    )
    on_origin = remote_head(branch)
    remote_steps = ()
    if on_origin and on_origin != target and is_ancestor(target, on_origin):
        remote_steps = (
            PreviewStep(
                "network-server-symbolic",
                _("origin/{0}: from {1} back to {2}").format(branch, short(on_origin), short(target)),
                f"git push --force-with-lease origin {short(target)}:{branch}",
            ),
        )
    return Preview(
        heading=_("Go back to {0}?").format(short(target)),
        summary=_("{0} will point at {1}; {2} commit(s) after it leave the branch.").format(
            branch, short(target), len(dropped)
        ),
        steps=(
            *(
                PreviewStep("list-remove-symbolic", _("Leaves {0}: {1} {2}").format(branch, sha, subject))
                for sha, subject in dropped
            ),
            PreviewStep(
                "edit-undo-symbolic",
                _("{0} now points at {1}").format(branch, short(target)),
                f"git reset --keep {short(target)}",
            ),
        ),
        files_title=_("Files that change in {0}").format(branch),
        files=files,
        notices=tuple(notices),
        remote_title=_("Also go back on GitHub") if remote_steps else "",
        remote_steps=remote_steps,
        extra={"branch": branch, "on_origin": on_origin},
    )


def can_go_back(branch: str) -> tuple[bool, str]:
    if not branch:
        return False, _("No branch is checked out (detached HEAD).")
    if branch in SHARED_BRANCHES:
        return False, _("{0} is shared; take changes back on it with a revert instead.").format(branch)
    return True, ""


def go_back(bp, target: str, *, include_remote: bool) -> bool:
    """Point the checked-out branch at *target*, and on origin too when asked."""
    branch = current_branch()
    allowed, reason = can_go_back(branch)
    if not allowed:
        bp.logger.log("red", reason)
        return False
    before = branch_heads()
    head = before.get(branch, "")
    bp.logger.log("white", _("{0}: from {1} to {2}").format(branch, short(head), short(target)))
    ok, detail = _move_branch(branch, head, target)
    if not ok:
        bp.logger.log("red", _("Could not move {0}: {1}").format(branch, detail))
        bp.logger.log("yellow", _("If Git mentions local changes, commit or stash them and try again."))
        return False
    pushes = ()
    remote_failed = False
    on_origin = remote_head(branch)
    if include_remote and on_origin and on_origin != target:
        bp.logger.log("white", _("origin/{0}: from {1} to {2}").format(branch, short(on_origin), short(target)))
        ok, detail = _republish(branch, on_origin, target)
        if ok:
            pushes = (RefMove(branch, on_origin, target),)
        else:
            remote_failed = True
            bp.logger.log("red", _("GitHub was not changed: {0}").format(detail))
    # Recorded even when GitHub refused: the local move happened and must stay undoable.
    record(_("Go back to {0}").format(short(target)), before, pushes)
    bp.logger.log("green", _("{0} now points at {1}.").format(branch, short(target)))
    return not remote_failed


def preview_text(preview: Preview, *, include_remote: bool = True) -> str:
    """Plain text of a preview for the terminal and for StructuredConfirmation."""
    lines = [preview.heading, preview.summary]
    for tone, text in preview.notices:
        lines.append(("⚠ " if tone == "warning" else "") + text)
    for step in preview.steps:
        lines.append(f"• {step.text}")
        if step.command:
            lines.append(step.command)
    if preview.files:
        lines.append(f"{preview.files_title}:")
        labels = {"A": _("added"), "M": _("modified"), "D": _("deleted"), "R": _("renamed"), "C": _("copied")}
        lines.extend(f"• {labels.get(change.status, change.status)}: {change.path}" for change in preview.files[:40])
        if len(preview.files) > 40:
            lines.append(_("… and {0} more").format(len(preview.files) - 40))
    if include_remote and preview.remote_steps:
        lines.append(f"{preview.remote_title}:")
        for step in preview.remote_steps:
            lines.append(f"• {step.text}")
            lines.append(step.command)
    return "\n".join(line for line in lines if line)
