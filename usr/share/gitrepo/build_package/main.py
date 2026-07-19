"""Start the Build Package interface directly from a source checkout."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import NoReturn

GUI_MODULE = "gitrepo.build_package.gui.main_gui"


def main() -> NoReturn:
    """Replace this process with the canonical GTK entrypoint."""
    share_dir = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, (str(share_dir), environment.get("PYTHONPATH"))))
    os.execve(sys.executable, [sys.executable, "-m", GUI_MODULE, *sys.argv[1:]], environment)


if __name__ == "__main__":
    main()
