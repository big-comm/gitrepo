#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# build_package.py - Main class for package management
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import os
import sys
import argparse
import subprocess
from rich.console import Console
from rich.prompt import Prompt
from datetime import datetime

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
                self.logger.die("red", f"Dependency '{dep}' not found. Please install it before continuing.")
    
    def parse_arguments(self) -> argparse.Namespace:
        """Parses command line arguments"""
        parser = argparse.ArgumentParser(
            description=f"{APP_NAME} v{VERSION} - {APP_DESC}",
            formatter_class=argparse.RawDescriptionHelpFormatter
        )
        
        parser.add_argument("-o", "--org", "--organization", 
                           dest="organization", 
                           help="Configure GitHub organization (default: big-comm)",
                           choices=VALID_ORGANIZATIONS,
                           default=DEFAULT_ORGANIZATION)
        
        parser.add_argument("-b", "--build",
                           help="Commit/push and generate package",
                           choices=VALID_BRANCHES)
        
        parser.add_argument("-c", "--commit",
                           help="Just commit/push with the specified message")
        
        parser.add_argument("-a", "--aur",
                           help="Build AUR package")
        
        parser.add_argument("-n", "--nocolor", action="store_true",
                           help="Suppress color printing")
        
        parser.add_argument("-V", "--version", action="store_true",
                           help="Print application version")
        
        parser.add_argument("-t", "--tmate", action="store_true",
                           help="Enable tmate for debugging")
        
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
        version_text.append(f"Copyright (C) 2024-2025 BigCommunity Team\n\n", style="blue")
        version_text.append("""
    This is free software: you are free to modify and redistribute it.
    """, style="white")
        version_text.append(f"{APP_NAME}", style="cyan")
        version_text.append(""" is provided to you under the """, style="white")
        version_text.append("MIT License", style="yellow")
        version_text.append(""", and
    includes open source software under a variety of other licenses.
    You can read instructions about how to download and build for yourself
    the specific source code used to create this copy.
    """, style="white")
        version_text.append("This program comes with absolutely NO warranty.", style="red")
        
        panel = Panel(
            version_text,
            box=ROUNDED,
            border_style="blue",
            padding=(1, 2)
        )
        
        console.print(panel)
    
    def commit_and_push(self):
        """Performs only commit and push of changes"""
        if not self.is_git_repo:
            self.logger.die("red", "This option is only available in git repositories.")
            return False
        
        # Check if there are changes
        if not GitUtils.has_changes():
            self.logger.log("yellow", "No changes to commit. No action will be performed.")
            return True
        
        # Pull latest changes before committing
        if not GitUtils.git_pull(self.logger):
            if not self.menu.confirm("Failed to pull changes. Do you want to continue anyway?"):
                self.logger.log("red", "Operation cancelled by user.")
                return False
        
        # Ask for commit message if not specified
        commit_message = self.args.commit
        if not commit_message:
            commit_message = Prompt.ask("Enter commit message")
            if not commit_message:
                self.logger.die("red", "Commit message cannot be empty.")
                return False
        
        return GitUtils.update_commit_push(commit_message, self.logger)
    
    def commit_and_generate_package(self):
        """Performs commit, creates branch and triggers workflow to generate package"""
        if not self.is_git_repo:
            self.logger.die("red", "This operation is only available in git repositories.")
            return False
        
        branch_type = self.args.build
        if not branch_type:
            self.logger.die("red", "Branch type not specified.")
            return False
        
        # Pull latest changes before proceeding
        if not GitUtils.git_pull(self.logger):
            if not self.menu.confirm("Failed to pull changes. Do you want to continue anyway?"):
                self.logger.log("red", "Operation cancelled by user.")
                return False
        
        commit_message = self.args.commit
        if not commit_message:
            if GitUtils.has_changes():
                self.logger.die("red", "When using the '-b|--build' parameter, the '-c|--commit' parameter is also required.")
                return False
        
        # Get package name
        package_name = GitUtils.get_package_name()
        if package_name in ["error2", "error3"]:
            if package_name == "error2":
                self.logger.die("red", "Error: PKGBUILD file not found.")
            else:
                self.logger.die("red", "Error: Package name not found in PKGBUILD.")
            return False
        
        # Summary of choices
        self.show_build_summary(package_name, branch_type)
        
        # Pause for user to read summary
        Prompt.ask("\nPress ENTER to continue")
        
        if not self.menu.confirm("Do you want to proceed with building the PACKAGE?"):
            self.logger.log("red", "Package build cancelled.")
            return False
        
        # Try to commit if there are changes
        if GitUtils.has_changes() and commit_message:
            GitUtils.update_commit_push(commit_message, self.logger)
        
        # Create branch and push
        new_branch = GitUtils.create_branch_and_push(branch_type, self.logger)
        if not new_branch:
            return False
        
        # Trigger workflow
        return self.github_api.trigger_workflow(
            package_name, branch_type, new_branch, False, self.tmate_option, self.logger
        )
    
    def build_aur_package(self):
        """Triggers workflow to build an AUR package"""
        aur_package_name = self.args.aur
        if not aur_package_name:
            self.logger.log("purple", "Enter the AUR package name (ex: showtime): type EXIT to exit")
            while True:
                aur_package_name = Prompt.ask("> ")
                aur_package_name = aur_package_name.replace("aur-", "").replace("aur/", "")
                
                if aur_package_name.upper() == "EXIT":
                    self.logger.log("yellow", "Exiting script. No action was performed.")
                    return False
                elif not aur_package_name:
                    self.logger.log("red", "Error: No package name was entered.")
                    continue
                break
        
        self.is_aur_package = True
        
        # Summary of choices for AUR
        self.show_aur_summary(aur_package_name)
        
        # Pause for user to read summary
        Prompt.ask("\nPress ENTER to continue")
        
        if not self.menu.confirm("Do you want to proceed with building the PACKAGE?"):
            self.logger.log("red", "Package build cancelled.")
            return False
        
        # Create branch and push if in a Git repository
        new_branch = ""
        if self.is_git_repo:
            new_branch = GitUtils.create_branch_and_push("aur", self.logger)
        
        # Trigger workflow
        return self.github_api.trigger_workflow(
            aur_package_name, "aur", new_branch, True, self.tmate_option, self.logger
        )
    
    def show_build_summary(self, package_name: str, branch_type: str):
        """Shows a summary of choices for normal build using Rich"""
        timestamp = datetime.now().strftime("%y.%m.%d-%H%M")
        new_branch = f"{branch_type}-{timestamp}"
        repo_name = GitUtils.get_repo_name()
        
        data = [
            ("Organization", self.organization),
            ("Repo Workflow", self.repo_workflow),
            ("User Name", self.github_user_name),
            ("Package Name", package_name),
            ("Branch_type", branch_type),
            ("New Branch", new_branch)
        ]
        
        if repo_name:
            data.append(("Url", f"https://github.com/{repo_name}"))
        
        data.append(("TMATE Debug", str(self.tmate_option)))
        
        self.logger.display_summary("Summary of Choices", data)
    
    def show_aur_summary(self, aur_package_name: str):
        """Shows a summary of choices for AUR package build using Rich"""
        aur_url = f"https://aur.archlinux.org/{aur_package_name}.git"
        timestamp = datetime.now().strftime("%y.%m.%d-%H%M")
        
        data = [
            ("Organization", self.organization),
            ("Repo Workflow", self.repo_workflow),
            ("User Name", self.github_user_name),
            ("Package AUR Name", aur_package_name),
            ("Branch_type", f"aur-{timestamp}"),
            ("New Branch", f"aur-{timestamp}"),
            ("Url", aur_url),
            ("TMATE Debug", str(self.tmate_option))
        ]
        
        self.logger.display_summary("AUR - Summary of Choices", data)
    
    def main_menu(self):
        """Displays interactive main menu"""
        while True:
            if self.is_git_repo:
                options = [
                    "Commit and push",
                    "Generate package (commit + branch + build)",
                    "Build AUR package",
                    "Advanced menu",
                    "Exit"
                ]
            else:
                options = [
                    "Build AUR package",
                    "Exit"
                ]
            
            result = self.menu.show_menu("Main Menu", options)
            if result is None:
                self.logger.log("yellow", "Operation cancelled by user.")
                return
            
            choice, _ = result
            
            if self.is_git_repo:
                if choice == 0:  # Commit and push
                    # Check changes before asking for message
                    if not GitUtils.has_changes():
                        self.logger.log("yellow", "No changes to commit. No action will be performed.")
                        continue
                    
                    # Pull latest changes
                    if not GitUtils.git_pull(self.logger):
                        if not self.menu.confirm("Failed to pull changes. Do you want to continue anyway?"):
                            continue
                    
                    # Only ask for message if there are changes
                    commit_message = Prompt.ask("Enter commit message")
                    if not commit_message:
                        self.logger.log("red", "Commit message cannot be empty.")
                        continue
                    
                    self.args.commit = commit_message
                    self.commit_and_push()
                    return
                
                elif choice == 1:  # Generate package
                    # Select branch type
                    branch_options = ["testing", "stable", "extra", "Back"]
                    branch_result = self.menu.show_menu("Select repository", branch_options)
                    
                    if branch_result is None or branch_options[branch_result[0]] == "Back":
                        continue
                    
                    branch_type = branch_options[branch_result[0]]
                    
                    # Pull latest changes
                    if not GitUtils.git_pull(self.logger):
                        if not self.menu.confirm("Failed to pull changes. Do you want to continue anyway?"):
                            continue
                    
                    # Enable or disable tmate for debug
                    debug_result = self.menu.show_menu("Enable TMATE debug session?", ["No", "Yes"])
                    if debug_result is None:
                        continue
                    
                    self.tmate_option = (debug_result[0] == 1)  # Yes = index 1
                    
                    # Get commit message if there are changes
                    commit_message = ""
                    if GitUtils.has_changes():
                        commit_message = Prompt.ask("Enter commit message")
                        if not commit_message:
                            self.logger.log("red", "Commit message cannot be empty.")
                            continue
                    
                    self.args.build = branch_type
                    self.args.commit = commit_message
                    self.commit_and_generate_package()
                    return
                
                elif choice == 2:  # Build AUR package
                    # Enable or disable tmate for debug
                    debug_result = self.menu.show_menu("Enable TMATE debug session?", ["No", "Yes"])
                    if debug_result is None:
                        continue
                    
                    self.tmate_option = (debug_result[0] == 1)  # Yes = index 1
                    
                    self.args.aur = None  # Force package name request
                    self.build_aur_package()
                    return
                
                elif choice == 3:  # Advanced menu
                    self.advanced_menu()
                    continue
                
                elif choice == 4:  # Exit
                    self.logger.log("yellow", "Exiting script. No action was performed.")
                    return
            else:
                if choice == 0:  # Build AUR package
                    # Enable or disable tmate for debug
                    debug_result = self.menu.show_menu("Enable TMATE debug session?", ["No", "Yes"])
                    if debug_result is None:
                        continue
                    
                    self.tmate_option = (debug_result[0] == 1)  # Yes = index 1
                    
                    self.args.aur = None  # Force package name request
                    self.build_aur_package()
                    return
                
                elif choice == 1:  # Exit
                    self.logger.log("yellow", "Exiting script. No action was performed.")
                    return
    
    def advanced_menu(self):
        """Displays advanced options menu"""
        options = [
            "Delete branches (except main and latest)",
            "Delete failed Action jobs",
            "Delete successful Action jobs",
            "Delete all tags",
            "Back"
        ]
        
        while True:
            result = self.menu.show_menu("Advanced Menu", options)
            if result is None or result[0] == 4:  # None or "Back"
                return
            
            choice, _ = result
            
            if choice == 0:  # Delete branches
                if self.menu.confirm("Are you sure you want to delete branches? This action cannot be undone."):
                    GitUtils.cleanup_old_branches(self.logger)
            
            elif choice == 1:  # Delete failed Action jobs
                if self.menu.confirm("Are you sure you want to delete all failed Action jobs?"):
                    self.github_api.clean_action_jobs("failure", self.logger)
            
            elif choice == 2:  # Delete successful Action jobs
                if self.menu.confirm("Are you sure you want to delete all successful Action jobs?"):
                    self.github_api.clean_action_jobs("success", self.logger)
            
            elif choice == 3:  # Delete tags
                if self.menu.confirm("Are you sure you want to delete all repository tags?"):
                    self.github_api.clean_all_tags(self.logger)
    
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