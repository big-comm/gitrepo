#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# build_package.py - Main class for package management

import sys
import os
import argparse
import subprocess
from rich.console import Console
from rich.prompt import Prompt
from datetime import datetime
from translation_utils import _

from config import (
    APP_NAME, APP_DESC, VERSION, DEFAULT_ORGANIZATION, 
    VALID_ORGANIZATIONS, VALID_BRANCHES
)
from logger import RichLogger
from git_utils import GitUtils
from github_api import GitHubAPI
from menu_system import MenuSystem

class BuildPackage:
    """Main class for package management"""
    
    def __init__(self):
        self.args = self.parse_arguments()
        self.logger = RichLogger(not self.args.nocolor)
        self.menu = MenuSystem(self.logger)
        self.organization = self.args.organization or DEFAULT_ORGANIZATION
        self.repo_workflow = f"{self.organization}/build-package"
        self.console = Console()  # Add console object for colorful prompts
        
        # Check if it's a Git repository
        self.is_git_repo = GitUtils.is_git_repo()
        
        # Setup logger
        self.logger.setup_log_file(GitUtils.get_repo_name)
        
        # Configure program header
        self.logger.draw_app_header()
        
        # Configure environment
        self.setup_environment()
    
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
        """Parses command line arguments"""
        parser = argparse.ArgumentParser(
            description=f"{APP_NAME} v{VERSION} - {APP_DESC}",
            formatter_class=argparse.RawDescriptionHelpFormatter
        )
        
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
        
        parser.add_argument("-a", "--aur",
                           help=_("Build AUR package"))
        
        parser.add_argument("-n", "--nocolor", action="store_true",
                           help=_("Suppress color printing"))
        
        parser.add_argument("-V", "--version", action="store_true",
                           help=_("Print application version"))
        
        parser.add_argument("-t", "--tmate", action="store_true",
                           help=_("Enable tmate for debugging"))
        
        # Don't manually add "-h/--help" argument as argparse already adds it
        
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
        version_text.append(f"{APP_NAME} v{VERSION}\n", style="bold cyan")
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
    
    def custom_commit_prompt(self):
        """Gets commit message from user"""
        # Show prompt in cyan
        print("\033[1;36m" + _("Enter commit message: ") + "\033[0m", end="")
        
        # Capture user input
        commit_message = input()
        
        return commit_message
    
    def commit_and_push(self):
        """Performs commit on a new dev branch with timestamp"""
        if not self.is_git_repo:
            self.logger.die("red", _("This option is only available in git repositories."))
            return False
        
        # Ensure dev branch exists
        self.ensure_dev_branch_exists()
        
        # Get current branch
        current_branch = GitUtils.get_current_branch()
        
        # If on main branch, we need to be careful
        if current_branch == "main" or current_branch == "master":
            self.logger.log("yellow", _("WARNING: You are on main branch. Commits should not be made directly on main!"))
        
        # Pull latest changes first - always try to get most recent code
        if not GitUtils.git_pull(self.logger):
            if not self.menu.confirm(_("Failed to pull changes. Do you want to continue anyway?")):
                self.logger.log("red", _("Operation cancelled by user."))
                return False

        # Check if there are changes AFTER pulling
        has_changes = GitUtils.has_changes()

        # Handle commit message based on if we have changes and args
        if self.args.commit:
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
            self.menu.show_menu(_("No Changes to Commit\n"), [_("Press Enter to return to main menu")])
            return True
        
        # ALWAYS create new dev branch with timestamp
        timestamp = datetime.now().strftime("%y.%m.%d-%H%M")
        dev_branch = f"dev-{timestamp}"
        
        # Create and switch to new dev branch
        self.logger.log("cyan", _("Creating new branch: {0}").format(dev_branch))
        try:
            subprocess.run(["git", "checkout", "-b", dev_branch], check=True)
        except subprocess.CalledProcessError as e:
            self.logger.log("red", _("Error creating dev branch: {0}").format(e))
            return False
        
        # Add and commit changes to dev branch
        try:
            subprocess.run(["git", "add", "--all"], check=True)
            subprocess.run(["git", "commit", "-m", commit_message], check=True)
        except subprocess.CalledProcessError as e:
            self.logger.log("red", _("Error committing changes: {0}").format(e))
            return False
        
        # Push dev branch to remote
        try:
            subprocess.run(["git", "push", "-u", "origin", dev_branch], check=True)
        except subprocess.CalledProcessError as e:
            self.logger.log("red", _("Error pushing to remote: {0}").format(e))
            return False
        
        self.logger.log("green", _("Changes committed and pushed to {0} branch successfully!").format(self.logger.format_branch_name(dev_branch)))
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
        """Determines which branch (main or a dev-*) has the most recent commit"""
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
            
            all_branches = []
            for line in result.stdout.strip().split('\n'):
                branch = line.strip().replace('* ', '').replace('remotes/origin/', '')
                # Filter for main and dev branches
                if branch == "main" or branch == "master" or branch.startswith('dev-'):
                    if branch not in all_branches:
                        all_branches.append(branch)
        except subprocess.CalledProcessError:
            self.logger.log("yellow", _("Warning: Failed to get branch list."))
            return "main"  # Default to main if we can't get branch list
        
        if not all_branches:
            return "main"  # If no branches found, default to main
        
        # Find the most recent commit date for each branch
        most_recent_branch = "main"
        most_recent_timestamp = 0
        
        for branch in all_branches:
            try:
                # Get the timestamp of the latest commit in this branch
                cmd = ["git", "log", "-1", "--format=%at", f"origin/{branch}"]
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                
                if result.returncode == 0 and result.stdout.strip():
                    timestamp = int(result.stdout.strip())
                    if timestamp > most_recent_timestamp:
                        most_recent_timestamp = timestamp
                        most_recent_branch = branch
            except (subprocess.CalledProcessError, ValueError):
                # If we can't get timestamp, just continue
                continue
        
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
        
        # AUTOMATION: Switch to most recent branch if needed with conflict-resistant pull
        if most_recent_branch != current_branch:
            self.logger.log("cyan", _("Switching to the most recent branch: {0}").format(most_recent_branch))
            
            try:
                # Simple checkout - conflicts should be resolved now
                subprocess.run(["git", "checkout", most_recent_branch], check=True)
                
                # Conflict-resistant pull strategy
                pull_cmd = ["git", "pull", "origin", most_recent_branch, "--strategy-option=theirs", "--no-edit"]
                pull_result = subprocess.run(pull_cmd, capture_output=True, text=True)
                
                if pull_result.returncode != 0:
                    # If pull fails, try alternative strategies
                    self.logger.log("yellow", _("Standard pull failed, trying force strategy..."))
                    
                    # Try fetch + reset strategy
                    subprocess.run(["git", "fetch", "origin", most_recent_branch], check=True)
                    subprocess.run(["git", "reset", "--hard", f"origin/{most_recent_branch}"], check=True)
                    self.logger.log("green", _("Force-updated to latest {0}").format(most_recent_branch))
                else:
                    self.logger.log("green", _("Successfully updated to latest {0}").format(most_recent_branch))
                
                current_branch = most_recent_branch
                
            except subprocess.CalledProcessError as e:
                self.logger.log("yellow", _("Could not switch branches automatically: {0}").format(e))
                self.logger.log("yellow", _("Continuing with current branch: {0}").format(current_branch))
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
        if self.args.commit:
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
            self.logger.die("red", _("When using the '-b|--build' parameter and there are changes, the '-c|--commit' parameter is also required."))
            return False

        # Different flows based on the package type
        if branch_type == "testing":
            if has_changes and commit_message:
                # Create a new dev-* branch for testing packages
                timestamp = datetime.now().strftime("%y.%m.%d-%H%M")
                dev_branch = f"dev-{timestamp}"
                self.logger.log("cyan", _("Creating new testing branch: {0}").format(dev_branch))
                try:
                    subprocess.run(["git", "checkout", "-b", dev_branch], check=True)
                    current_branch = dev_branch
                    
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
            # Create temporary dev-* branch for changes if necessary
            if has_changes and commit_message:
                timestamp = datetime.now().strftime("%y.%m.%d-%H%M")
                dev_branch = f"dev-{timestamp}"
                self.logger.log("cyan", _("Creating temporary branch {0} for your changes").format(dev_branch))
                try:
                    subprocess.run(["git", "checkout", "-b", dev_branch], check=True)
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
                        ["git", "merge", f"origin/{most_recent_branch}", "--strategy-option=theirs", "--no-edit"],
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
        
        if not self.menu.confirm(_("Do you want to proceed with building the PACKAGE?")):
            self.logger.log("red", _("Package build cancelled."))
            return False
        
        # Create branch and push if in a Git repository
        new_branch = ""
        if self.is_git_repo:
            new_branch = GitUtils.create_branch_and_push("dev", self.logger)
        
        # Trigger workflow
        return self.github_api.trigger_workflow(
            aur_package_name, "aur", new_branch, True, self.tmate_option, self.logger
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
        """Displays interactive main menu"""
        while True:
            if self.is_git_repo:
                options = [
                    _("Commit and push"),
                    _("Pull latest"),
                    _("Generate package (commit + branch + build)"),
                    _("Build AUR package"),
                    _("Advanced menu"),
                    _("Exit")
                ]
            else:
                options = [
                    _("Build AUR package"),
                    _("Exit")
                ]
            
            result = self.menu.show_menu(_("Main Menu"), options)
            if result is None:
                self.logger.log("yellow", _("Operation cancelled by user."))
                return
            
            choice, ignore = result
            
            if self.is_git_repo:
                if choice == 0:  # Commit and push
                    # Check changes before asking for message
                    if not GitUtils.has_changes():
                        self.menu.show_menu(_("No Changes to Commit\n"), [_("Press Enter to return to main menu")])
                        continue
                    
                    # Pull latest changes
                    if not GitUtils.git_pull(self.logger):
                        if not self.menu.confirm(_("Failed to pull changes. Do you want to continue anyway?")):
                            continue
                    
                    # Only ask for message if there are changes
                    commit_message = self.custom_commit_prompt()
                    if not commit_message:
                        self.logger.log("red", _("Commit message cannot be empty."))
                        continue
                    
                    self.args.commit = commit_message
                    self.commit_and_push()
                    return
                
                elif choice == 1:  # Pull latest
                    self.pull_latest_code_menu()
                    continue
                
                elif choice == 2:  # Generate package
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
                    
                    self.tmate_option = (debug_result[0] == 1)  # Yes = index 1
                    
                    # Get commit message if there are changes
                    has_changes = GitUtils.has_changes()
                    commit_message = ""

                    if has_changes:
                        commit_message = self.custom_commit_prompt()
                        if not commit_message:
                            self.logger.log("red", _("Commit message cannot be empty."))
                            continue
                    else:
                        self.logger.log("yellow", _("No changes to commit, proceeding with package generation."))
                    
                    self.args.build = branch_type
                    self.args.commit = commit_message
                    self.commit_and_generate_package()
                    return
                
                elif choice == 3:  # Build AUR package
                    # Enable or disable tmate for debug
                    debug_result = self.menu.show_menu(_("Enable TMATE debug session?"), [_("No"), _("Yes")])
                    if debug_result is None:
                        continue
                    
                    self.tmate_option = (debug_result[0] == 1)  # Yes = index 1
                    
                    self.args.aur = None  # Force package name request
                    self.build_aur_package()
                    return
                
                elif choice == 4:  # Advanced menu
                    self.advanced_menu()
                    continue
                
                elif choice == 5:  # Exit
                    self.logger.log("yellow", _("Exiting script. No action was performed."))
                    return
            else:
                if choice == 0:  # Build AUR package
                    # Enable or disable tmate for debug
                    debug_result = self.menu.show_menu(_("Enable TMATE debug session?"), [_("No"), _("Yes")])
                    if debug_result is None:
                        continue
                    
                    self.tmate_option = (debug_result[0] == 1)  # Yes = index 1
                    
                    self.args.aur = None  # Force package name request
                    self.build_aur_package()
                    return
                
                elif choice == 1:  # Exit
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
            _("Back")
        ]
        
        while True:
            result = self.menu.show_menu(_("Advanced Menu"), options)
            if result is None or result[0] == 5:  # None ou "Back"
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
        """Pulls the latest code from the most recent branch - shows detailed changes"""
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
            
            # NUCLEAR CLEANUP - resolve qualquer estado problemático
            try:
                subprocess.run(["git", "rebase", "--abort"], capture_output=True, check=False)
                subprocess.run(["git", "merge", "--abort"], capture_output=True, check=False)
                subprocess.run(["git", "cherry-pick", "--abort"], capture_output=True, check=False)
                subprocess.run(["git", "am", "--abort"], capture_output=True, check=False)
            except:
                pass
            
            # Fetch - SEMPRE funciona
            self.logger.log("cyan", _("Fetching latest changes from remote..."))
            subprocess.run(["git", "fetch", "--all", "--prune", "--force"], check=True)
            
            # Get current state
            current_branch = GitUtils.get_current_branch()
            has_changes = GitUtils.has_changes()
            
            # Find most recent branch
            most_recent_branch = self.get_most_recent_branch()
            
            self.logger.log("green", _("Most recent branch: {0}").format(self.logger.format_branch_name(most_recent_branch)))
            
            # Backup mudanças locais se existirem
            if has_changes:
                self.logger.log("cyan", _("Backing up your local changes..."))
                subprocess.run(["git", "stash", "push", "-u", "-m", "auto-backup-pull-latest"], check=False)
            
            # ESTRATÉGIA AGRESSIVA: Sempre funciona
            self.logger.log("cyan", _("Updating to latest code from {0}...").format(self.logger.format_branch_name(most_recent_branch)))
            
            # Force checkout + reset - SEMPRE funciona
            subprocess.run(["git", "checkout", "-B", most_recent_branch, f"origin/{most_recent_branch}"], check=True)
            
            # Get final state for comparison
            try:
                final_commit = subprocess.run(
                    ["git", "rev-parse", "HEAD"], 
                    stdout=subprocess.PIPE, text=True, check=True
                ).stdout.strip()
            except:
                final_commit = None
            
            # Show what changed
            self.show_update_changes(initial_commit, final_commit, most_recent_branch)
            
            # Tentar restaurar mudanças locais
            if has_changes:
                self.logger.log("cyan", _("Attempting to restore your local changes..."))
                result = subprocess.run(["git", "stash", "pop"], capture_output=True, text=True, check=False)
                if result.returncode == 0:
                    self.logger.log("green", _("✓ Local changes restored successfully."))
                else:
                    self.logger.log("yellow", _("! Local changes backed up in stash (some conflicts may exist)."))
                    self.logger.log("yellow", _("Use 'git stash list' and 'git stash apply' manually if needed."))
            
            # Show completion
            self.menu.show_menu(_("✓ Update completed successfully!\n"), [_("Press Enter to return to main menu")])
            return True
            
        except Exception as e:
            self.logger.log("red", _("✗ Error during update: {0}").format(str(e)))
            self.logger.log("yellow", _("Repository may be in inconsistent state. Check manually."))
            return False

    def show_update_changes(self, initial_commit, final_commit, branch_name):
        """Shows detailed information about what was updated"""
        if not initial_commit or not final_commit:
            self.logger.log("green", _("✓ Successfully updated to latest {0}!").format(self.logger.format_branch_name(branch_name)))
            return
        
        if initial_commit == final_commit:
            self.logger.log("green", _("✓ Already up to date with {0}").format(self.logger.format_branch_name(branch_name)))
            return
        
        try:
            # Show new commits
            self.logger.log("green", _("✓ Successfully updated to latest {0}!").format(self.logger.format_branch_name(branch_name)))
            
            # Get commit range info
            commits_result = subprocess.run(
                ["git", "log", "--oneline", f"{initial_commit}..{final_commit}"],
                stdout=subprocess.PIPE, text=True, check=True
            )
            
            if commits_result.stdout.strip():
                commit_lines = commits_result.stdout.strip().split('\n')
                commit_count = len(commit_lines)
                
                self.logger.log("cyan", _("📄 New commits ({0}):").format(commit_count))
                for line in commit_lines[:5]:  # Show max 5 commits
                    self.logger.log("white", f"  • {line}")
                
                if commit_count > 5:
                    self.logger.log("white", f"  ... and {commit_count - 5} more commits")
            
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
                self.logger.log("cyan", _("📁 Files changed ({0}):").format(total_files))
                
                # Show by type
                if 'A' in changes:
                    self.logger.log("green", f"  ✓ Added: {len(changes['A'])} files")
                    for f in changes['A'][:3]:
                        self.logger.log("white", f"    + {f}")
                    if len(changes['A']) > 3:
                        self.logger.log("white", f"    + ... and {len(changes['A']) - 3} more")
                
                if 'M' in changes:
                    self.logger.log("yellow", f"  ! Modified: {len(changes['M'])} files")
                    for f in changes['M'][:3]:
                        self.logger.log("white", f"    ~ {f}")
                    if len(changes['M']) > 3:
                        self.logger.log("white", f"    ~ ... and {len(changes['M']) - 3} more")
                
                if 'D' in changes:
                    self.logger.log("red", f"  ✗ Deleted: {len(changes['D'])} files")
                    for f in changes['D'][:3]:
                        self.logger.log("white", f"    - {f}")
                    if len(changes['D']) > 3:
                        self.logger.log("white", f"    - ... and {len(changes['D']) - 3} more")
                
                if 'R' in changes:
                    self.logger.log("cyan", f"  → Renamed: {len(changes['R'])} files")
            
            # Show stats
            stats_result = subprocess.run(
                ["git", "diff", "--stat", initial_commit, final_commit],
                stdout=subprocess.PIPE, text=True, check=True
            )
            
            if stats_result.stdout.strip():
                stats_lines = stats_result.stdout.strip().split('\n')
                if len(stats_lines) > 1:
                    summary_line = stats_lines[-1]
                    self.logger.log("cyan", f"📊 {summary_line}")
                    
        except Exception as e:
            self.logger.log("green", _("✓ Successfully updated to latest {0}!").format(self.logger.format_branch_name(branch_name)))
            self.logger.log("yellow", _("! Could not show detailed changes: {0}").format(str(e)))