# intentional-log: this CLI owner renders prompts, help, and summaries to stdout.
#
# build_package.py - Main class for package management

import argparse
import shutil
from datetime import datetime

from gitrepo.common import child_process as subprocess
from rich.console import Console
from rich.prompt import Prompt

from gitrepo.common.version_display import print_version_panel

from .config import APP_DESC, APP_NAME, APP_VERSION, DEFAULT_ORGANIZATION, VALID_BRANCHES, VALID_ORGANIZATIONS
from .conflict_resolver import ConflictResolver
from .git_utils import GitUtils
from .github_api import GitHubAPI
from .settings import Settings
from .settings_menu import SettingsMenu
from gitrepo.common.translation import _


class BuildPackage:
    """Main class for package management"""

    def __init__(self, logger=None, menu_system=None, args=None):
        # Parsing process arguments here would let an argument the desktop
        # passed to the GUI abort the window during construction. The CLI owns
        # argv; every other caller gets the documented defaults.
        self.args = args if args is not None else parse_arguments([])
        self.logger = logger
        self.menu = menu_system
        self.organization = self.args.organization or DEFAULT_ORGANIZATION
        self.repo_workflow = f"{self.organization}/build-package"
        self.console = Console()  # Add console object for colorful prompts
        self.last_commit_type = None
        self._app_version_cache = None
        self._app_version_warning_shown = False

        # Check if it's a Git repository
        self.is_git_repo = GitUtils.is_git_repo()

        # Setup logger if provided
        if self.logger:
            self.logger.setup_log_file(GitUtils.get_repo_name)
            self.logger.draw_app_header()

        # Initialize settings and intelligent systems
        self.settings = Settings()
        self.conflict_resolver = None  # Initialize after menu is ready
        self.settings_menu = None

        # Apply --dry-run if provided
        if self.args.dry_run:
            self.dry_run_mode = True
            if self.logger:
                self.logger.log("yellow", _("🔍 DRY-RUN MODE: No operations will be executed"))
        else:
            self.dry_run_mode = False

        # Configure environment
        self.setup_environment()

        # Initialize conflict resolver with menu system
        if self.menu:
            conflict_strategy = self.settings.get("conflict_strategy", "interactive")
            self.conflict_resolver = ConflictResolver(self.logger, self.menu, conflict_strategy)
            self.settings_menu = SettingsMenu(self.settings, self.logger, self.menu)

    def setup_environment(self):
        """Configures the execution environment"""
        # Try to get GitHub token (optional - not required for basic Git operations)
        # Basic Git operations (commit, push, pull, branches) work without a token.
        # The token is only needed for GitHub API operations (package generation,
        # PR creation, workflow triggers).
        # Credential lookup is deferred until an API operation. GUI callers
        # perform that lookup in a worker so libsecret never blocks GTK startup.
        self.github_api = GitHubAPI(None, self.organization)

        # Additional settings
        self.github_user_name = GitUtils.get_github_username()
        self.repo_name = GitUtils.get_repo_name()
        self.repo_path = GitUtils.get_repo_root_path()
        self.tmate_option = self.args.tmate

        # Check dependencies
        self.check_dependencies()

    def check_dependencies(self):
        """Checks if all dependencies are installed"""
        dependencies = ["git"]

        for dep in dependencies:
            if shutil.which(dep) is None:
                self.logger.die(
                    "red", _("Dependency '{0}' not found. Please install it before continuing.").format(dep)
                )

    def get_commit_types(self):
        """Returns available commit types with emojis and descriptions"""
        return [
            ("✨", "feat", _("A new feature")),
            ("🐛", "fix", _("A bug fix")),
            ("📚", "docs", _("Documentation only changes")),
            ("💎", "style", _("Changes that do not affect the meaning of the code")),
            ("🔨", "refactor", _("A code change that neither fixes a bug nor adds a feature")),
            ("🚀", "perf", _("A code change that improves performance")),
            ("🚨", "test", _("Adding missing tests or correcting existing tests")),
            ("📦", "build", _("Changes that affect the build system or external dependencies")),
            ("👷", "ci", _("Changes to CI configuration files and scripts")),
            ("🔧", "chore", _("Other changes that don't modify src or test files")),
            ("✏️", "custom", _("Custom commit message (free text)")),
        ]

    def show_commit_type_menu(self):
        """Shows interactive menu for commit type selection"""
        commit_types = self.get_commit_types()

        # Create menu options
        options = []
        for emoji, commit_type, description in commit_types:
            if commit_type == "custom":
                options.append(f"{emoji} {commit_type}: {description}")
            else:
                options.append(f"{emoji} {commit_type}: {description}")

        # Show menu
        result = self.menu.show_menu(_("Select commit type"), options)

        if result is None:
            return None, None

        choice_index = result[0]
        emoji, commit_type, description = commit_types[choice_index]

        return emoji, commit_type

    def get_commit_message_with_type(self):
        """Gets commit message with type selection"""
        # Step 1: Select commit type
        emoji, commit_type = self.show_commit_type_menu()

        if emoji is None or commit_type is None:
            self.last_commit_type = None
            return None

        # Step 2: Get commit description
        if commit_type == "custom":
            # For custom, allow free text
            self.console.print("", style="cyan")
            self.console.print(_("Enter your custom commit message:"), style="cyan")
            print("\033[1;36m> \033[0m", end="")
            description = input()

            if not description:
                self.last_commit_type = None
                return None

            self.last_commit_type = None
            return description
        else:
            # For conventional commits, get description
            self.console.print("", style="cyan")
            self.console.print(_("{0} {1}: Enter description").format(emoji, commit_type), style="cyan")
            print(f"\033[1;36m{emoji} {commit_type}: \033[0m", end="")
            description = input()

            if not description:
                self.last_commit_type = None
                return None

            self.last_commit_type = commit_type
            return f"{emoji} {commit_type}: {description}"

    def custom_commit_prompt(self):
        """Gets commit message from user with type selection"""
        return self.get_commit_message_with_type()

    def apply_auto_version_bump(self, commit_message, explicit_type=None):
        """Automatically bumps APP_VERSION based on commit metadata."""
        from .version_bumper import apply_auto_version_bump as _bump

        return _bump(self, commit_message, explicit_type)

    def build_aur_package(self):
        """Triggers workflow to build an AUR package"""
        # Ensure GitHub token is available (required for triggering workflows)
        if not self.github_api.ensure_github_token(self.logger):
            self.logger.log("red", _("✗ Cannot build AUR package without a GitHub token."))
            return False

        aur_package_name = self.args.aur
        if not aur_package_name:
            self.logger.log("purple", _("Enter the AUR package name (ex: showtime): type EXIT to exit"))
            while True:
                aur_package_name = Prompt.ask("> ")
                aur_package_name = aur_package_name.replace("aur-", "").replace("aur/", "")

                if aur_package_name.upper() == "EXIT":
                    self.logger.log("yellow", _("Exiting script. No action was performed."))
                    return False
                elif not aur_package_name:
                    self.logger.log("red", _("Error: No package name was entered."))
                    continue
                break

        # Summary of choices for AUR
        self.show_aur_summary(aur_package_name)

        # Detect if running in GUI mode (confirmation already done by GTK dialog)
        is_gui_mode = hasattr(self.menu, "__class__") and "GTK" in self.menu.__class__.__name__

        # In CLI mode, ask for confirmation; in GUI mode, skip (already confirmed)
        if not is_gui_mode:
            if not self.menu.confirm(_("Do you want to proceed with building the PACKAGE?")):
                self.logger.log("red", _("Package build cancelled."))
                return False

        self.logger.log("cyan", _("Starting AUR package build..."))

        # AUR builds don't need local branches - they just trigger the GitHub workflow
        # The aur-build workflow clones the AUR package directly from aur.archlinux.org

        # Trigger workflow (no branch needed for AUR)
        return self.github_api.trigger_workflow(aur_package_name, "aur", "", True, self.tmate_option, self.logger)

    def show_aur_summary(self, aur_package_name: str):
        """Shows a summary of choices for AUR package build using Rich"""
        aur_url = f"https://aur.archlinux.org/{aur_package_name}.git"
        timestamp = datetime.now().strftime("%y.%m.%d-%H%M")

        data = [
            (_("Organization"), self.organization),
            (_("Repo Workflow"), self.repo_workflow),
            (_("User Name"), self.github_user_name),
            (_("Package AUR Name"), aur_package_name),
            (_("Branch_type"), f"aur-{timestamp}"),
            (_("New Branch"), f"aur-{timestamp}"),
            (_("Url"), aur_url),
            (_("TMATE Debug"), str(self.tmate_option)),
        ]

        self.logger.display_summary(_("AUR - Summary of Choices"), data)

    def _main_menu_entries(self):
        entries = []
        if self.is_git_repo:
            entries.extend([(_("Download updates"), "pull"), (_("Publish changes"), "commit")])
            if self.settings.get("package_features_enabled", False):
                entries.append((_("Build package"), "package"))
        if self.settings.get("aur_features_enabled", False):
            entries.append((_("Build from the AUR"), "aur"))
        entries.append((_("Settings"), "settings"))
        if self.is_git_repo:
            entries.append((_("Repository maintenance"), "advanced"))
        entries.append((_("Exit"), "exit"))
        return entries

    def _menu_pull(self):
        from .pull_operations import pull_latest

        pull_latest(self)
        return False

    def _menu_commit(self):
        from .commit_operations import commit_and_push

        commit_and_push(self)
        return True

    def _menu_package(self):
        branch_options = ["testing", "stable", "extra", _("Back")]
        branch_result = self.menu.show_menu(_("Select repository"), branch_options)
        if branch_result is None or branch_options[branch_result[0]] == _("Back"):
            return False
        debug_result = self.menu.show_menu(_("Enable TMATE debug session?"), [_("No"), _("Yes")])
        if debug_result is None:
            return False
        message = self.custom_commit_prompt() if GitUtils.has_changes() else None
        if GitUtils.has_changes() and not message:
            self.logger.log("red", _("Commit message cannot be empty."))
            return False
        from .package_operations import commit_and_generate_package

        commit_and_generate_package(self, branch_options[branch_result[0]], message, debug_result[0] == 1)
        return True

    def _menu_aur(self):
        debug_result = self.menu.show_menu(_("Enable TMATE debug session?"), [_("No"), _("Yes")])
        if debug_result is None:
            return False
        self.tmate_option = debug_result[0] == 1
        self.args.aur = None
        self.build_aur_package()
        return True

    def _menu_settings(self):
        if self.settings_menu:
            self.settings_menu.show()
        return False

    def _menu_advanced(self):
        self.advanced_menu()
        return False

    def _menu_exit(self):
        self.logger.log("yellow", _("Exiting script. No action was performed."))
        return True

    def main_menu(self):
        """Display the capability-aware menu and dispatch one semantic action."""
        handlers = {
            "pull": self._menu_pull,
            "commit": self._menu_commit,
            "package": self._menu_package,
            "aur": self._menu_aur,
            "settings": self._menu_settings,
            "advanced": self._menu_advanced,
            "exit": self._menu_exit,
        }
        while True:
            entries = self._main_menu_entries()
            result = self.menu.show_menu(_("Main Menu"), [label for label, _action in entries])
            if result is None:
                return
            action = entries[result[0]][1]
            if handlers[action]():
                return

    def advanced_menu(self):
        """Displays advanced options menu"""
        options = [
            _("Delete branches (except main and latest)"),
            _("Delete failed Action jobs"),
            _("Delete successful Action jobs"),
            _("Delete all tags"),
            _("Merge branch to main"),
            _("Revert commit"),
            _("Back"),
        ]

        while True:
            result = self.menu.show_menu(_("Advanced Menu"), options)
            if result is None or result[0] == 6:  # None ou "Back"
                return

            choice = result[0]

            if choice == 0:  # Delete branches
                GitUtils.cleanup_old_branches(self.logger, self.menu)

            elif choice == 1:  # Delete failed Action jobs
                self.github_api.clean_action_jobs("failure", self.logger, self.menu)

            elif choice == 2:  # Delete successful Action jobs
                self.github_api.clean_action_jobs("success", self.logger, self.menu)

            elif choice == 3:  # Delete tags
                self.github_api.clean_all_tags(self.logger, self.menu)

            elif choice == 4:  # Merge branch to main
                self.merge_branch_menu()

            elif choice == 5:  # Revert commit
                self.revert_commit_menu()

    def merge_branch_menu(self):
        """Displays menu for merging branches to main"""
        if not self.is_git_repo:
            self.logger.log("red", _("This operation is only available in git repositories."))
            return

        # Fetch the latest list of branches first
        subprocess.run_git(["git", "fetch", "--all", "--prune"], check=True, intent="ordinary")

        # Get available branches
        try:
            # Get all branches
            result = subprocess.run_git(
                ["git", "branch", "-r"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                intent="ordinary",
            )

            branches = []
            for line in result.stdout.strip().split("\n"):
                branch = line.strip().replace("origin/", "")
                # Filter only testing and stable branches
                if branch.startswith(("dev-")) and branch != "HEAD":
                    branches.append(branch)

            if not branches:
                self.logger.log("yellow", _("No dev branches found to merge."))
                return

            # Sort branches by date (newest first)
            branches.sort(reverse=True)

            # Add a Back option
            branches.append(_("Back"))

            # Show branch selection menu
            branch_result = self.menu.show_menu(_("Select branch to merge to main"), branches)
            if branch_result is None or branches[branch_result[0]] == _("Back"):
                return

            selected_branch = branches[branch_result[0]]

            # Ask if should auto-merge
            merge_options = [_("Create PR (manual approval)"), _("Create PR and auto-merge")]
            merge_result = self.menu.show_menu(_("Select merge option"), merge_options)
            if merge_result is None:
                return

            auto_merge = merge_result[0] == 1  # True if "Create PR and auto-merge" is selected

            # Show summary
            data = [
                (_("Source Branch"), selected_branch),
                (_("Target Branch"), "main"),
                (_("Auto-merge"), _("Yes") if auto_merge else _("No")),
            ]

            self.logger.display_summary(_("Merge Summary"), data)

            # Confirm action
            if not self.menu.confirm(_("Do you want to proceed with creating the pull request?")):
                self.logger.log("yellow", _("Operation cancelled by user."))
                return

            # Create pull request
            pr_info = self.github_api.create_pull_request(selected_branch, "main", auto_merge, self.logger)

            if pr_info:
                self.logger.log("green", _("Pull request operation completed."))

        except (subprocess.SubprocessError, ValueError) as error:
            self.logger.log("red", _("Could not prepare the merge request: {0}").format(error))

    def revert_commit_menu(self):
        """Display menu for reverting / resetting commits."""
        from .revert_operations import revert_commit_menu as _revert

        _revert(self)

    def run(self):
        """Executes main program flow"""
        # Check command line arguments
        if self.args.commit and not self.args.build:
            from .commit_operations import commit_and_push

            commit_and_push(self)

        elif self.args.build:
            from .package_operations import commit_and_generate_package

            commit_and_generate_package(self, self.args.build, self.args.commit, self.args.tmate)

        elif self.args.aur:
            # Build AUR package
            self.build_aur_package()

        else:
            # No specific argument, show interactive menu
            self.main_menu()


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments with standard, scriptable help."""
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} v{APP_VERSION} - {APP_DESC}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "-o",
        "--org",
        "--organization",
        dest="organization",
        help=_("Configure GitHub organization (default: big-comm)"),
        choices=VALID_ORGANIZATIONS,
        default=DEFAULT_ORGANIZATION,
    )

    parser.add_argument("-b", "--build", help=_("Commit/push and generate package"), choices=VALID_BRANCHES)

    parser.add_argument("-c", "--commit", help=_("Just commit/push with the specified message"))

    parser.add_argument("-F", "--commit-file", help=_("Read commit message from file (multi-line support)"))

    parser.add_argument("-a", "--aur", help=_("Build AUR package"))

    parser.add_argument("-n", "--nocolor", action="store_true", help=_("Suppress color printing"))

    parser.add_argument("-V", "--version", action="store_true", help=_("Print application version"))

    parser.add_argument("-t", "--tmate", action="store_true", help=_("Enable tmate for debugging"))

    parser.add_argument("--dry-run", action="store_true", help=_("Simulate operations without executing"))

    return parser.parse_args(argv)


def print_version() -> None:
    """Print the localized application version and license notice."""
    print_version_panel(
        Console(),
        app_name=APP_NAME,
        app_version=APP_VERSION,
        app_description=APP_DESC,
    )
