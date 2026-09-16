"""Repository-root emblems for Nautilus."""

import sys
from pathlib import Path

import gi

gi.require_version("Nautilus", "4.1")
from gi.repository import GObject, Nautilus

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from gitrepo.file_manager.emblems import EmblemProvider
from gitrepo.file_manager.nautilus_style import EmblemStyle


class GitRepoEmblems(GObject.GObject, Nautilus.InfoProvider):
    def __init__(self):
        super().__init__()
        self._style = EmblemStyle()
        self._emblems = EmblemProvider(on_changed=self._style.schedule)

    def update_file_info(self, file_info):
        self._emblems.update(file_info)
        return Nautilus.OperationResult.COMPLETE
