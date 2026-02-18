#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# build_package.py - Main class for package management

import argparse
import subprocess
import sys
from datetime import datetime

from rich.console import Console
from rich.prompt import Prompt

from .config import APP_DESC, APP_NAME, APP_VERSION, DEFAULT_ORGANIZATION, VALID_BRANCHES, VALID_ORGANIZATIONS
from .conflict_resolver import ConflictResolver
from .git_utils import GitUtils
from .github_api import GitHubAPI
from .settings import Settings
from .settings_menu import SettingsMenu
from .translation_utils import _


class BuildPackage:
    """Main class for package management"""

    def __init__(self, logger=None, menu_system=None):
        self.args = self.parse_arguments()
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

        # Apply --mode argument if provided
        if self.args.mode:
            self.settings.set("operation_mode", self.args.mode)
            if self.logger:
                self.logger.log("cyan", _("Operation mode set to: {0}").format(self.args.mode))

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
        token = GitHubAPI(None, self.organization).get_github_token_optional()
        self.github_api = GitHubAPI(token, self.organization)

        # Additional settings
        self.github_user_name = GitUtils.get_github_username()
        self.repo_name = GitUtils.get_repo_name()
        self.repo_path = GitUtils.get_repo_root_path()
        self.is_aur_package = False
        self.tmate_option = self.args.tmate

        # Check dependencies
        self.check_dependencies()

    def check_dependencies(self):
        """Checks if all dependencies are installed"""
        dependencies = ["git", "curl"]

        for dep in dependencies:
            try:
                subprocess.run(["which", dep], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError:
                self.logger.die(
                    "red", _("Dependency '{0}' not found. Please install it before continuing.").format(dep)
                )

    def parse_arguments(self) -> argparse.Namespace:
        """Parses command line arguments with colored help"""

        # Custom help action that shows colored help
        class ColoredHelpAction(argparse.Action):
            def __init__(self, option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, help=None):
                super().__init__(option_strings=option_strings, dest=dest, default=default, nargs=0, help=help)

            def __call__(self, parser, namespace, values, option_string=None):
                from rich.box import ROUNDED
                from rich.console import Console
                from rich.panel import Panel
                from rich.table import Table
                from rich.text import Text

                console = Console()

                # Header - compact version like main menu
                header = Text()
                header.append(f"{APP_NAME} ", style="bold cyan")
                header.append(f"v{APP_VERSION}\n", style="bold white")
                header.append(f"{APP_DESC}", style="white")

                console.print(
                    Panel(
                        header,
                        border_style="cyan",
                        box=ROUNDED,
                        padding=(0, 1),
                        title="BigCommunity",
                        width=70,  # Fixed width like other menus
                    )
                )
                console.print()

                # Usage
                console.print("[bold yellow]USAGE:[/]")
                console.print("  [cyan]python main.py[/] [dim]\\[OPTIONS][/]\n")

                # Interface Mode Flags (special flags processed before argparse)
                console.print("[bold yellow]INTERFACE MODE:[/]")
                table_interface = Table(show_header=False, box=None, padding=(0, 2))
                table_interface.add_column(style="green bold", no_wrap=True)
                table_interface.add_column(style="white")

                table_interface.add_row("--cli, --no-gui", _("Force CLI mode (terminal interface)"))
                table_interface.add_row("--gui", _("Force GUI mode (graphical interface)"))
                console.print(table_interface)
                console.print()

                # Main Options
                console.print("[bold yellow]OPTIONS:[/]")
                table = Table(show_header=False, box=None, padding=(0, 2))
                table.add_column(style="green bold", no_wrap=True)
                table.add_column(style="white")

                table.add_row("-h, --help", _("Show this help message and exit"))
                table.add_row("-V, --version", _("Print application version"))
                table.add_row(
                    "-o, --org, --organization",
                    _("Configure GitHub organization")
                    + " [dim](default: big-comm)[/]\n"
                    + _("Choices: {big-comm, biglinux}"),
                )
                table.add_row("-b, --build {dev}", _("Commit/push and generate package"))
                table.add_row("-c, --commit MSG", _("Just commit/push with the specified message"))
                table.add_row("-F, --commit-file FILE", _("Read commit message from file (multi-line support)"))
                table.add_row("-a, --aur PACKAGE", _("Build AUR package"))
                table.add_row("-t, --tmate", _("Enable tmate for debugging"))
                table.add_row("-n, --nocolor", _("Suppress color printing"))

                console.print(table)
                console.print()

                # Examples
                console.print("[bold yellow]EXAMPLES:[/]")
                examples = [
                    ("python main.py --cli", _("Open in CLI mode")),
                    ("python main.py --gui", _("Open in GUI mode")),
                    ('python main.py -c "fix: bug fix"', _("Quick commit with message")),
                    ("python main.py -F commit_msg.txt", _("Commit with message from file")),
                    ('python main.py -b dev -c "feat: new feature"', _("Build development package")),
                    ("python main.py -a package-name", _("Build AUR package")),
                ]

                for cmd, desc in examples:
                    console.print(f"  [cyan]{cmd}[/]")
                    console.print(f"    [dim]{desc}[/]\n")

                # Footer
                console.print("[dim]For more information, visit: https://github.com/big-comm[/]")

                parser.exit()

        parser = argparse.ArgumentParser(
            description=f"{APP_NAME} v{APP_VERSION} - {APP_DESC}",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            add_help=False,  # Disable default help to use custom one
        )

        # Add custom help
        parser.add_argument("-h", "--help", action=ColoredHelpAction, help=_("Show this help message and exit"))

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

        parser.add_argument(
            "--mode",
            choices=["safe", "quick", "expert"],
            help=_("Operation mode: safe (default), quick (fast), expert (max automation)"),
        )

        parser.add_argument("--dry-run", action="store_true", help=_("Simulate operations without executing"))

        args = parser.parse_args()

        if args.version:
            self.print_version()
            sys.exit(0)

        return args

    def print_version(self):
        """Prints application version"""
        console = Console()
        from rich.box import ROUNDED
        from rich.panel import Panel
        from rich.text import Text

        version_text = Text()
        version_text.append(f"{APP_NAME} v{APP_VERSION}\n", style="bold cyan")
        version_text.append(f"{APP_DESC}\n\n", style="white")
        version_text.append(_("Copyright (C) 2024-2025 BigCommunity Team\n\n"), style="blue")
        version_text.append(_("""This is free software: you are free to modify and redistribute it."""), style="white")
        version_text.append("\n", style="white")
        version_text.append(f"{APP_NAME}", style="cyan")
        version_text.append(_(" is provided to you under the "), style="white")
        version_text.append(_("MIT License"), style="yellow")
        version_text.append(
            _(""", and includes open source software under a variety of other licenses.
You can read instructions about how to download and build for yourself
the specific source code used to create this copy."""),
            style="white",
        )
        version_text.append("\n", style="white")
        version_text.append(_("This program comes with absolutely NO warranty."), style="red")

        panel = Panel(version_text, box=ROUNDED, border_style="blue", padding=(1, 2))

        console.print(panel)

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

        choice_index, selected_option = result
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


    def ensure_user_branch_exists(self, branch_name: str):
        """Creates user branch if it doesn't exist, or switches to it if it does"""
        try:
            # Check if there are local changes that need to be stashed
            has_changes = GitUtils.has_changes()
            stashed = False
            
            if has_changes:
                self.logger.log("cyan", _("Stashing local changes before branch switch..."))
                stash_result = subprocess.run(
                    ["git", "stash", "push", "-m", f"auto-stash-before-switch-to-{branch_name}"],
                    capture_output=True, text=True, check=False
                )
                stashed = stash_result.returncode == 0
                
                if not stashed:
                    self.logger.log("red", _("Failed to stash changes before branch switch."))
                    return False
            
            # Check if branch exists locally
            local_result = subprocess.run(
                ["git", "rev-parse", "--verify", branch_name],
                capture_output=True, check=False
            )
            
            # Check if branch exists remotely  
            remote_result = subprocess.run(
                ["git", "rev-parse", "--verify", f"origin/{branch_name}"],
                capture_output=True, check=False
            )
            
            if remote_result.returncode == 0:
                # Branch exists remotely, checkout/switch to it
                self.logger.log("cyan", _("Switching to existing branch: {0}").format(branch_name))
                subprocess.run(["git", "checkout", branch_name], check=True)
            elif local_result.returncode == 0:
                # Branch exists locally only, push it
                self.logger.log("cyan", _("Using existing local branch: {0}").format(branch_name))
                subprocess.run(["git", "checkout", branch_name], check=True)
                subprocess.run(["git", "push", "-u", "origin", branch_name], check=True)
            else:
                # Branch doesn't exist, create it
                self.logger.log("cyan", _("Creating new branch: {0}").format(branch_name))
                subprocess.run(["git", "checkout", "-b", branch_name], check=True)
            
            # Restore stashed changes if any
            if stashed:
                self.logger.log("cyan", _("Restoring stashed changes..."))
                pop_result = subprocess.run(["git", "stash", "pop"], capture_output=True, text=True, check=False)
                if pop_result.returncode != 0:
                    self.logger.log("yellow", _("Could not restore stashed changes automatically. Check 'git stash list'"))
                else:
                    self.logger.log("green", _("Stashed changes restored successfully"))
                
            return True
        except subprocess.CalledProcessError as e:
            self.logger.log("red", _("Error with user branch: {0}").format(e))
            return False
        
    def ensure_working_in_own_branch(self, preserve_changes=True):
        """Ensures user is working in their own dev branch, preserving changes if needed"""
        username = self.github_user_name or "unknown"
        my_branch = f"dev-{username}"
        current_branch = GitUtils.get_current_branch()
        
        if current_branch == my_branch:
            return True  # Already in correct branch
        
        self.logger.log("yellow", _("Moving from {0} to your own branch {1}...").format(
            self.logger.format_branch_name(current_branch), self.logger.format_branch_name(my_branch)))
        
        has_changes = GitUtils.has_changes()
        
        if has_changes and preserve_changes:
            # Stash → Switch → Apply workflow
            stash_message = f"auto-preserve-changes-switch-to-{my_branch}"
            stash_result = subprocess.run(
                ["git", "stash", "push", "-u", "-m", stash_message], 
                capture_output=True, text=True, check=False
            )
            
            if stash_result.returncode != 0:
                self.logger.log("red", _("Failed to stash changes. Cannot proceed safely."))
                return False
            
            # Ensure user's branch exists and switch
            if not self.ensure_user_branch_exists(my_branch):
                return False
            
            # Apply stashed changes
            pop_result = subprocess.run(["git", "stash", "pop"], capture_output=True, text=True, check=False)
            if pop_result.returncode != 0:
                self.logger.log("yellow", _("Conflicts detected while applying changes. Resolving automatically..."))
                try:
                    subprocess.run(["git", "reset", "HEAD"], check=True)
                    subprocess.run(["git", "add", "."], check=True)
                    self.logger.log("green", _("Conflicts resolved automatically"))
                except subprocess.CalledProcessError:
                    self.logger.log("red", _("Could not resolve conflicts automatically."))
                    return False
            
            self.logger.log("green", _("Successfully moved your changes to your own branch!"))
        else:
            # No changes or don't preserve, just switch
            if not self.ensure_user_branch_exists(my_branch):
                return False
            self.logger.log("cyan", _("Switched to your branch: {0}").format(self.logger.format_branch_name(my_branch)))
        
        return True
    
    def ensure_dev_branch_exists(self):
        """Creates the dev branch if it doesn't exist yet"""
        if not self.is_git_repo:
            self.logger.log("red", _("This operation is only available in git repositories."))
            return False
            
        try:
            # Check if dev branch exists locally
            local_branches = subprocess.run(
                ["git", "branch"],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            ).stdout.strip().split('\n')
            
            local_branches = [b.strip('* ') for b in local_branches if b.strip()]
            
            # Check if dev branch exists remotely
            remote_branches = subprocess.run(
                ["git", "branch", "-r"],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            ).stdout.strip().split('\n')
            
            remote_branches = [b.strip().replace('origin/', '') for b in remote_branches if b.strip()]
            
            # If dev branch doesn't exist anywhere, create it
            if 'dev' not in local_branches and 'dev' not in remote_branches:
                self.logger.log("yellow", _("Dev branch doesn't exist. Creating it now..."))
                
                # Check if we have uncommitted changes
                has_changes = GitUtils.has_changes()
                stashed = False
                if has_changes:
                    # Stash changes temporarily
                    self.logger.log("cyan", _("Stashing local changes temporarily..."))
                    try:
                        subprocess.run(["git", "stash"], check=True)
                        # Verify if anything was actually stashed
                        stash_list = subprocess.run(
                            ["git", "stash", "list"],
                            stdout=subprocess.PIPE,
                            text=True,
                            check=True
                        ).stdout.strip()
                        stashed = bool(stash_list)  # True if something was stashed
                        if not stashed:
                            self.logger.log("yellow", _("No local changes were stashed."))
                    except subprocess.CalledProcessError as e:
                        self.logger.log("red", _("Error stashing changes: {0}").format(e))
                        return False
                
                try:
                    # Get current branch
                    current_branch = subprocess.run(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        stdout=subprocess.PIPE,
                        text=True,
                        check=True
                    ).stdout.strip()
                    
                    # Try to checkout main first (only if different from current)
                    if current_branch != "main":
                        subprocess.run(["git", "checkout", "main"], check=True)
                    
                    # Create dev branch from main
                    subprocess.run(["git", "checkout", "-b", "dev"], check=True)
                    subprocess.run(["git", "push", "-u", "origin", "dev"], check=True)
                    
                    # Go back to original branch
                    if current_branch != "main" and current_branch != "dev":
                        subprocess.run(["git", "checkout", current_branch], check=True)
                    
                    # Apply stashed changes only if something was actually stashed
                    if stashed:
                        try:
                            self.logger.log("cyan", _("Applying stashed changes..."))
                            subprocess.run(["git", "stash", "pop"], check=True)
                            self.logger.log("green", _("Stashed changes applied successfully."))
                        except subprocess.CalledProcessError as e:
                            self.logger.log("red", _("Error applying stashed changes: {0}").format(e))
                            self.logger.log("yellow", _("Your changes might be in the stash. Use 'git stash list' to check."))
                    
                    self.logger.log("green", _("Dev branch created successfully!"))
                    return True
                except subprocess.CalledProcessError as e:
                    self.logger.log("red", _("Could not create dev branch: {0}").format(e))
                    
                    # Try to restore original state
                    try:
                        if current_branch != "dev":
                            subprocess.run(["git", "checkout", current_branch], check=True)
                    except subprocess.CalledProcessError:
                        pass
                    
                    # Apply stashed changes if any
                    if stashed:
                        try:
                            self.logger.log("cyan", _("Applying stashed changes..."))
                            subprocess.run(["git", "stash", "pop"], check=True)
                        except subprocess.CalledProcessError:
                            self.logger.log("red", _("Could not apply stashed changes. Your changes are in the stash."))
                    
                    return False
                
            return True
        except Exception as e:
            self.logger.log("red", _("Error creating dev branch: {0}").format(e))
            return False
    
    def get_most_recent_branch(self):
        """Determines which branch has the most recent commit by actual commit date"""
        self.logger.log("cyan", _("Determining which branch has the most recent code..."))
        
        # Fetch the latest from remote
        try:
            subprocess.run(["git", "fetch", "--all"], check=True)
        except subprocess.CalledProcessError:
            self.logger.log("yellow", _("Warning: Failed to fetch latest changes from remote."))
        
        # Get all branches including remote ones
        try:
            result = subprocess.run(
                ["git", "branch", "-a"],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            )
            
            candidate_branches = []
            
            for line in result.stdout.strip().split('\n'):
                branch = line.strip().replace('* ', '').replace('remotes/origin/', '')
                # Include main, master, dev, and dev-* branches
                if branch in ["main", "master", "dev"] or branch.startswith('dev-'):
                    if branch not in candidate_branches:
                        candidate_branches.append(branch)
                    
        except subprocess.CalledProcessError:
            self.logger.log("yellow", _("Warning: Failed to get branch list."))
            return "main"
        
        if not candidate_branches:
            return "main"
        
        # Get the actual last commit date for each branch
        branch_dates = {}
        for branch in candidate_branches:
            try:
                # Get the commit date of the latest commit on this branch
                commit_date_result = subprocess.run(
                    ["git", "log", "-1", "--format=%ct", f"origin/{branch}"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,  # Suppress error messages
                    text=True,
                    check=True
                )
                # %ct gives timestamp in seconds since epoch
                branch_dates[branch] = int(commit_date_result.stdout.strip())
            except subprocess.CalledProcessError:
                # If branch doesn't exist remotely, try locally
                try:
                    commit_date_result = subprocess.run(
                        ["git", "log", "-1", "--format=%ct", branch],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,  # Suppress error messages
                        text=True,
                        check=True
                    )
                    branch_dates[branch] = int(commit_date_result.stdout.strip())
                except subprocess.CalledProcessError:
                    # If we can't get the date, skip this branch (don't include it)
                    continue  # Skip branches that don't exist

        # Check if we found any valid branches
        if not branch_dates:
            self.logger.log("yellow", _("Warning: No valid branches found, using 'dev' as default"))
            return "dev"

        # Find the branch with the most recent commit
        most_recent_branch = max(branch_dates.keys(), key=lambda b: branch_dates[b])
        
        self.logger.log("green", _("The most recent branch is: {0}").format(most_recent_branch))
        return most_recent_branch
    
    def pull_latest_code(self):
        """Pulls the latest code from the most recent branch"""
        most_recent_branch = self.get_most_recent_branch()
        current_branch = GitUtils.get_current_branch()
        
        if most_recent_branch == current_branch:
            # We're already on the most recent branch, just pull
            self.logger.log("cyan", _("You're already on the most recent branch: {0}. Pulling latest changes...").format(current_branch))
            try:
                subprocess.run(["git", "pull", "origin", current_branch], check=True)
                return True
            except subprocess.CalledProcessError:
                self.logger.log("yellow", _("Warning: Failed to pull latest changes."))
                return False
        else:
            # We need to get updates from a different branch
            self.logger.log("cyan", _("The most recent code is on branch: {0}").format(most_recent_branch))
            
            # Check if we have local changes
            has_changes = GitUtils.has_changes()
            
            if has_changes:
                # We have local changes that might be lost
                self.logger.log("yellow", _("You have local changes that could be lost if you switch branches."))
                options = [
                    _("Stash changes and switch to most recent branch"),
                    _("Stay on current branch and just pull its latest version"),
                    _("Cancel operation")
                ]
                result = self.menu.show_menu(_("How do you want to proceed?"), options)
                
                if result is None or result[0] == 2:  # Cancel
                    self.logger.log("yellow", _("Operation cancelled by user."))
                    return False
                
                if result[0] == 0:  # Stash and switch
                    try:
                        # Stash changes
                        self.logger.log("cyan", _("Stashing your local changes..."))
                        subprocess.run(["git", "stash"], check=True)
                        
                        # Switch to most recent branch
                        self.logger.log("cyan", _("Switching to most recent branch: {0}").format(most_recent_branch))
                        subprocess.run(["git", "checkout", most_recent_branch], check=True)
                        
                        # Pull latest
                        self.logger.log("cyan", _("Pulling latest changes..."))
                        subprocess.run(["git", "pull", "origin", most_recent_branch], check=True)
                        
                        # Apply stash
                        self.logger.log("cyan", _("Applying your stashed changes..."))
                        subprocess.run(["git", "stash", "pop"], check=True)
                        
                        self.logger.log("green", _("Successfully switched to most recent branch with your changes."))
                        return True
                    except subprocess.CalledProcessError:
                        self.logger.log("red", _("Error during branch switch operations."))
                        self.logger.log("yellow", _("You may need to manually resolve the situation."))
                        return False
                else:  # Stay and pull current
                    try:
                        self.logger.log("cyan", _("Staying on current branch and pulling its latest version..."))
                        subprocess.run(["git", "pull", "origin", current_branch], check=True)
                        self.logger.log("yellow", _("Note: You're not working with the most recent code from {0}.").format(most_recent_branch))
                        return True
                    except subprocess.CalledProcessError:
                        self.logger.log("red", _("Error pulling latest changes."))
                        return False
            else:
                # No local changes, safe to switch
                try:
                    self.logger.log("cyan", _("Switching to most recent branch: {0}").format(most_recent_branch))
                    subprocess.run(["git", "checkout", most_recent_branch], check=True)
                    
                    self.logger.log("cyan", _("Pulling latest changes..."))
                    subprocess.run(["git", "pull", "origin", most_recent_branch], check=True)
                    
                    self.logger.log("green", _("Successfully switched to most recent branch."))
                    return True
                except subprocess.CalledProcessError:
                    self.logger.log("red", _("Error switching to most recent branch."))
                    return False
    

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
        
        self.is_aur_package = True
        
        # Summary of choices for AUR
        self.show_aur_summary(aur_package_name)
        
        # Detect if running in GUI mode (confirmation already done by GTK dialog)
        is_gui_mode = hasattr(self.menu, '__class__') and 'GTK' in self.menu.__class__.__name__
        
        # In CLI mode, ask for confirmation; in GUI mode, skip (already confirmed)
        if not is_gui_mode:
            if not self.menu.confirm(_("Do you want to proceed with building the PACKAGE?")):
                self.logger.log("red", _("Package build cancelled."))
                return False
        
        self.logger.log("cyan", _("Starting AUR package build..."))
        
        # AUR builds don't need local branches - they just trigger the GitHub workflow
        # The aur-build workflow clones the AUR package directly from aur.archlinux.org
        
        # Trigger workflow (no branch needed for AUR)
        return self.github_api.trigger_workflow(
            aur_package_name, "aur", "", True, self.tmate_option, self.logger
        )
    
    def show_build_summary(self, package_name: str, branch_type: str, working_branch=None):
        """Shows a summary of choices for normal build using Rich"""
        # Get the branch we're using
        if working_branch is None:
            current_branch = GitUtils.get_current_branch()
        else:
            current_branch = working_branch
        
        repo_name = GitUtils.get_repo_name()
        
        data = [
            (_("Organization"), self.organization),
            # (_("Repo Workflow"), self.repo_workflow),
            (_("User Name"), self.github_user_name),
            (_("Package Name"), package_name),
            (_("Repository Type"), branch_type),
            (_("Working Branch"), current_branch),
        ]
        
        if repo_name:
            data.append((_("Url"), f"https://github.com/{repo_name}"))
        
        data.append((_("TMATE Debug"), str(self.tmate_option)))
        
        self.logger.display_summary(_("Summary of Choices"), data)
    
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
            (_("TMATE Debug"), str(self.tmate_option))
        ]
        
        self.logger.display_summary(_("AUR - Summary of Choices"), data)
    
    def main_menu(self):
        """Displays interactive main menu respecting feature flags"""
        while True:
            # Build menu dynamically based on feature flags
            options = []
            actions = []  # Track which action each option corresponds to
            
            if self.is_git_repo:
                # Core git operations (always available)
                options.append(_("Pull latest"))
                actions.append("pull")
                
                options.append(_("Commit and push"))
                actions.append("commit")
                
                # Package generation (only if enabled)
                if self.settings and self.settings.get("package_features_enabled", False):
                    options.append(_("Generate package (commit + branch + build)"))
                    actions.append("package")
                
                # AUR package (only if enabled)
                if self.settings and self.settings.get("aur_features_enabled", False):
                    options.append(_("Build AUR package"))
                    actions.append("aur")
                
                # Settings and Advanced (always available)
                options.append(_("Settings"))
                actions.append("settings")
                
                options.append(_("Advanced menu"))
                actions.append("advanced")
                
                options.append(_("Exit"))
                actions.append("exit")
            else:
                # Non-git repo - limited options
                if self.settings and self.settings.get("aur_features_enabled", False):
                    options.append(_("Build AUR package"))
                    actions.append("aur")
                
                options.append(_("Settings"))
                actions.append("settings")
                
                options.append(_("Exit"))
                actions.append("exit")
            
            result = self.menu.show_menu(_("Main Menu"), options)
            if result is None:
                self.logger.log("yellow", _("Operation cancelled by user."))
                return
            
            choice, ignored = result
            action = actions[choice]
            
            # Handle actions by name instead of index
            if action == "pull":
                from .pull_operations import pull_latest_v2
                pull_latest_v2(self)
                continue

            elif action == "commit":
                from .commit_operations import commit_and_push_v2
                commit_and_push_v2(self)
                return

            elif action == "package":
                # Select branch type
                branch_options = ["testing", "stable", "extra", _("Back")]
                branch_result = self.menu.show_menu(_("Select repository"), branch_options)

                if branch_result is None or branch_options[branch_result[0]] == _("Back"):
                    continue

                branch_type = branch_options[branch_result[0]]

                # Enable or disable tmate for debug
                debug_result = self.menu.show_menu(_("Enable TMATE debug session?"), [_("No"), _("Yes")])
                if debug_result is None:
                    continue

                tmate_option = (debug_result[0] == 1)  # Yes = index 1

                # Get commit message if there are changes
                has_changes = GitUtils.has_changes()
                commit_message = None

                if has_changes:
                    commit_message = self.custom_commit_prompt()
                    if not commit_message:
                        self.logger.log("red", _("Commit message cannot be empty."))
                        continue

                # Use improved version
                from .package_operations import commit_and_generate_package_v2
                commit_and_generate_package_v2(self, branch_type, commit_message, tmate_option)
                return
            
            elif action == "aur":
                # Enable or disable tmate for debug
                debug_result = self.menu.show_menu(_("Enable TMATE debug session?"), [_("No"), _("Yes")])
                if debug_result is None:
                    continue

                self.tmate_option = (debug_result[0] == 1)  # Yes = index 1

                self.args.aur = None  # Force package name request
                self.build_aur_package()
                return

            elif action == "settings":
                if self.settings_menu:
                    self.settings_menu.show()
                continue

            elif action == "advanced":
                self.advanced_menu()
                continue

            elif action == "exit":
                self.logger.log("yellow", _("Exiting script. No action was performed."))
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
            _("Back")
        ]
        
        while True:
            result = self.menu.show_menu(_("Advanced Menu"), options)
            if result is None or result[0] == 6:  # None ou "Back"
                return

            choice, ignore = result

            if choice == 0:  # Delete branches
                if self.menu.confirm(_("Are you sure you want to delete branches? This action cannot be undone.")):
                    GitUtils.cleanup_old_branches(self.logger)

            elif choice == 1:  # Delete failed Action jobs
                if self.menu.confirm(_("Are you sure you want to delete all failed Action jobs?")):
                    self.github_api.clean_action_jobs("failure", self.logger)

            elif choice == 2:  # Delete successful Action jobs
                if self.menu.confirm(_("Are you sure you want to delete all successful Action jobs?")):
                    self.github_api.clean_action_jobs("success", self.logger)

            elif choice == 3:  # Delete tags
                if self.menu.confirm(_("Are you sure you want to delete all repository tags?")):
                    self.github_api.clean_all_tags(self.logger)
                    
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
        subprocess.run(
            ["git", "fetch", "--all", "--prune"],
            check=True
        )
        
        # Get available branches
        try:
            # Get all branches
            result = subprocess.run(
                ["git", "branch", "-r"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True
            )
            
            branches = []
            for line in result.stdout.strip().split('\n'):
                branch = line.strip().replace('origin/', '')
                # Filter only testing and stable branches
                if branch.startswith(('dev-')) and branch != 'HEAD':
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
            
            auto_merge = (merge_result[0] == 1)  # True if "Create PR and auto-merge" is selected
            
            # Show summary
            data = [
                (_("Source Branch"), selected_branch),
                (_("Target Branch"), "main"),
                (_("Auto-merge"), _("Yes") if auto_merge else _("No"))
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
            
        except subprocess.CalledProcessError as e:
            self.logger.log("red", _("Error getting branches: {0}").format(e.stderr.strip() if hasattr(e, 'stderr') else str(e)))
        except Exception as e:
            self.logger.log("red", _("Unexpected error: {0}").format(str(e)))
    
    def revert_commit_menu(self):
        """Display menu for reverting / resetting commits."""
        from .revert_operations import revert_commit_menu as _revert

        _revert(self)

    def get_recent_commits(self, count: int = 10) -> list:
        """Return the *count* most recent commits as a list of dicts."""
        from .revert_operations import get_recent_commits as _get

        return _get(self, count)

    def execute_revert(self, commit: dict, revert_method: str, current_branch: str) -> bool:
        """Perform the revert or reset and return success status."""
        from .revert_operations import execute_revert as _exec

        return _exec(self, commit, revert_method, current_branch)

    def show_operation_summary(self, operation_type: str, commit_info: dict, details: dict = None) -> None:
        """Show a rich post-operation summary and wait for user confirmation."""
        from .revert_operations import show_operation_summary as _summary

        _summary(self, operation_type, commit_info, details)

    def check_commit_in_remote(self, commit_hash: str) -> bool:
        """Return True if *commit_hash* appears in any remote-tracking branch."""
        from .revert_operations import check_commit_in_remote as _check

        return _check(commit_hash)

    def run(self):
        """Executes main program flow"""
        # Check command line arguments
        if self.args.commit and not self.args.build:
            # Only commit/push (direct CLI path)
            from .commit_operations import commit_and_push_cli
            commit_and_push_cli(self)

        elif self.args.build:
            # Perform commit (if -c is present) and generate package (direct CLI path)
            from .commit_operations import commit_and_generate_package_cli
            commit_and_generate_package_cli(self)

        elif self.args.aur:
            # Build AUR package
            self.build_aur_package()

        else:
            # No specific argument, show interactive menu
            self.main_menu()
            
    def get_update_changes_summary(self, initial_commit, final_commit, branch_name):
        """Generate a formatted summary of changes"""
        
        if not initial_commit or not final_commit:
            result = _("✓ Successfully updated to latest {0}!").format(self.logger.format_branch_name(branch_name)) + "\n"
            return result
        
        if initial_commit == final_commit:
            result = _("✓ Already up to date with {0}").format(self.logger.format_branch_name(branch_name)) + "\n"
            return result
        
        try:
            summary_lines = []
            summary_lines.append(_("✓ Successfully updated to latest {0}!").format(self.logger.format_branch_name(branch_name)) + "\n")
            
            # Get commit range info
            commits_result = subprocess.run(
                ["git", "log", "--oneline", f"{initial_commit}..{final_commit}"],
                stdout=subprocess.PIPE, text=True, check=True
            )
            
            if commits_result.stdout.strip():
                commit_lines = commits_result.stdout.strip().split('\n')
                commit_count = len(commit_lines)
                
                summary_lines.append(_("📄 New commits ({0}):").format(commit_count))
                for line in commit_lines[:5]:  # Show max 5 commits
                    summary_lines.append(f"  • {line}")
                
                if commit_count > 5:
                    summary_lines.append(f"  ... and {commit_count - 5} more commits")
                summary_lines.append("")
            
            # Show file changes
            diff_result = subprocess.run(
                ["git", "diff", "--name-status", initial_commit, final_commit],
                stdout=subprocess.PIPE, text=True, check=True
            )
            
            if diff_result.stdout.strip():
                changes = {}
                for line in diff_result.stdout.strip().split('\n'):
                    if line:
                        status = line[0]
                        filename = line[1:].strip()
                        if status not in changes:
                            changes[status] = []
                        changes[status].append(filename)
                
                # Show changes summary
                total_files = sum(len(files) for files in changes.values())
                summary_lines.append(_("📁 Files changed ({0}):").format(total_files))
                
                # Show by type
                if 'A' in changes:
                    summary_lines.append(_("  ✓ Added: {0} files").format(len(changes['A'])))
                    for f in changes['A'][:3]:
                        summary_lines.append(f"    + {f}")
                    if len(changes['A']) > 3:
                        summary_lines.append(_("    + ... and {0} more").format(len(changes['A']) - 3))

                if 'M' in changes:
                    summary_lines.append(_("  ⚠ Modified: {0} files").format(len(changes['M'])))
                    for f in changes['M'][:3]:
                        summary_lines.append(f"    ~ {f}")
                    if len(changes['M']) > 3:
                        summary_lines.append(_("    ~ ... and {0} more").format(len(changes['M']) - 3))

                if 'D' in changes:
                    summary_lines.append(_("  ✗ Deleted: {0} files").format(len(changes['D'])))
                    for f in changes['D'][:3]:
                        summary_lines.append(f"    - {f}")
                    if len(changes['D']) > 3:
                        summary_lines.append(_("    - ... and {0} more").format(len(changes['D']) - 3))

                if 'R' in changes:
                    summary_lines.append(_("  → Renamed: {0} files").format(len(changes['R'])))
                
                summary_lines.append("")
            
            # Show stats
            stats_result = subprocess.run(
                ["git", "diff", "--stat", initial_commit, final_commit],
                stdout=subprocess.PIPE, text=True, check=True
            )
            
            if stats_result.stdout.strip():
                stats_lines = stats_result.stdout.strip().split('\n')
                if len(stats_lines) > 1:
                    summary_line = stats_lines[-1]
                    summary_lines.append(_("📊 {0}").format(summary_line))
                    summary_lines.append("")
            
            result = '\n'.join(summary_lines)
            return result
                    
        except Exception as e:
            return _("✓ Successfully updated to latest {0}!").format(
                self.logger.format_branch_name(branch_name)) + "\n" + _("⚠ Could not show detailed changes: {0}").format(str(e)) + "\n"
    
    def _switch_to_branch_safely(self, target_branch):
        """Helper method to switch branches with proper error handling and feedback"""
        try:
            # Simple checkout - conflicts should be resolved now
            subprocess.run(["git", "checkout", target_branch], check=True)
            
            # Conflict-resistant pull strategy
            pull_cmd = ["git", "pull", "origin", target_branch, "--strategy-option=theirs", "--no-edit"]
            pull_result = subprocess.run(pull_cmd, capture_output=True, text=True)
            
            if pull_result.returncode != 0:
                # If pull fails, try alternative strategies
                self.logger.log("yellow", _("Standard pull failed, trying force strategy..."))
                
                # Try fetch + reset strategy
                subprocess.run(["git", "fetch", "origin", target_branch], check=True)
                subprocess.run(["git", "reset", "--hard", f"origin/{target_branch}"], check=True)
                self.logger.log("green", _("Force-updated to latest {0}").format(self.logger.format_branch_name(target_branch)))
            else:
                self.logger.log("green", _("Successfully switched and updated to {0}").format(self.logger.format_branch_name(target_branch)))
            
        except subprocess.CalledProcessError as e:
            self.logger.log("red", _("Error switching to branch {0}: {1}").format(target_branch, e))
            raise
