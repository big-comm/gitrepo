#
# core/package_selection.py - Which packages of a multi-package repository to build
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#
# Shared by the GTK dialog and the terminal menu, so both count, order and
# warn the same way. Nothing here touches GTK: the package is built without
# a display, where constructing a widget segfaults inside pango.
#

from dataclasses import dataclass

from gitrepo.common.translation import _
from .git_utils import GitUtils


@dataclass(frozen=True)
class PackageChoice:
    """One package directory offered for building, as the repository names it."""

    directory: str
    description: str = ""


def main_package(directories: list[str], repo_name: str = "") -> str:
    """Return the package the others build against, or "" when there is none.

    It is the one named after the repository, or the one every other
    directory extends: linux-big is the prefix of each linux-big-* module,
    which is built against the linux-big-headers it publishes.
    """
    repository = repo_name.rsplit("/", 1)[-1]
    if repository in directories:
        return repository
    for candidate in directories:
        if all(other == candidate or other.startswith(f"{candidate}-") for other in directories):
            return candidate
    return ""


def ordered_directories(directories: list[str], main: str) -> list[str]:
    """Put the main package first and the rest in alphabetical order."""
    rest = sorted(directory for directory in directories if directory != main)
    return [main, *rest] if main in directories else rest


def package_choices(directories: list[str]) -> tuple[list[PackageChoice], str]:
    """Describe each package directory in display order, and name the main one."""
    main = main_package(directories, GitUtils.get_repo_name() or "")
    choices = [
        PackageChoice(directory, GitUtils.read_package_description(directory))
        for directory in ordered_directories(directories, main)
    ]
    return choices, main


class PackageSelection:
    """Which of the offered packages are marked, and what that implies."""

    def __init__(self, choices: list[PackageChoice], main: str = ""):
        self.choices = list(choices)
        self.main = main if any(choice.directory == main for choice in self.choices) else ""
        self._selected: set[str] = set()

    def is_selected(self, directory: str) -> bool:
        return directory in self._selected

    def set_selected(self, directory: str, selected: bool) -> None:
        if not any(choice.directory == directory for choice in self.choices):
            return
        if selected:
            self._selected.add(directory)
        else:
            self._selected.discard(directory)

    def toggle(self, directory: str) -> None:
        self.set_selected(directory, not self.is_selected(directory))

    def select_all(self) -> None:
        self._selected = {choice.directory for choice in self.choices}

    def clear(self) -> None:
        self._selected.clear()

    def selected_directories(self) -> list[str]:
        """Return the marked directories in display order, main package first."""
        return [choice.directory for choice in self.choices if choice.directory in self._selected]

    @property
    def can_confirm(self) -> bool:
        return bool(self._selected)

    def count_text(self) -> str:
        return _("{0} of {1} selected").format(len(self._selected), len(self.choices))

    @property
    def needs_order_warning(self) -> bool:
        """True when the main package is marked together with packages that build against it."""
        return bool(self.main) and self.main in self._selected and len(self._selected) > 1

    def order_warning_text(self) -> str:
        return _(
            "The other packages build against the {0} headers that are already published. "
            "Built together, they compile against the previous version: build {0} first, "
            "and the others once it is published."
        ).format(self.main)

    def only_main_label(self) -> str:
        return _("Build only {0}").format(self.main)
