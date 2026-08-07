# intentional-log: CLI startup and fallback failures are user-facing output.
#
# cli/main_cli.py - Entry point for CLI interface
#

import sys
import traceback
from rich.console import Console

from gitrepo.build_package.cli.cli_menu import MenuSystem
from gitrepo.build_package.core.build_package import BuildPackage, parse_arguments, print_version
from gitrepo.build_package.core.config import APP_DESC, APP_NAME, LOG_DIR_BASE
from gitrepo.common.rich_logger import RichLogger
from gitrepo.common.translation import _


def main():
    """Main entry point of the CLI application"""

    console = Console()

    try:
        # Create CLI-specific logger and menu system
        logger = RichLogger(APP_NAME, APP_DESC, LOG_DIR_BASE)
        menu = MenuSystem(logger)

        # Only the terminal entry point owns process arguments.
        args = parse_arguments()
        if args.version:
            print_version()
            return

        build_package = BuildPackage(logger=logger, menu_system=menu, args=args)
        build_package.run()

    except KeyboardInterrupt:
        console.print("\n[yellow]" + _("Operation cancelled by user.") + "[/]")
        sys.exit(1)
    except Exception as e:
        console.print("[red]" + _("Unhandled error: {0}").format(e) + "[/]")
        traceback.print_exc()  # Added for better debugging
        sys.exit(1)


if __name__ == "__main__":
    main()
