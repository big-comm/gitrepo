"""The GUI entry points must carry the same guards as the interactive menus."""

import os
from types import SimpleNamespace

import pytest

from gitrepo.build_package.core.conflict_resolver import ConflictResolver
from gitrepo.build_package.core.revert_operations import _branch_allows_revert


def _bp(user="bruno"):
    logged = []
    return (
        SimpleNamespace(
            logger=SimpleNamespace(log=lambda style, message: logged.append(style)),
            github_user_name=user,
        ),
        logged,
    )


@pytest.mark.parametrize(
    ("branch", "method", "allowed"),
    [
        ("main", "revert", True),
        # Shared main takes only the history-preserving method.
        ("main", "reset", False),
        ("dev-bruno", "revert", True),
        ("dev-bruno", "reset", True),
        # Someone else's branch, and anything unowned, is refused outright.
        ("dev-someone", "revert", False),
        ("dev-someone", "reset", False),
        ("feature-x", "reset", False),
    ],
)
def test_revert_is_limited_to_main_and_the_user_branch(branch, method, allowed):
    bp, logged = _bp()

    assert _branch_allows_revert(bp, branch, method) is allowed
    assert logged == ([] if allowed else ["red"])


def _resolver(root):
    resolver = ConflictResolver(logger=None, menu_system=None)
    resolver.repo_root = str(root)
    return resolver


def test_an_existing_companion_file_is_never_overwritten(tmp_path):
    # The dialog used to `shutil.copy` onto file.ours, destroying a copy the
    # user had made themselves, with no git object to recover it from.
    precious = tmp_path / "f.ours"
    precious.write_text("the user's own copy", encoding="utf-8")

    candidate, descriptor = _resolver(tmp_path)._reserve_companion(str(tmp_path / "f"), "ours")
    os.close(descriptor)

    assert os.path.basename(candidate) == "f.ours.1"
    assert precious.read_text(encoding="utf-8") == "the user's own copy"


def test_a_symlinked_companion_is_not_followed(tmp_path):
    target = tmp_path / "outside"
    target.write_text("must not be written", encoding="utf-8")
    (tmp_path / "f.theirs").symlink_to(target)

    candidate, descriptor = _resolver(tmp_path)._reserve_companion(str(tmp_path / "f"), "theirs")
    os.close(descriptor)

    assert os.path.basename(candidate) == "f.theirs.1"
    assert target.read_text(encoding="utf-8") == "must not be written"
    assert (tmp_path / "f.theirs").is_symlink()


def test_the_dialog_writes_companions_through_the_core_resolver():
    from gitrepo.build_package.gui.dialogs import conflict_dialog

    with open(conflict_dialog.__file__, "r", encoding="utf-8") as stream:
        text = stream.read()

    assert "_write_index_stage(" in text
    # shutil.copy followed symlinks and clobbered existing names.
    assert "shutil.copy" not in text
