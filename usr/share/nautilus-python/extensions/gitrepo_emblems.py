"""Repository-root emblems for Nautilus."""

import sys
from pathlib import Path

import gi

gi.require_version("Nautilus", "4.1")
from gi.repository import GObject, Nautilus

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from gitrepo.file_manager import nautilus_css
from gitrepo.file_manager.emblems import EmblemProvider


class GitRepoEmblems(GObject.GObject, Nautilus.InfoProvider):
    def __init__(self):
        super().__init__()
        # Only the public InfoProvider API plus one global CSS provider are
        # used here. Reaching into Nautilus widgets from Python (the former
        # nautilus_style.py) kept GTK objects alive via Python wrappers and
        # crashed Nautilus on cell recycling.
        self._css = nautilus_css.install()
        self._emblems = EmblemProvider()

    def update_file_info(self, file_info):
        self._emblems.update(file_info)
        return Nautilus.OperationResult.COMPLETE
