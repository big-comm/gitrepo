"""Repository-root emblems for Nemo."""

import sys
from pathlib import Path

import gi

gi.require_version("Nemo", "3.0")
from gi.repository import GObject, Nemo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from gitrepo.file_manager.emblems import EmblemProvider


class GitRepoEmblems(GObject.GObject, Nemo.InfoProvider):
    def __init__(self):
        super().__init__()
        self._emblems = EmblemProvider()

    def update_file_info(self, file_info):
        self._emblems.update(file_info)
        return Nemo.OperationResult.COMPLETE
