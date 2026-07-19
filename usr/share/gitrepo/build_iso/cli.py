"""Command-line entrypoint for Build ISO."""

from __future__ import annotations

import sys
import traceback
from types import TracebackType

from rich.console import Console

from gitrepo.build_iso.build_iso import BuildISO
from gitrepo.common.translation import _


def debug_hook(
    exception_type: type[BaseException], value: BaseException, traceback_object: TracebackType | None
) -> None:
    """Print an uncaught exception with its translated heading."""
    print("\n" + _("DETAILED ERROR:"))
    traceback.print_exception(exception_type, value, traceback_object)
    print("\n")


sys.excepthook = debug_hook


def main() -> int:
    """Run the Build ISO command-line interface."""
    console = Console()

    try:
        BuildISO().run()
    except KeyboardInterrupt:
        console.print(_("Operation cancelled by user."), style="yellow")
        return 1
    except Exception as error:
        console.print(_("Unhandled error: {0}").format(str(error)), style="red", markup=False)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
