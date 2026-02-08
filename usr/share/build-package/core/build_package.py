#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# build_package.py - Main class for package management

import sys
import os
import re
import argparse
import subprocess
from rich.console import Console
from rich.prompt import Prompt
import tempfile
from datetime import datetime
from .translation_utils import _

from .config import (
    APP_NAME, APP_DESC, APP_VERSION, DEFAULT_ORGANIZATION,
    VALID_ORGANIZATIONS, VALID_BRANCHES
)
from .git_utils import GitUtils
from .github_api import GitHubAPI
from .settings import Settings
from .conflict_resolver import ConflictResolver
from .operation_preview import OperationPlan, QuickPlan
from .settings_menu import SettingsMenu

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
        # Get GitHub token
        token = GitHubAPI(None, self.organization).get_github_token(self.logger)
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
                subprocess.run(
                    ["which", dep],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True
                )
            except subprocess.CalledProcessError:
                self.logger.die("red", _("Dependency '{0}' not found. Please install it before continuing.").format(dep))
    
    def parse_arguments(self) -> argparse.Namespace:
        """Parses command line arguments with colored help"""
        
        # Custom help action that shows colored help
        class ColoredHelpAction(argparse.Action):
            def __init__(self, option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, help=None):
                super().__init__(option_strings=option_strings, dest=dest, default=default, nargs=0, help=help)
            
            def __call__(self, parser, namespace, values, option_string=None):
                from rich.console import Console
                from rich.panel import Panel
                from rich.text import Text
                from rich.table import Table
                from rich.box import ROUNDED
                
                console = Console()
                
                # Header - compact version like main menu
                header = Text()
                header.append(f"{APP_NAME} ", style="bold cyan")
                header.append(f"v{APP_VERSION}\n", style="bold white")
                header.append(f"{APP_DESC}", style="white")

                console.print(Panel(
                    header, 
                    border_style="cyan", 
                    box=ROUNDED, 
                    padding=(0, 1),
                    title="BigCommunity",
                    width=70  # Fixed width like other menus
                ))
                console.print()
                
                # Usage
                console.print("[bold yellow]USAGE:[/]")
                console.print(f"  [cyan]python main.py[/] [dim]\\[OPTIONS][/]\n")
                
                # Interface Mode Flags (special flags processed before argparse)
                console.print("[bold yellow]INTERFACE MODE:[/]")
                table_interface = Table(show_header=False, box=None, padding=(0, 2))
                table_interface.add_column(style="green bold", no_wrap=True)
                table_interface.add_column(style="white")
                
                table_interface.add_row(
                    "--cli, --no-gui",
                    _("Force CLI mode (terminal interface)")
                )
                table_interface.add_row(
                    "--gui",
                    _("Force GUI mode (graphical interface)")
                )
                console.print(table_interface)
                console.print()
                
                # Main Options
                console.print("[bold yellow]OPTIONS:[/]")
                table = Table(show_header=False, box=None, padding=(0, 2))
                table.add_column(style="green bold", no_wrap=True)
                table.add_column(style="white")
                
                table.add_row(
                    "-h, --help",
                    _("Show this help message and exit")
                )
                table.add_row(
                    "-V, --version",
                    _("Print application version")
                )
                table.add_row(
                    "-o, --org, --organization",
                    _("Configure GitHub organization") + " [dim](default: big-comm)[/]\n" +
                    _("Choices: {big-comm, biglinux}")
                )
                table.add_row(
                    "-b, --build {dev}",
                    _("Commit/push and generate package")
                )
                table.add_row(
                    "-c, --commit MSG",
                    _("Just commit/push with the specified message")
                )
                table.add_row(
                    "-F, --commit-file FILE",
                    _("Read commit message from file (multi-line support)")
                )
                table.add_row(
                    "-a, --aur PACKAGE",
                    _("Build AUR package")
                )
                table.add_row(
                    "-t, --tmate",
                    _("Enable tmate for debugging")
                )
                table.add_row(
                    "-n, --nocolor",
                    _("Suppress color printing")
                )
                
                console.print(table)
                console.print()
                
                # Examples
                console.print("[bold yellow]EXAMPLES:[/]")
                examples = [
                    ("python main.py --cli", _("Open in CLI mode")),
                    ("python main.py --gui", _("Open in GUI mode")),
                    ("python main.py -c \"fix: bug fix\"", _("Quick commit with message")),
                    ("python main.py -F commit_msg.txt", _("Commit with message from file")),
                    ("python main.py -b dev -c \"feat: new feature\"", _("Build development package")),
                    ("python main.py -a package-name", _("Build AUR package")),
                ]
                
                for cmd, desc in examples:
                    console.print(f"  [cyan]{cmd}[/]")
                    console.print(f"    [dim]{desc}[/]\n")
                
                # Footer
                console.print(f"[dim]For more information, visit: https://github.com/big-comm[/]")
                
                parser.exit()
        
        parser = argparse.ArgumentParser(
            description=f"{APP_NAME} v{APP_VERSION} - {APP_DESC}",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            add_help=False  # Disable default help to use custom one
        )
        
        # Add custom help
        parser.add_argument("-h", "--help", action=ColoredHelpAction,
                        help=_("Show this help message and exit"))
        
        parser.add_argument("-o", "--org", "--organization", 
                        dest="organization", 
                        help=_("Configure GitHub organization (default: big-comm)"),
                        choices=VALID_ORGANIZATIONS,
                        default=DEFAULT_ORGANIZATION)
        
        parser.add_argument("-b", "--build",
                        help=_("Commit/push and generate package"),
                        choices=VALID_BRANCHES)
        
        parser.add_argument("-c", "--commit",
                        help=_("Just commit/push with the specified message"))
        
        parser.add_argument("-F", "--commit-file",
                        help=_("Read commit message from file (multi-line support)"))
        
        parser.add_argument("-a", "--aur",
                        help=_("Build AUR package"))
        
        parser.add_argument("-n", "--nocolor", action="store_true",
                        help=_("Suppress color printing"))
        
        parser.add_argument("-V", "--version", action="store_true",
                        help=_("Print application version"))
        
        parser.add_argument("-t", "--tmate", action="store_true",
                        help=_("Enable tmate for debugging"))

        parser.add_argument("--mode", choices=['safe', 'quick', 'expert'],
                        help=_("Operation mode: safe (default), quick (fast), expert (max automation)"))

        parser.add_argument("--dry-run", action="store_true",
                        help=_("Simulate operations without executing"))

        args = parser.parse_args()

        if args.version:
            self.print_version()
            sys.exit(0)

        return args
    
    def print_version(self):
        """Prints application version"""
        console = Console()
        from rich.text import Text
        from rich.panel import Panel
        from rich.box import ROUNDED
        
        version_text = Text()
        version_text.append(f"{APP_NAME} v{APP_VERSION}\n", style="bold cyan")
        version_text.append(f"{APP_DESC}\n\n", style="white")
        version_text.append(_("Copyright (C) 2024-2025 BigCommunity Team\n\n"), style="blue")
        version_text.append(_("""This is free software: you are free to modify and redistribute it."""), style="white")
        version_text.append("\n", style="white")
        version_text.append(f"{APP_NAME}", style="cyan")
        version_text.append(_(" is provided to you under the "), style="white")
        version_text.append(_("MIT License"), style="yellow")
        version_text.append(_(""", and includes open source software under a variety of other licenses.
You can read instructions about how to download and build for yourself
the specific source code used to create this copy."""), style="white")
        version_text.append("\n", style="white")
        version_text.append(_("This program comes with absolutely NO warranty."), style="red")
        
        panel = Panel(
            version_text,
            box=ROUNDED,
            border_style="blue",
            padding=(1, 2)
        )
        
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
            ("✏️", "custom", _("Custom commit message (free text)"))
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

    def _extract_commit_metadata(self, commit_message, explicit_type=None):
        """Extracts commit type and breaking change info from message"""
        commit_type = explicit_type if explicit_type not in (None, "custom") else None
        breaking_change = False
        message = (commit_message or "").strip()
        
        if message:
            first_line = message.splitlines()[0].strip()
            # Remove leading emojis/symbols before analysing the commit header
            cleaned_header = re.sub(r'^[^\w]+', '', first_line)
            match = re.match(r'(?P<type>[a-zA-Z]+)(?:\([^\)]*\))?(?P<breaking>!?):', cleaned_header)
            if match:
                if not commit_type:
                    commit_type = match.group('type').lower()
                if match.group('breaking'):
                    breaking_change = True
            if not breaking_change and "BREAKING CHANGE" in message.upper():
                breaking_change = True
        
        return commit_type.lower() if commit_type else None, breaking_change

    def _infer_bump_level(self, commit_type, breaking_change):
        """Maps commit metadata to semantic version bump level"""
        if breaking_change:
            return "major"
        
        if not commit_type:
            return None
        
        commit_type = commit_type.lower()
        if commit_type == "feat":
            return "minor"
        
        patch_types = {"fix", "perf", "docs", "style", "refactor", "test", "build", "ci", "chore"}
        if commit_type in patch_types:
            return "patch"
        
        return None

    def _locate_app_version_entry(self):
        """Finds the file and match object for APP_VERSION assignment"""
        pattern = re.compile(r'(APP_VERSION\s*=\s*)(["\'])(\d+\.\d+\.\d+)(["\'])')
        repo_path = self.repo_path or GitUtils.get_repo_root_path()
        
        # Try cached path first
        if self._app_version_cache:
            try:
                with open(self._app_version_cache, 'r', encoding='utf-8') as cached_file:
                    cached_content = cached_file.read()
                cached_match = pattern.search(cached_content)
                if cached_match:
                    return self._app_version_cache, cached_content, cached_match
            except (OSError, UnicodeDecodeError):
                self._app_version_cache = None
        
        if not repo_path or not os.path.isdir(repo_path):
            return None, None, None
        
        ignore_dirs = {
            '.git', '__pycache__', 'node_modules', 'vendor', 'venv', '.venv', 'env',
            'build', 'dist', '.idea', '.vscode'
        }
        allowed_extensions = {
            "", ".py", ".cfg", ".conf", ".ini", ".json", ".toml", ".yaml", ".yml",
            ".txt", ".sh", ".bash", ".zsh", ".fish"
        }
        
        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            dirs.sort()
            for filename in sorted(files):
                ext = os.path.splitext(filename)[1].lower()
                if ext not in allowed_extensions:
                    continue
                
                file_path = os.path.join(root, filename)
                
                try:
                    if os.path.getsize(file_path) > 1_000_000:  # Skip files larger than ~1MB
                        continue
                except OSError:
                    continue
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as file_handle:
                        content = file_handle.read()
                except (OSError, UnicodeDecodeError):
                    continue
                
                for match in pattern.finditer(content):
                    line_start = content.rfind('\n', 0, match.start()) + 1
                    line_prefix = content[line_start:match.start()]
                    stripped_prefix = line_prefix.strip()
                    
                    if stripped_prefix.startswith(("#", "//", ";", "/*")):
                        continue
                    
                    prefix_no_trailing = line_prefix.rstrip()
                    if prefix_no_trailing and prefix_no_trailing[-1] in ("'", '"'):
                        continue
                    
                    self._app_version_cache = file_path
                    return file_path, content, match
        
        return None, None, None

    def _bump_semver(self, current_version, bump_level):
        """Returns bumped semantic version string"""
        try:
            major, minor, patch = [int(part) for part in current_version.split('.')]
        except (ValueError, AttributeError):
            return current_version
        
        if bump_level == "major":
            major += 1
            minor = 0
            patch = 0
        elif bump_level == "minor":
            minor += 1
            patch = 0
        else:  # patch
            patch += 1
        
        return f"{major}.{minor}.{patch}"

    def apply_auto_version_bump(self, commit_message, explicit_type=None):
        """Automatically bumps APP_VERSION based on commit metadata"""
        commit_type, breaking_change = self._extract_commit_metadata(commit_message, explicit_type)
        bump_level = self._infer_bump_level(commit_type, breaking_change)
        
        if not bump_level:
            return None
        
        file_path, content, match = self._locate_app_version_entry()
        if not file_path or not match:
            if not self._app_version_warning_shown and self.logger:
                self.logger.log("yellow", _("APP_VERSION constant not found. Skipping automatic version bump."))
                self._app_version_warning_shown = True
            return None
        
        current_version = match.group(3)
        new_version = self._bump_semver(current_version, bump_level)
        
        if current_version == new_version:
            return None
        
        new_assignment = f"{match.group(1)}{match.group(2)}{new_version}{match.group(4)}"
        updated_content = content[:match.start()] + new_assignment + content[match.end():]
        
        try:
            with open(file_path, 'w', encoding='utf-8') as file_handle:
                file_handle.write(updated_content)
        except OSError as exc:
            if self.logger:
                self.logger.log(
                    "yellow",
                    _("Could not update APP_VERSION ({0}). Reason: {1}").format(file_path, exc)
                )
            return None
        
        relative_path = os.path.relpath(file_path, self.repo_path or GitUtils.get_repo_root_path())
        if self.logger:
            self.logger.log(
                "green",
                _("APP_VERSION bumped from {0} to {1} ({2} bump) in {3}").format(
                    current_version, new_version, bump_level, relative_path
                )
            )
        
        return new_version
    
    def commit_and_push(self):
        """Performs commit on user's own dev branch with proper isolation"""
        if not self.is_git_repo:
            self.logger.die("red", _("This option is only available in git repositories."))
            return False
        
        # Ensure dev branch exists
        self.ensure_dev_branch_exists()
        
        # Get user info and target branch
        username = self.github_user_name or "unknown"
        my_branch = f"dev-{username}"
        current_branch = GitUtils.get_current_branch()

        # ASK USER: Which branch to commit to?
        self.logger.log("cyan", _("Choose target branch for commit:"))
        branch_choice = self.menu.show_menu(
            _("Select branch for commit"),
            [
                _("My branch ({0}) - Recommended").format(my_branch),
                _("Main branch - Direct commit"),
                _("Cancel")
            ],
            default_index=0
        )

        if branch_choice is None or branch_choice[0] == 2:  # Cancel
            self.logger.log("yellow", _("Operation cancelled"))
            return False

        # Set target branch based on user choice
        if branch_choice[0] == 1:  # Main branch
            target_branch = "main"
            self.logger.log("yellow", _("⚠️  WARNING: You chose to commit directly to main!"))

            # Confirm this choice
            confirm = self.menu.confirm(_("Are you sure you want to commit directly to main branch?"))
            if not confirm:
                self.logger.log("yellow", _("Operation cancelled"))
                return False

            self.logger.log("cyan", _("Target branch: {0}").format(self.logger.format_branch_name(target_branch)))
        else:  # User's branch (default)
            target_branch = my_branch
            self.logger.log("cyan", _("Target branch: {0}").format(self.logger.format_branch_name(target_branch)))

        # ROBUST CHECK: Ensure user is working in their target branch
        if current_branch != target_branch:
            self.logger.log("yellow", _("You're in {0} but should commit to {1}. Fixing this...").format(
                self.logger.format_branch_name(current_branch), self.logger.format_branch_name(target_branch)))

            # Check if there are changes to preserve
            has_changes = GitUtils.has_changes()

            if has_changes:
                # Stash → Switch → Apply workflow
                self.logger.log("cyan", _("Preserving your changes while switching to target branch..."))
                stash_message = f"auto-preserve-changes-commit-to-{target_branch}"
                stash_result = subprocess.run(
                    ["git", "stash", "push", "-u", "-m", stash_message],
                    capture_output=True, text=True, check=False
                )

                if stash_result.returncode != 0:
                    self.logger.log("red", _("Failed to stash changes. Cannot proceed safely."))
                    return False

                # Ensure target branch exists and switch
                if target_branch == "main":
                    # For main branch, try to checkout or create if it doesn't exist
                    checkout_result = subprocess.run(
                        ["git", "checkout", target_branch], 
                        capture_output=True, text=True, check=False
                    )
                    if checkout_result.returncode != 0:
                        # Branch doesn't exist, create it
                        self.logger.log("cyan", _("Creating main branch (doesn't exist yet)..."))
                        create_result = subprocess.run(
                            ["git", "checkout", "-b", target_branch],
                            capture_output=True, text=True, check=False
                        )
                        if create_result.returncode != 0:
                            self.logger.log("red", _("Failed to create main branch: {0}").format(create_result.stderr))
                            return False
                        self.logger.log("green", _("✓ Created new main branch"))
                else:
                    # For user branch, ensure it exists
                    if not self.ensure_user_branch_exists(target_branch):
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
                        self.logger.log("red", _("Could not resolve conflicts automatically. Please check 'git status'"))
                        return False

                self.logger.log("green", _("Successfully moved your changes to target branch!"))
            else:
                # No changes, just ensure we're on target branch
                if target_branch == "main":
                    # For main branch, try to checkout or create if it doesn't exist
                    checkout_result = subprocess.run(
                        ["git", "checkout", target_branch], 
                        capture_output=True, text=True, check=False
                    )
                    if checkout_result.returncode != 0:
                        # Branch doesn't exist, create it
                        self.logger.log("cyan", _("Creating main branch (doesn't exist yet)..."))
                        create_result = subprocess.run(
                            ["git", "checkout", "-b", target_branch],
                            capture_output=True, text=True, check=False
                        )
                        if create_result.returncode != 0:
                            self.logger.log("red", _("Failed to create main branch: {0}").format(create_result.stderr))
                            return False
                        self.logger.log("green", _("✓ Created new main branch"))
                else:
                    if not self.ensure_user_branch_exists(target_branch):
                        return False
                self.logger.log("cyan", _("Switched to target branch: {0}").format(self.logger.format_branch_name(target_branch)))

        # Now we're guaranteed to be in target branch
        current_branch = target_branch
        
        # Check if there are changes AFTER ensuring we're in the right branch
        has_changes = GitUtils.has_changes()

        # SYNC REMOTE BRANCH: Update remote dev-username branch with latest main BEFORE pulling
        # BUT PRESERVE LOCAL CHANGES!
        # NOTE: Skip this for main branch - only sync dev branches
        if target_branch != "main":
            self.logger.log("cyan", _("Checking if your remote branch needs sync with main..."))

            # CRITICAL: Save local changes first!
            local_changes_backup = None
            if has_changes:
                self.logger.log("cyan", _("Backing up your local changes temporarily..."))
                try:
                    # Create a temporary stash with all changes
                    stash_result = subprocess.run(
                        ["git", "stash", "push", "-u", "-m", "auto-backup-before-sync"],
                        capture_output=True, text=True, check=False
                    )
                    if stash_result.returncode == 0:
                        local_changes_backup = True
                        self.logger.log("green", _("Local changes safely backed up!"))
                    else:
                        self.logger.log("yellow", _("Could not backup changes, skipping sync."))
                except Exception as e:
                    self.logger.log("yellow", _("Could not backup changes: {0}").format(e))

            try:
                # Check if remote branch exists
                remote_check = subprocess.run(
                    ["git", "ls-remote", "--heads", "origin", target_branch],
                    capture_output=True, text=True, check=False
                )

                remote_branch_exists = bool(remote_check.stdout.strip())

                if remote_branch_exists:
                    # Remote branch exists - check if it needs sync with main
                    self.logger.log("cyan", _("Remote branch exists. Checking sync status..."))

                    # Fetch latest main
                    subprocess.run(["git", "fetch", "origin", "main"], check=True)

                    # Check if remote branch is behind main
                    behind_check = subprocess.run(
                        ["git", "rev-list", "--count", f"origin/{target_branch}..origin/main"],
                        capture_output=True, text=True, check=False
                    )

                    commits_behind = int(behind_check.stdout.strip()) if behind_check.returncode == 0 and behind_check.stdout.strip() else 0

                    if commits_behind > 0:
                        self.logger.log("yellow", _("Your remote branch is {0} commits behind main. Updating...").format(commits_behind))

                        # Save current branch
                        original_branch = GitUtils.get_current_branch()

                        # Switch to target branch if not already there
                        if original_branch != target_branch:
                            subprocess.run(["git", "checkout", target_branch], check=True)

                        # Pull latest from remote target branch first
                        subprocess.run(["git", "pull", "origin", target_branch, "--no-edit"], check=False)

                        # Try to merge main into target branch
                        merge_result = subprocess.run(
                            ["git", "merge", "origin/main", "--no-edit"],
                            capture_output=True, text=True, check=False
                        )

                        if merge_result.returncode == 0:
                            # Merge successful, push updated branch
                            subprocess.run(["git", "push", "origin", target_branch], check=True)
                            self.logger.log("green", _("Remote branch synced with main successfully!"))
                        else:
                            # Merge failed, use force update strategy
                            self.logger.log("yellow", _("Merge conflict detected. Using force-update strategy..."))
                            subprocess.run(["git", "merge", "--abort"], check=False)
                            subprocess.run(["git", "reset", "--hard", "origin/main"], check=True)
                            subprocess.run(["git", "push", "origin", target_branch, "--force"], check=True)
                            self.logger.log("green", _("Remote branch force-updated with main!"))

                        # Return to original branch if needed
                        if original_branch != target_branch:
                            subprocess.run(["git", "checkout", original_branch], check=True)
                    else:
                        self.logger.log("green", _("Remote branch is already up-to-date with main!"))
                else:
                    self.logger.log("cyan", _("Remote branch doesn't exist yet - will be created on first push."))

            except subprocess.CalledProcessError as e:
                self.logger.log("yellow", _("Could not sync remote branch: {0}. Continuing...").format(e))
            except Exception as e:
                self.logger.log("yellow", _("Unexpected sync error: {0}. Continuing...").format(e))
            finally:
                # CRITICAL: Restore local changes!
                if local_changes_backup:
                    self.logger.log("cyan", _("Restoring your local changes..."))
                    try:
                        restore_result = subprocess.run(
                            ["git", "stash", "pop"],
                            capture_output=True, text=True, check=False
                        )
                        if restore_result.returncode == 0:
                            self.logger.log("green", _("Local changes restored successfully!"))
                        else:
                            self.logger.log("yellow", _("Could not restore changes automatically. Check 'git stash list'"))
                    except Exception as e:
                        self.logger.log("yellow", _("Error restoring changes: {0}").format(e))

            # Recheck changes after sync (they should be back now)
            has_changes = GitUtils.has_changes()

            # NOW pull is safe because remote branch is synced with main
            if not has_changes:
                if not GitUtils.git_pull(self.logger):
                    self.logger.log("yellow", _("Failed to pull latest changes, but continuing since no local changes."))
            else:
                self.logger.log("cyan", _("Local changes detected - skipping automatic pull to avoid conflicts."))
        else:
            # For main branch, just pull latest
            self.logger.log("cyan", _("Pulling latest changes from main..."))
            try:
                subprocess.run(["git", "pull", "origin", "main", "--no-edit"], check=True)
                self.logger.log("green", _("Successfully pulled latest main"))
            except subprocess.CalledProcessError:
                self.logger.log("yellow", _("Failed to pull, but continuing..."))

        # Handle commit message based on if we have changes and args
        self.last_commit_type = None
        if self.args.commit_file:
            # Read commit message from file
            try:
                with open(self.args.commit_file, 'r', encoding='utf-8') as f:
                    commit_message = f.read().strip()
                if not commit_message:
                    self.logger.die("red", _("Commit message file is empty."))
                    return False
                self.logger.log("cyan", _("Using commit message from file: {0}").format(self.args.commit_file))
            except FileNotFoundError:
                self.logger.die("red", _("Commit message file not found: {0}").format(self.args.commit_file))
                return False
            except Exception as e:
                self.logger.die("red", _("Error reading commit message file: {0}").format(e))
                return False
        elif self.args.commit:
            # User already provided commit message via argument
            commit_message = self.args.commit
        elif has_changes:
            # No commit message provided, but we have changes - ask for message
            commit_message = self.custom_commit_prompt()
            if not commit_message:
                self.logger.die("red", _("Commit message cannot be empty."))
                return False
        else:
            # No changes to commit
            self.menu.show_menu(_("No Changes to Commit") + "\n", [_("Press Enter to return to main menu")])
            return True
        
        if has_changes and commit_message:
            self.apply_auto_version_bump(commit_message, self.last_commit_type)
        
        # Add and commit changes to user's dev branch
        try:
            subprocess.run(["git", "add", "--all"], check=True)
            
            # Use file for multiline messages
            if '\n' in commit_message:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                    f.write(commit_message)
                    commit_file = f.name
                try:
                    subprocess.run(["git", "commit", "-F", commit_file], check=True)
                finally:
                    os.unlink(commit_file)
            else:
                subprocess.run(["git", "commit", "-m", commit_message], check=True)
        except subprocess.CalledProcessError as e:
            self.logger.log("red", _("Error committing changes: {0}").format(e))
            return False
        
        # Push target branch to remote
        try:
            subprocess.run(["git", "push", "-u", "origin", target_branch], check=True)
        except subprocess.CalledProcessError as e:
            self.logger.log("red", _("Error pushing to remote: {0}").format(e))
            return False

        self.logger.log("green", _("Changes committed and pushed to {0} branch successfully!").format(self.logger.format_branch_name(target_branch)))
        return True
    
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
                    except:
                        pass
                    
                    # Apply stashed changes if any
                    if stashed:
                        try:
                            self.logger.log("cyan", _("Applying stashed changes..."))
                            subprocess.run(["git", "stash", "pop"], check=True)
                        except:
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
    
    def commit_and_generate_package(self):
        """Performs commit, creates branch and triggers workflow to generate package"""
        if not self.is_git_repo:
            self.logger.die("red", _("This operation is only available in git repositories."))
            return False
        
        branch_type = self.args.build
        if not branch_type:
            self.logger.die("red", _("Branch type not specified."))
            return False
        
        # FORCE CLEANUP AT START - resolve any conflicts immediately without external functions
        self.logger.log("cyan", _("Checking and resolving any existing conflicts..."))
        try:
            # Check if there are unmerged files (conflicts)
            status_result = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False
            )
            has_conflicts = bool(status_result.stdout.strip())
            
            # Check if merge is in progress
            repo_root = GitUtils.get_repo_root_path()
            merge_head_path = os.path.join(repo_root, '.git', 'MERGE_HEAD')
            merge_in_progress = os.path.exists(merge_head_path)
            
            if has_conflicts or merge_in_progress:
                self.logger.log("yellow", _("Conflicts detected. Performing automatic cleanup..."))
                
                # Force abort any merge in progress
                subprocess.run(["git", "merge", "--abort"], capture_output=True, check=False)
                
                # Stash any local changes to preserve them
                stash_result = subprocess.run(["git", "stash", "push", "-m", "auto-backup-before-cleanup"], 
                                            capture_output=True, check=False)
                stashed = stash_result.returncode == 0 and "No local changes to save" not in stash_result.stdout.decode()
                
                # Hard reset to clean state
                subprocess.run(["git", "reset", "--hard", "HEAD"], check=True)
                
                # Clean untracked files
                subprocess.run(["git", "clean", "-fd"], check=True)
                
                self.logger.log("green", _("Repository cleaned to stable state."))
                
                # Try to restore stashed changes
                if stashed:
                    self.logger.log("cyan", _("Restoring your local changes..."))
                    restore_result = subprocess.run(["git", "stash", "pop"], capture_output=True, text=True)
                    if restore_result.returncode == 0:
                        self.logger.log("green", _("Local changes restored successfully"))
                    else:
                        self.logger.log("yellow", _("Could not restore stashed changes. Use 'git stash list' to see them."))
            else:
                self.logger.log("green", _("Repository is already in clean state."))
                
        except subprocess.CalledProcessError as e:
            self.logger.log("yellow", _("Warning during cleanup: {0}").format(e))
        
        # Ensure dev branch exists before proceeding
        self.ensure_dev_branch_exists()
        
        # AUTOMATION: Fetch remote without user interaction
        self.logger.log("cyan", _("Fetching latest updates from remote..."))
        try:
            subprocess.run(["git", "fetch", "--all"], check=True)
        except subprocess.CalledProcessError:
            self.logger.log("yellow", _("Warning: Failed to fetch latest changes, continuing with local code."))
        
        # Get current branch after cleanup
        current_branch = GitUtils.get_current_branch()
        
        # Identify most recent branch
        most_recent_branch = self.get_most_recent_branch()
        
        # PRODUCTIVITY AUTOMATION: Always work with most recent code
        if most_recent_branch != current_branch:
            # Check if user has uncommitted changes before switching
            has_local_changes = GitUtils.has_changes()
            
            # Show clear information about what's happening
            self.logger.log("cyan", _("Current branch: {0}").format(self.logger.format_branch_name(current_branch)))
            self.logger.log("cyan", _("Most recent branch available: {0}").format(self.logger.format_branch_name(most_recent_branch)))
            
            if has_local_changes:
                # AUTOMATIC WORKFLOW: Stash → Switch → Apply → Ready for commit
                self.logger.log("cyan", _("Moving your changes to the most recent branch..."))
                
                # Step 1: Stash changes with descriptive message
                stash_message = f"auto-preserve-changes-from-{current_branch}-to-{most_recent_branch}"
                self.logger.log("cyan", _("Step 1/4: Preserving your changes temporarily..."))
                stash_result = subprocess.run(
                    ["git", "stash", "push", "-u", "-m", stash_message], 
                    capture_output=True, text=True, check=False
                )
                
                if stash_result.returncode != 0:
                    self.logger.log("red", _("Failed to stash changes. Cannot proceed safely."))
                    return False
                
                # Step 2: Switch to most recent branch
                self.logger.log("cyan", _("Step 2/4: Switching to most recent branch..."))
                try:
                    self._switch_to_branch_safely(most_recent_branch)
                except subprocess.CalledProcessError as e:
                    self.logger.log("red", _("Failed to switch branches. Your changes are safe in stash."))
                    return False
                
                # Step 3: Apply stashed changes to new branch
                self.logger.log("cyan", _("Step 3/4: Applying your changes to the most recent branch..."))
                pop_result = subprocess.run(["git", "stash", "pop"], capture_output=True, text=True, check=False)
                
                if pop_result.returncode != 0:
                    self.logger.log("yellow", _("Conflicts detected while applying changes. Resolving automatically..."))
                    # Try to resolve conflicts automatically by preferring user's changes
                    try:
                        subprocess.run(["git", "reset", "HEAD"], check=True)  # Unstage conflicted files
                        subprocess.run(["git", "add", "."], check=True)       # Add all files (resolves conflicts)
                        self.logger.log("green", _("Conflicts resolved automatically"))
                    except subprocess.CalledProcessError:
                        self.logger.log("red", _("Could not resolve conflicts automatically. Please check 'git status'"))
                        return False
                
                # Step 4: Ready for commit
                self.logger.log("green", _("Step 4/4: Your changes are now ready to commit in the most recent branch!"))
                current_branch = most_recent_branch
                
            else:
                # No local changes, safe to switch automatically
                self.logger.log("cyan", _("No local changes detected. Switching to most recent branch: {0}").format(most_recent_branch))
                self._switch_to_branch_safely(most_recent_branch)
                current_branch = most_recent_branch
        else:
            # Already on most recent branch, try conflict-resistant pull
            pull_cmd = ["git", "pull", "origin", current_branch, "--strategy-option=theirs", "--no-edit"]
            pull_result = subprocess.run(pull_cmd, capture_output=True, text=True)
            
            if pull_result.returncode != 0:
                # Try alternative strategy
                self.logger.log("yellow", _("Standard pull failed, trying force update..."))
                try:
                    subprocess.run(["git", "fetch", "origin", current_branch], check=True)
                    subprocess.run(["git", "reset", "--hard", f"origin/{current_branch}"], check=True)
                    self.logger.log("green", _("Force-updated to latest {0}").format(current_branch))
                except subprocess.CalledProcessError:
                    self.logger.log("yellow", _("Could not update branch, continuing with current state"))
            else:
                self.logger.log("green", _("Successfully pulled latest changes"))
        
        # Check changes AFTER all operations
        has_changes = GitUtils.has_changes()

        # Handle commit message
        self.last_commit_type = None
        if self.args.commit_file:
            # Read commit message from file
            try:
                with open(self.args.commit_file, 'r', encoding='utf-8') as f:
                    commit_message = f.read().strip()
                if not commit_message:
                    self.logger.die("red", _("Commit message file is empty."))
                    return False
                self.logger.log("cyan", _("Using commit message from file: {0}").format(self.args.commit_file))
            except FileNotFoundError:
                self.logger.die("red", _("Commit message file not found: {0}").format(self.args.commit_file))
                return False
            except Exception as e:
                self.logger.die("red", _("Error reading commit message file: {0}").format(e))
                return False
        elif self.args.commit:
            commit_message = self.args.commit
        elif has_changes:
            commit_message = self.custom_commit_prompt()
            if not commit_message:
                self.logger.log("red", _("Commit message cannot be empty."))
                return False
        else:
            commit_message = ""
            
        # Ensure we have a message if there are changes
        if has_changes and not commit_message:
            self.logger.die("red", _("When using the '-b|--build' parameter and there are changes, the '-c|--commit' or '-F|--commit-file' parameter is also required."))
            return False

        if has_changes and commit_message:
            self.apply_auto_version_bump(commit_message, self.last_commit_type)

        # Different flows based on the package type
        if branch_type == "testing":
            if has_changes and commit_message:
                # Create or switch to dev-* branch for testing packages
                username = self.github_user_name or "unknown"  
                dev_branch = f"dev-{username}"
                self.logger.log("cyan", _("Creating/updating testing branch: {0}").format(dev_branch))
                try:
                    # Use the existing method that handles branch creation safely
                    if not self.ensure_user_branch_exists(dev_branch):
                        return False
                    current_branch = dev_branch
                    
                    # SYNC: Sync local dev branch with remote dev branch before commit
                    self.logger.log("cyan", _("Syncing local {0} with remote {0}...").format(dev_branch))
                    try:
                        # Fetch remote dev branch
                        subprocess.run(["git", "fetch", "origin", dev_branch], check=True)
                        
                        # Pull/merge remote dev branch into local dev branch
                        pull_result = subprocess.run(
                            ["git", "pull", "origin", dev_branch, "--no-edit"],
                            capture_output=True, text=True, check=False
                        )
                        
                        if pull_result.returncode == 0:
                            self.logger.log("green", _("Successfully synced with remote {0}").format(dev_branch))
                        else:
                            self.logger.log("yellow", _("Pull failed, trying rebase..."))
                            # Try rebase if pull fails
                            subprocess.run(["git", "rebase", f"origin/{dev_branch}"], check=True)
                            self.logger.log("green", _("Successfully rebased with remote {0}").format(dev_branch))
                            
                    except subprocess.CalledProcessError:
                        self.logger.log("yellow", _("Could not sync with remote {0}, continuing with local version").format(dev_branch))
                    
                    subprocess.run(["git", "add", "--all"], check=True)
                    self.logger.log("cyan", _("Committing changes with message:"))
                    self.logger.log("purple", commit_message)
                    subprocess.run(["git", "commit", "-m", commit_message], check=True)
                    subprocess.run(["git", "push", "origin", current_branch], check=True)
                    self.logger.log("green", _("Changes committed and pushed to {0} successfully!").format(self.logger.format_branch_name(current_branch)))
                except subprocess.CalledProcessError as e:
                    self.logger.log("red", _("Error during branch operations: {0}").format(e))
                    return False
            else:
                self.logger.log("yellow", _("No changes to commit, using current branch for package."))
            
            working_branch = current_branch
            
        else:  # stable/extra packages
            # Create or switch to dev-* branch for changes if necessary
            if has_changes and commit_message:
                username = self.github_user_name or "unknown"
                dev_branch = f"dev-{username}"
                self.logger.log("cyan", _("Creating/updating branch {0} for your changes").format(dev_branch))
                try:
                    # Use the existing method that handles branch creation safely
                    if not self.ensure_user_branch_exists(dev_branch):
                        return False
                    subprocess.run(["git", "add", "--all"], check=True)
                    self.logger.log("cyan", _("Committing changes with message:"))
                    self.logger.log("purple", commit_message)
                    subprocess.run(["git", "commit", "-m", commit_message], check=True)
                    subprocess.run(["git", "push", "-u", "origin", dev_branch], check=True)
                    self.logger.log("green", _("Changes committed and pushed to {0} successfully!").format(self.logger.format_branch_name(dev_branch)))
                    most_recent_branch = dev_branch
                except subprocess.CalledProcessError as e:
                    self.logger.log("red", _("Error in branch operations: {0}").format(e))
                    return False
            
            # AGGRESSIVE MERGE to main for stable/extra
            if most_recent_branch != "main" and most_recent_branch != "master":
                self.logger.log("cyan", _("Force merging {0} to main for stable/extra package").format(most_recent_branch))
                
                try:
                    # Switch to main
                    subprocess.run(["git", "checkout", "main"], check=True)
                    
                    # Force update main first
                    subprocess.run(["git", "fetch", "origin", "main"], check=True)
                    subprocess.run(["git", "reset", "--hard", "origin/main"], check=True)
                    
                    # Try different merge strategies
                    merge_strategies = [
                        ["git", "merge", f"{most_recent_branch}", "--strategy-option=theirs", "--no-edit"],
                        ["git", "merge", f"origin/{most_recent_branch}", "--strategy=ours", "--no-edit"],
                        ["git", "reset", "--hard", f"origin/{most_recent_branch}"]  # Nuclear option
                    ]
                    
                    merge_success = False
                    for i, merge_cmd in enumerate(merge_strategies):
                        try:
                            if i == 2:  # Nuclear option
                                self.logger.log("yellow", _("Using nuclear merge strategy (reset to source branch)"))
                            
                            subprocess.run(merge_cmd, check=True)
                            merge_success = True
                            break
                        except subprocess.CalledProcessError:
                            if i < len(merge_strategies) - 1:
                                self.logger.log("yellow", _("Merge strategy {0} failed, trying next...").format(i+1))
                                # Abort any partial merge before trying next strategy
                                subprocess.run(["git", "merge", "--abort"], capture_output=True, check=False)
                            continue
                    
                    if merge_success:
                        # Push successful merge
                        subprocess.run(["git", "push", "origin", "main", "--force"], check=True)
                        self.logger.log("green", _("Successfully merged {0} to main!").format(most_recent_branch))
                    else:
                        self.logger.log("red", _("All merge strategies failed"))
                        return False
                    
                except subprocess.CalledProcessError as e:
                    self.logger.log("yellow", _("Could not merge automatically: {0}").format(e))
                    # Abort any partial merge
                    subprocess.run(["git", "merge", "--abort"], capture_output=True, check=False)
                
            working_branch = "main"
        
        # Get package name
        package_name = GitUtils.get_package_name()
        if package_name in ["error2", "error3"]:
            error_msg = _("Error: PKGBUILD file not found.") if package_name == "error2" else _("Error: Package name not found in PKGBUILD.")
            self.logger.die("red", error_msg)
            return False

        self.show_build_summary(package_name, branch_type, working_branch)
        
        # Confirm package generation
        if not self.menu.confirm(_("Do you want to proceed with building the PACKAGE?")):
            self.logger.log("red", _("Package build cancelled."))
            return False
        
        repo_type = branch_type
        new_branch = working_branch if working_branch != "main" else ""
        
        # Trigger workflow
        return self.github_api.trigger_workflow(
            package_name, repo_type, new_branch, False, self.tmate_option, self.logger
        )
    
    def build_aur_package(self):
        """Triggers workflow to build an AUR package"""
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
        """Displays menu for reverting commits"""
        if not self.is_git_repo:
            self.logger.log("red", _("This operation is only available in git repositories."))
            return
        
        # Get current branch and username
        current_branch = GitUtils.get_current_branch()
        username = self.github_user_name or "unknown"
        my_branch = f"dev-{username}"
        
        # Check if user can revert on this branch
        if current_branch != "main" and current_branch != my_branch:
            self.logger.log("red", _("You can only revert commits on your own branch ({0}) or main branch.").format(my_branch))
            return
        
        # Determine revert options based on branch
        revert_options = []
        if current_branch == my_branch:
            # Own branch: both options available
            revert_options = [
                _("Revert (keep history)"),
                _("Reset (remove from history)"),
                _("Back")
            ]
            
            # Ask for revert type
            revert_result = self.menu.show_menu(
                _("Branch: {0} - Select revert method").format(current_branch), 
                revert_options
            )
            
            if revert_result is None or revert_result[0] == 2:  # Back
                return
            
            revert_method = "revert" if revert_result[0] == 0 else "reset"
        else:
            # Main branch: only revert available
            revert_method = "revert"
            self.logger.log("cyan", _("Main branch detected - only revert method available (safer for shared branch)"))
        
        # Get and display commit list
        commits = self.get_recent_commits(10)
        if not commits:
            self.logger.log("yellow", _("No commits found to revert."))
            return
        
        # Show commit selection menu
        commit_options = []
        for i, commit in enumerate(commits):
            short_hash = commit['hash'][:7]
            author = commit['author']
            date = commit['date']
            message = commit['message'][:60] + "..." if len(commit['message']) > 60 else commit['message']
            
            commit_options.append(f"{short_hash} - {author} - {date}\n    {message}")
        
        commit_options.append(_("Back"))
        
        # Show commit selection
        commit_result = self.menu.show_menu(
            _("Select commit to revert ({0})").format(revert_method), 
            commit_options
        )
        
        if commit_result is None or commit_result[0] == len(commits):  # Back
            return
        
        selected_commit = commits[commit_result[0]]
        
        # Show preview and confirm
        self.show_revert_preview(selected_commit, revert_method)

        confirm_result = self.menu.confirm(_("Do you want to proceed with this {0}?").format(revert_method))

        if not confirm_result:
            self.logger.log("yellow", _("Operation cancelled by user."))
            return

        # Execute revert/reset
        success = self.execute_revert(selected_commit, revert_method, current_branch)

        if success:
            # Get details from executed operation
            details = getattr(self, 'last_revert_details', {})
            
            # Show operation summary
            self.show_operation_summary(revert_method, selected_commit, details)
            
            # Clean up
            if hasattr(self, 'last_revert_details'):
                delattr(self, 'last_revert_details')
        else:
            self.logger.log("red", _("Failed to {0} commit.").format(revert_method))
            
    def get_recent_commits(self, count: int = 10) -> list:
        """Gets recent commits from current branch"""
        try:
            # Get commits with custom format
            # Format: hash|author|date|message
            result = subprocess.run(
                ["git", "log", f"-{count}", "--pretty=format:%H|%an|%ad|%s", "--date=short"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True
            )
            
            commits = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = line.split('|', 3)
                    if len(parts) == 4:
                        commits.append({
                            'hash': parts[0],
                            'author': parts[1],
                            'date': parts[2],
                            'message': parts[3]
                        })
            
            return commits
        except subprocess.CalledProcessError as e:
            self.logger.log("red", _("Error getting commit history: {0}").format(e))
            return []
        except Exception as e:
            self.logger.log("red", _("Unexpected error getting commits: {0}").format(e))
            return []
        
    def show_revert_preview(self, commit: dict, revert_method: str):
        """Shows preview of what will be reverted"""
        try:
            # Get commit details
            commit_hash = commit['hash']
            short_hash = commit_hash[:7]
            
            # Get current commit for comparison
            current_commit_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            )
            current_commit = current_commit_result.stdout.strip()[:7]
            
            # Prepare preview data
            preview_data = [
                (_("Target Commit Hash"), short_hash),
                (_("Author"), commit['author']),
                (_("Date"), commit['date']),
                (_("Message"), commit['message']),
                (_("Method"), revert_method.upper()),
            ]
            
            if revert_method == "revert":
                preview_data.append((_("Result"), _("Code will be restored to this commit's exact state")))
                preview_data.append((_("New Commit"), _("Will create new commit with restored state")))
                preview_data.append((_("History"), _("All commits remain in history (non-destructive)")))
                preview_data.append((_("Current Code"), f"From {current_commit} → To {short_hash}"))
            else:  # reset
                preview_data.append((_("Result"), _("Repository will be reset to this commit")))
                preview_data.append((_("History"), _("Commits after this will be removed from history")))
            
            # Show preview summary
            self.logger.display_summary(_("Revert Preview"), preview_data)
            
            # Show what will change (files that differ between current and target)
            if revert_method == "revert":
                try:
                    diff_result = subprocess.run(
                        ["git", "diff", "--name-status", commit_hash, "HEAD"],
                        stdout=subprocess.PIPE,
                        text=True,
                        check=True
                    )
                    
                    if diff_result.stdout.strip():
                        self.logger.log("cyan", _("Files that will be restored to target state:"))
                        diff_lines = diff_result.stdout.strip().split('\n')
                        for i, line in enumerate(diff_lines[:10]):
                            if line.strip():
                                status = line[0] if line else ""
                                filename = line[2:] if len(line) > 2 else ""
                                status_text = {"M": "Modified", "A": "Added", "D": "Deleted"}.get(status, status)
                                self.logger.log("white", f"  {status_text}: {filename}")
                        
                        if len(diff_lines) > 10:
                            self.logger.log("yellow", f"  ... and {len(diff_lines) - 10} more files")
                    else:
                        self.logger.log("yellow", _("No differences detected - code is already at target state"))
                except subprocess.CalledProcessError:
                    self.logger.log("yellow", _("Could not analyze file differences"))
            
        except subprocess.CalledProcessError as e:
            self.logger.log("yellow", _("Could not show commit details: {0}").format(e))
        except Exception as e:
            self.logger.log("yellow", _("Error showing preview: {0}").format(e))
            
    def execute_revert(self, commit: dict, revert_method: str, current_branch: str) -> bool:
        """Executes the revert or reset operation"""
        try:
            commit_hash = commit['hash']
            short_hash = commit_hash[:7]
            
            # Check if commit exists in remote
            remote_exists = self.check_commit_in_remote(commit_hash)
            
            self.logger.log("cyan", _("Executing {0} for commit {1}...").format(revert_method, short_hash))
            
            if revert_method == "revert":
                success = self._execute_revert_method(commit_hash, current_branch, remote_exists)
            else:  # reset
                success = self._execute_reset_method(commit_hash, current_branch, remote_exists)
            
            if success:
                # Get details if it was a reset operation
                details = getattr(self, 'last_operation_details', {})
                
                # Store details for caller
                self.last_revert_details = details
                
                # Clean up details
                if hasattr(self, 'last_operation_details'):
                    delattr(self, 'last_operation_details')
                
            return success
                
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip() if hasattr(e, 'stderr') and e.stderr else str(e)
            self.logger.log("red", _("Error during {0}: {1}").format(revert_method, error_msg))
            self._cleanup_revert_state()
            return False
        except Exception as e:
            self.logger.log("red", _("Unexpected error during {0}: {1}").format(revert_method, str(e)))
            return False

    def _execute_revert_method(self, commit_hash: str, current_branch: str, remote_exists: bool) -> bool:
        """Execute revert by restoring complete state from selected commit"""
        
        try:
            # Step 1: Get commit message for the new commit
            self.logger.log("cyan", _("Getting commit information..."))
            commit_message_result = subprocess.run(
                ["git", "log", "-1", "--pretty=format:%s", commit_hash],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            )
            original_message = commit_message_result.stdout.strip()
            
            # Step 2: Restore complete state from selected commit
            self.logger.log("cyan", _("Restoring code state from selected commit..."))
            subprocess.run(
                ["git", "checkout", commit_hash, "--", "."],
                check=True
            )
            
            # Step 3: Stage all changes
            self.logger.log("cyan", _("Staging restored files..."))
            subprocess.run(["git", "add", "."], check=True)
            
            # Step 4: Check if there are actually changes to commit
            status_result = subprocess.run(
                ["git", "status", "--porcelain"],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            )
            
            if not status_result.stdout.strip():
                self.logger.log("yellow", _("No changes detected - code is already at selected state"))
                return True
            
            # Step 5: Create new commit with restored state
            new_commit_message = f"Revert to: {original_message}\n\nThis restores the complete state from commit {commit_hash[:7]}."
            
            self.logger.log("cyan", _("Creating revert commit..."))
            subprocess.run(
                ["git", "commit", "-m", new_commit_message],
                check=True
            )
            
            self.logger.log("green", _("Revert completed successfully - code restored to selected commit state"))
            return self._push_revert_changes(current_branch, remote_exists)
            
        except subprocess.CalledProcessError as e:
            self.logger.log("red", _("Error during revert operation: {0}").format(e))
            self._cleanup_revert_state()
            return False
        except Exception as e:
            self.logger.log("red", _("Unexpected error during revert: {0}").format(e))
            return False

    def _execute_reset_method(self, commit_hash: str, current_branch: str, remote_exists: bool) -> bool:
        """Execute git reset"""
        self.logger.log("cyan", _("Resetting to previous commit..."))
        
        # Reset to the target commit itself (user selects where they want to be)
        reset_target = commit_hash
        subprocess.run(["git", "reset", "--hard", reset_target], check=True)
        
        # Handle push based on remote existence
        details = {}
        if remote_exists:
            self.logger.log("yellow", _("Commit exists in remote - force push required"))
            if self.menu.confirm(_("This will force push and rewrite remote history. Continue?")):
                self.logger.log("cyan", _("Force pushing changes..."))
                subprocess.run(["git", "push", "origin", current_branch, "--force"], check=True)
                self.logger.log("green", _("Reset completed and force pushed"))
                details['force_pushed'] = True
            else:
                self.logger.log("yellow", _("Reset completed locally only (remote unchanged)"))
                details['local_only'] = True
        else:
            self.logger.log("green", _("Reset completed (commit was only local)"))
            details['local_only'] = True

        # Store details for summary (will be called by execute_revert)
        self.last_operation_details = details
        return True

    def _has_changes_to_commit(self) -> bool:
        """Check if there are staged changes ready to commit"""
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            stdout=subprocess.PIPE,
            text=True,
            check=True
        )
        return bool(status_result.stdout.strip())

    def _skip_revert(self) -> bool:
        """Skip the current revert operation"""
        skip_result = subprocess.run(
            ["git", "revert", "--skip"],
            capture_output=True,
            text=True,
            check=False
        )
        
        if skip_result.returncode == 0:
            self.logger.log("green", _("Successfully skipped revert (no effective changes)"))
            return True
        else:
            self.logger.log("red", _("Failed to skip revert: {0}").format(
                skip_result.stderr.strip() if skip_result.stderr else "Unknown error"))
            self._cleanup_revert_state()
            return False

    def _continue_revert(self) -> bool:
        """Continue the revert after resolving conflicts"""
        try:
            continue_result = subprocess.run(
                ["git", "revert", "--continue"],
                capture_output=True,
                text=True,
                check=False,
                timeout=30
            )
            
            if continue_result.returncode == 0:
                self.logger.log("green", _("Revert completed successfully"))
                return True
            else:
                self.logger.log("red", _("Revert continue failed: {0}").format(
                    continue_result.stderr.strip() if continue_result.stderr else "Unknown error"))
                self._cleanup_revert_state()
                return False
                
        except subprocess.TimeoutExpired:
            self.logger.log("red", _("Revert continue timed out - aborting"))
            self._cleanup_revert_state()
            return False

    def _push_revert_changes(self, current_branch: str, remote_exists: bool) -> bool:
        """Push the revert changes if needed"""
        if remote_exists:
            self.logger.log("cyan", _("Pushing revert changes..."))
            push_result = subprocess.run(
                ["git", "push", "origin", current_branch],
                capture_output=True,
                text=True,
                check=False
            )
            
            if push_result.returncode == 0:
                self.logger.log("green", _("Revert changes pushed successfully"))
                return True
            else:
                self.logger.log("red", _("Failed to push revert: {0}").format(
                    push_result.stderr.strip() if push_result.stderr else "Unknown error"))
                return False
        else:
            self.logger.log("green", _("Revert completed (commit was only local)"))
            return True

    def _cleanup_revert_state(self):
        """Clean up any ongoing revert operation"""
        subprocess.run(["git", "revert", "--abort"], capture_output=True, check=False)
        subprocess.run(["git", "reset", "--abort"], capture_output=True, check=False)
        
    def show_operation_summary(self, operation_type: str, commit_info: dict, details: dict = None):
        """Shows operation summary with emojis and waits for user input"""
        
        # Get current commit info for summary
        try:
            current_commit = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            ).stdout.strip()
            
            current_message = subprocess.run(
                ["git", "log", "-1", "--pretty=format:%s"],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            ).stdout.strip()
        except:
            current_commit = "unknown"
            current_message = "unknown"
        
        # Get file changes if available
        try:
            if operation_type in ["revert", "reset"]:
                # Show what changed in the last commit (our operation)
                diff_result = subprocess.run(
                    ["git", "diff", "--name-status", "HEAD~1", "HEAD"],
                    stdout=subprocess.PIPE,
                    text=True,
                    check=True
                )
                
                changed_files = []
                if diff_result.stdout.strip():
                    for line in diff_result.stdout.strip().split('\n'):
                        if line:
                            status = line[0]
                            filename = line[2:] if len(line) > 2 else ""
                            status_emoji = {"M": "📝", "A": "➕", "D": "❌"}.get(status, "📄")
                            changed_files.append(f"    {status_emoji} {filename}")
            else:
                changed_files = []
        except:
            changed_files = []
        
        # Build summary message
        summary_lines = []
        
        if operation_type == "revert":
            summary_lines.extend([
                f"🔄 **{_('REVERT COMPLETED SUCCESSFULLY!')}**",
                f"",
                f"✅ {_('Code restored to commit')}: {commit_info['hash'][:7]}",
                f"📝 {_('Target commit')}: \"{commit_info['message']}\"",
                f"🆕 {_('New commit created')}: {current_commit}",
                f"💬 {_('New commit message')}: \"{current_message}\"",
            ])
            
            if changed_files:
                summary_lines.extend([
                    f"",
                    f"📁 **{_('Files restored')} ({len(changed_files)}):**"
                ])
                summary_lines.extend(changed_files[:10])
                if len(changed_files) > 10:
                    summary_lines.append(f"    ... {_('and {0} more files').format(len(changed_files) - 10)}")
        
        elif operation_type == "reset":
            summary_lines.extend([
                f"⚡ **{_('RESET COMPLETED SUCCESSFULLY!')}**",
                f"",
                f"🎯 {_('Repository reset to commit')}: {commit_info['hash'][:7]}",
                f"📝 {_('Target commit')}: \"{commit_info['message']}\"",
                f"🗑️ {_('History after this commit was removed')}",
                f"💾 {_('Current HEAD')}: {current_commit}",
            ])
            
            if details and details.get('force_pushed'):
                summary_lines.append(f"🌐 {_('Changes force-pushed to remote')}")
            elif details and details.get('local_only'):
                summary_lines.append(f"🏠 {_('Reset completed locally only')}")
        
        # Add final instruction
        summary_lines.extend([
            f"",
            f"📋 **{_('Operation completed successfully!')}**",
            f"🏠 {_('All changes have been saved to your repository')}"
        ])
        
        # Convert to string and show
        summary_text = '\n'.join(summary_lines)
        
        # Show summary with menu system (waits for Enter)
        self.menu.show_menu(
            f"✅ {_(operation_type.upper() + ' COMPLETED')}",
            [_("Press Enter to return to menu")],
            additional_content=summary_text
        )

    def check_commit_in_remote(self, commit_hash: str) -> bool:
        """Checks if commit exists in remote repository"""
        try:
            # Check if commit exists in any remote branch
            result = subprocess.run(
                ["git", "branch", "-r", "--contains", commit_hash],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False
            )
            
            # If command succeeds and has output, commit exists in remote
            return result.returncode == 0 and bool(result.stdout.strip())
        except Exception:
            # If we can't determine, assume it exists (safer approach)
            return True
    
    def run(self):
        """Executes main program flow"""
        # Check command line arguments
        if self.args.commit and not self.args.build:
            # Only commit/push
            self.commit_and_push()
        
        elif self.args.build:
            # Perform commit (if -c is present) and generate package
            self.commit_and_generate_package()
        
        elif self.args.aur:
            # Build AUR package
            self.build_aur_package()
        
        else:
            # No specific argument, show interactive menu
            self.main_menu()
            
    def pull_latest_code_menu(self):
        """Pulls the latest code to user's own branch while maintaining isolation"""
        if not self.is_git_repo:
            self.logger.log("red", _("This operation is only available in git repositories."))
            return False
        
        try:
            self.logger.log("cyan", _("Checking for latest updates..."))
            
            # Get initial state for comparison
            try:
                initial_commit = subprocess.run(
                    ["git", "rev-parse", "HEAD"], 
                    stdout=subprocess.PIPE, text=True, check=True
                ).stdout.strip()
            except:
                initial_commit = None
            
            # CLEANUP - resolve any problematic state
            try:
                subprocess.run(["git", "rebase", "--abort"], capture_output=True, check=False)
                subprocess.run(["git", "merge", "--abort"], capture_output=True, check=False)
                subprocess.run(["git", "cherry-pick", "--abort"], capture_output=True, check=False)
                subprocess.run(["git", "am", "--abort"], capture_output=True, check=False)
            except:
                pass
            
            # Fetch latest changes
            self.logger.log("cyan", _("Fetching latest changes from remote..."))
            subprocess.run(["git", "fetch", "--all", "--prune", "--force"], check=True)
            
            # Get current state
            current_branch = GitUtils.get_current_branch()
            has_changes = GitUtils.has_changes()
            username = self.github_user_name or "unknown"
            my_branch = f"dev-{username}"
            
            # Find most recent branch
            most_recent_branch = self.get_most_recent_branch()
            
            self.logger.log("cyan", _("Current branch: {0}").format(self.logger.format_branch_name(current_branch)))
            self.logger.log("green", _("Most recent branch available: {0}").format(self.logger.format_branch_name(most_recent_branch)))
            self.logger.log("cyan", _("Your target branch: {0}").format(self.logger.format_branch_name(my_branch)))
            
            # ROBUST WORKFLOW: Always ensure user works in their own branch
            if current_branch != my_branch:
                self.logger.log("yellow", _("You're not in your own branch. Moving to {0}...").format(my_branch))
                
                # Ensure user's branch exists, create if needed
                if not self.ensure_user_branch_exists(my_branch):
                    self.logger.log("red", _("Failed to create/access your branch."))
                    return False
                
                if has_changes:
                    # Ask user what to do with local changes
                    self.logger.log("yellow", "")
                    self.logger.log("yellow", "⚠️  " + _("You have uncommitted local changes!"))
                    self.logger.log("cyan", "")
                    self.logger.log("cyan", _("What do you want to do?"))
                    self.logger.log("green", _("  [1] Keep my changes and merge with remote (DEFAULT - Git standard behavior)"))
                    self.logger.log("cyan", _("      Your local edits will be preserved and merged with remote code"))
                    self.logger.log("red", _("  [2] ⚠️  DISCARD my changes and use only remote version"))
                    self.logger.log("red", _("      ⚠️  WARNING: You will LOSE all your uncommitted local changes!"))
                    self.logger.log("cyan", "")

                    choice = input(_("Choose option [1/2] (press Enter for default=1): ")).strip()

                    # Default to option 1 if user just presses Enter
                    if not choice:
                        choice = "1"

                    if choice == "2":
                        # User wants to discard local changes
                        self.logger.log("yellow", _("Discarding local changes and using remote version..."))
                        subprocess.run(["git", "reset", "--hard", "HEAD"], check=True)
                        subprocess.run(["git", "clean", "-fd"], check=True)
                        subprocess.run(["git", "checkout", my_branch], check=True)
                    else:
                        # User wants to keep local changes (default behavior)
                        # Stash → Switch → Apply workflow
                        self.logger.log("cyan", _("Preserving your changes while switching to your branch..."))
                        stash_message = f"auto-preserve-changes-pull-to-{my_branch}"
                        stash_result = subprocess.run(
                            ["git", "stash", "push", "-u", "-m", stash_message],
                            capture_output=True, text=True, check=False
                        )

                        if stash_result.returncode != 0:
                            self.logger.log("red", _("Failed to stash changes. Cannot proceed safely."))
                            return False

                        # Switch to user's branch
                        subprocess.run(["git", "checkout", my_branch], check=True)

                        # Apply stashed changes
                        pop_result = subprocess.run(["git", "stash", "pop"], capture_output=True, text=True, check=False)
                        if pop_result.returncode != 0:
                            self.logger.log("yellow", _("⚠️  Conflicts detected while restoring your changes!"))

                            # Use enhanced conflict resolver
                            from .conflict_resolver import ConflictResolver
                            from .config import CONFLICT_RESOLUTION_AUTO_ACCEPT_NEWER

                            resolver = ConflictResolver(
                                self.logger,
                                self.menu,
                                strategy="interactive",
                                auto_accept_newer=CONFLICT_RESOLUTION_AUTO_ACCEPT_NEWER
                            )

                            # Determine the branches involved
                            # current_branch is where we restored the stash (user's branch)
                            # incoming is most_recent_branch (from remote)
                            if not resolver.resolve(current_branch=my_branch, incoming_branch=most_recent_branch):
                                self.logger.log("red", _("Failed to resolve conflicts"))
                                return False
                else:
                    # No changes, safe to switch
                    subprocess.run(["git", "checkout", my_branch], check=True)
            
            # Now we're guaranteed to be in user's own branch
            current_branch = my_branch
            
            # MERGE latest code TO user's branch (not switch FROM user's branch)
            if most_recent_branch != my_branch:
                self.logger.log("cyan", _("Merging latest code from {0} into your branch...").format(most_recent_branch))
                
                # Try different merge strategies
                merge_strategies = [
                    (["git", "merge", f"origin/{most_recent_branch}", "--strategy-option=theirs", "--no-edit"], 
                    _("Using automatic merge strategy")),
                    (["git", "rebase", f"origin/{most_recent_branch}"], 
                    _("Using rebase strategy")),
                    (["git", "reset", "--hard", f"origin/{most_recent_branch}"], 
                    _("Using force update strategy"))
                ]
                
                merge_success = False
                for i, (merge_cmd, strategy_desc) in enumerate(merge_strategies):
                    try:
                        if i == 2:  # Force update strategy
                            self.logger.log("yellow", strategy_desc)
                        else:
                            self.logger.log("cyan", strategy_desc)
                        
                        subprocess.run(merge_cmd, check=True)
                        merge_success = True
                        break
                    except subprocess.CalledProcessError:
                        if i < len(merge_strategies) - 1:
                            self.logger.log("yellow", _("Strategy failed, trying next approach..."))
                            # Abort any partial operation
                            subprocess.run(["git", "merge", "--abort"], capture_output=True, check=False)
                            subprocess.run(["git", "rebase", "--abort"], capture_output=True, check=False)
                        continue
                
                if not merge_success:
                    self.logger.log("red", _("All merge strategies failed. Manual intervention may be needed."))
                    return False
                
                self.logger.log("green", _("Successfully merged latest code into your branch!"))
            else:
                # User's branch is already the most recent, just update it
                self.logger.log("cyan", _("Your branch is the most recent. Updating from remote..."))
                try:
                    subprocess.run(["git", "pull", "origin", my_branch, "--strategy-option=theirs", "--no-edit"], check=True)
                    self.logger.log("green", _("Successfully updated your branch"))
                except subprocess.CalledProcessError:
                    try:
                        subprocess.run(["git", "fetch", "origin", my_branch], check=True)
                        subprocess.run(["git", "reset", "--hard", f"origin/{my_branch}"], check=True)
                        self.logger.log("green", _("Force-updated your branch"))
                    except subprocess.CalledProcessError:
                        self.logger.log("yellow", _("Could not update branch"))
            
            # Get final state for comparison
            try:
                final_commit = subprocess.run(
                    ["git", "rev-parse", "HEAD"], 
                    stdout=subprocess.PIPE, text=True, check=True
                ).stdout.strip()
            except:
                final_commit = None
            
            # Generate changes summary
            changes_summary = self.get_update_changes_summary(initial_commit, final_commit, my_branch)
            
            # CRITICAL: Check for merge conflicts using enhanced resolver
            from .conflict_resolver import ConflictResolver
            from .config import CONFLICT_RESOLUTION_AUTO_ACCEPT_NEWER

            resolver = ConflictResolver(
                self.logger,
                self.menu,
                strategy="interactive",
                auto_accept_newer=CONFLICT_RESOLUTION_AUTO_ACCEPT_NEWER
            )

            if resolver.has_conflicts():
                self.logger.log("yellow", _("Merge conflicts detected after pull"))

                # Use enhanced interactive conflict resolution
                if not resolver.resolve(current_branch=my_branch, incoming_branch=most_recent_branch):
                    self.logger.log("red", _("Failed to resolve conflicts"))
                    return False

                self.logger.log("green", _("✓ All conflicts resolved successfully"))
            else:
                self.logger.log("green", _("✓ No conflicts detected"))

            # Show summary without clearing screen
            if changes_summary:
                self.logger.log("green", "")
                self.logger.log("green", "═" * 70)
                self.logger.log("green", _("PULL COMPLETED - SUMMARY OF CHANGES"))
                self.logger.log("green", "═" * 70)
                # Split summary into lines and log each one
                summary_lines = changes_summary.split('\n')
                for line in summary_lines:
                    if line.strip():
                        self.logger.log("cyan", line)
                self.logger.log("green", "═" * 70)
            else:
                self.logger.log("green", _("✓ Update completed successfully!"))

            # Wait for user to see the result before continuing
            self.logger.log("yellow", "")
            input(_("Press Enter to return to main menu..."))
            return True
            
        except Exception as e:
            self.logger.log("red", _("✗ Error during update: {0}").format(str(e)))
            return False
        
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
