#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# build_iso.py - Main class for ISO building management

import sys
import argparse
import subprocess
from rich.console import Console
from datetime import datetime
import requests
from translation_utils import _

from config import (
    APP_NAME, APP_DESC, VERSION, DEFAULT_ORGANIZATION, 
    VALID_ORGANIZATIONS, VALID_BRANCHES, VALID_KERNELS,
    VALID_DISTROS, DISTRO_DISPLAY_NAMES, ISO_PROFILES,
    DEFAULT_ISO_PROFILES, API_PROFILES, ORG_DEFAULT_CONFIGS
)
from logger import RichLogger
from git_utils import GitUtils
from github_api import GitHubAPI
from menu_system import MenuSystem

class BuildISO:
    """Main class for ISO building management"""
    
    def __init__(self):
        self.args = self.parse_arguments()
        self.logger = RichLogger(not self.args.nocolor)
        self.menu = MenuSystem(self.logger)
        self.organization = self.args.organization or DEFAULT_ORGANIZATION
        self.repo_workflow = f"{self.organization}/build-iso"
        self.console = Console()
        
        # Initial default values
        self.distroname = self.args.distroname or "big-comm"
        self.edition = self.args.edition or "xfce"
        self.kernel = self.args.kernel or "lts"
        self.iso_profiles_repo = ""
        self.build_dir = ""
        self.branches = {
            "manjaro": "stable",
            "community": "stable",
            "biglinux": "stable"
        }
        self.tmate = self.args.tmate
        
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
        
        parser.add_argument("-d", "--distro", "--distroname",
                           dest="distroname",
                           help=_("Set the distribution name"),
                           choices=VALID_DISTROS)
        
        parser.add_argument("-e", "--edition",
                           help=_("Set the edition (desktop environment)"))
        
        parser.add_argument("-k", "--kernel",
                           help=_("Set the kernel type"),
                           choices=VALID_KERNELS)
        
        parser.add_argument("-a", "--auto", "--automatic",
                           action="store_true",
                           help=_("Automatic mode using default values"))
        
        parser.add_argument("-n", "--nocolor", 
                           action="store_true",
                           help=_("Suppress color printing"))
        
        parser.add_argument("-V", "--version", 
                           action="store_true",
                           help=_("Print application version"))
        
        parser.add_argument("-t", "--tmate", 
                           action="store_true",
                           help=_("Enable tmate for debugging"))
        
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
    
    def get_organization(self) -> bool:
        """Select the GitHub organization"""
        result = self.menu.show_menu(
            _("Choose the GitHub {0}:").format("[yellow]organization[/]"),
            VALID_ORGANIZATIONS + [_("Exit")]
        )
        
        if result is None or result[0] == len(VALID_ORGANIZATIONS):
            self.logger.log("yellow", _("Operation cancelled by user."))
            return False
        
        self.organization = VALID_ORGANIZATIONS[result[0]]
        self.repo_workflow = f"{self.organization}/build-iso"
        
        # IMPORTANT: Update the github_api object with the new organization
        token = GitHubAPI(None, self.organization).get_github_token(self.logger)
        self.github_api = GitHubAPI(token, self.organization)
        
        return True
    
    def get_distroname(self) -> bool:
        """Select the distribution name"""
        # Create a list with display names for the menu
        display_names = [DISTRO_DISPLAY_NAMES[distro] for distro in VALID_DISTROS]
        
        result = self.menu.show_menu(
            _("Choose the {0}:").format("[yellow]distribution[/]"),
            display_names + [_("Back")]
        )
        
        if result is None or result[0] == len(display_names):
            return False
        
        # Map the display name back to the distribution ID
        selected_display = display_names[result[0]]
        for distro_id, display in DISTRO_DISPLAY_NAMES.items():
            if display == selected_display:
                self.distroname = distro_id
                break
                
        return True
    
    def get_iso_profiles_repo(self) -> bool:
        """Select the ISO profiles repository"""
        # Generate a default URL based on distroname
        default_url = DEFAULT_ISO_PROFILES.get(self.distroname, DEFAULT_ISO_PROFILES["big-comm"])
        
        # Pre-select the default repository for the current distribution
        default_index = 0
        for i, repo_url in enumerate(ISO_PROFILES):
            if repo_url == default_url:
                default_index = i
                break
        
        # Create a list of repository options
        result = self.menu.show_menu(
            _("Choose the ISO profiles repository:"),
            ISO_PROFILES + [_("Back")],
            default_index=default_index
        )
        
        if result is None or result[0] == len(ISO_PROFILES):
            return False
        
        self.iso_profiles_repo = ISO_PROFILES[result[0]]
        return True
    
    def get_build_list(self) -> bool:
        """Get the build directory list based on selected repository"""
        if not self.iso_profiles_repo:
            self.logger.log("red", _("No ISO profiles repository selected."))
            return False
        
        # Get the API URL for the repository
        api_url = API_PROFILES.get(self.iso_profiles_repo)
        if not api_url:
            self.logger.log("red", _("Error: Repository API URL not found: {0}").format(self.iso_profiles_repo))
            return False
        
        self.logger.log("cyan", _("Fetching from API: {0}").format(api_url))
        
        try:
            # Make API request
            response = requests.get(api_url)
            if response.status_code != 200:
                self.logger.log("red", _("Error: API request failed with status code {0}").format(response.status_code))
                return False
            
            # Parse response based on whether it's GitHub or GitLab
            build_list = []
            if "github" in api_url:
                # GitHub API response format
                data = response.json()
                for item in data:
                    if item.get("type") == "dir" and item.get("name") not in ["shared", "grub", "temp_repo", ".github"]:
                        build_list.append(item.get("name"))
            else:
                # GitLab API response format
                data = response.json()
                for item in data:
                    if item.get("type") == "tree" and item.get("name") not in ["shared", "grub", "temp_repo", ".github"]:
                        build_list.append(item.get("name"))
            
            # Use generic fallback if the dynamic list fails or is empty
            if not build_list:
                build_list = [self.distroname]
            
            # Show menu with build directories
            result = self.menu.show_menu(
                _("Choose a {0} for {1}:").format("[yellow]BUILD_DIR[/]", f"[yellow]{self.distroname}[/]"),
                build_list + [_("Back")]
            )
            
            if result is None or result[0] == len(build_list):
                return False
            
            self.build_dir = build_list[result[0]]
            return True
            
        except Exception as e:
            self.logger.log("red", _("Error fetching build list: {0}").format(str(e)))
            # Fallback to generic build dir
            build_list = [self.distroname]
            
            result = self.menu.show_menu(
                _("Choose a {0} for {1} (from defaults):").format("[yellow]BUILD_DIR[/]", f"[yellow]{self.distroname}[/]"),
                build_list + [_("Back")]
            )
            
            if result is None or result[0] == len(build_list):
                return False
            
            self.build_dir = build_list[result[0]]
            return True
    
    def get_edition(self) -> bool:
        """Select the edition (desktop environment)"""
        if not self.iso_profiles_repo or not self.build_dir:
            self.logger.log("red", _("Repository and build directory must be selected first."))
            return False
        
        try:
            # First try to get editions dynamically from API
            api_url = API_PROFILES.get(self.iso_profiles_repo)
            if not api_url:
                self.logger.log("red", _("Error: Repository API URL not found: {0}").format(self.iso_profiles_repo))
                return False
            
            editions = []
            
            # Make API request for subdirectories
            if "github" in api_url:
                # GitHub API path format
                response = requests.get(f"{api_url}{self.build_dir}")
                if response.status_code == 200:
                    data = response.json()
                    for item in data:
                        if item.get("type") == "dir":
                            editions.append(item.get("name"))
            else:
                # GitLab API path format
                response = requests.get(f"{api_url}?path={self.build_dir}")
                if response.status_code == 200:
                    data = response.json()
                    for item in data:
                        if item.get("type") == "tree":
                            editions.append(item.get("name"))
            
            # If API call fails or returns empty, use generic editions
            if not editions:
                editions = ["xfce", "kde", "gnome", "cinnamon"]
            
            # Show menu with editions
            result = self.menu.show_menu(
                _("Choose an {0} for {1}:").format("[yellow]EDITION[/]", f"[yellow]{self.distroname}[/]"),
                editions + [_("Back")]
            )
            
            if result is None or result[0] == len(editions):
                return False
            
            self.edition = editions[result[0]]
            return True
            
        except Exception as e:
            self.logger.log("red", _("Error fetching editions: {0}").format(str(e)))
            # Fallback to generic editions
            editions = ["xfce", "kde", "gnome", "cinnamon"]
            
            result = self.menu.show_menu(
                _("Choose an {0} for {1} (from defaults):").format("[yellow]EDITION[/]", f"[yellow]{self.distroname}[/]"),
                editions + [_("Back")]
            )
            
            if result is None or result[0] == len(editions):
                return False
            
            self.edition = editions[result[0]]
            return True
    
    def get_manjaro_branch(self) -> bool:
        """Select the Manjaro branch"""
        result = self.menu.show_menu(
            _("Choose the {0} branch for {1}:").format("[yellow]Manjaro[/]", "[yellow]base system[/]"),
            VALID_BRANCHES + [_("Back")]
        )
        
        if result is None or result[0] == len(VALID_BRANCHES):
            return False
        
        self.branches["manjaro"] = VALID_BRANCHES[result[0]]
        return True
    
    def get_biglinux_branch(self) -> bool:
        """Select the BigLinux branch"""
        result = self.menu.show_menu(
            _("Choose the {0} branch for {1}:").format("[yellow]BigLinux[/]", "[yellow]customizations[/]"),
            VALID_BRANCHES + [_("Back")]
        )
        
        if result is None or result[0] == len(VALID_BRANCHES):
            return False
        
        self.branches["biglinux"] = VALID_BRANCHES[result[0]]
        return True
    
    def get_bigcomm_branch(self) -> bool:
        """Select the Big Community branch"""
        result = self.menu.show_menu(
            _("Choose the {0} branch for {1}:").format("[yellow]Big Community[/]", "[yellow]customizations[/]"),
            VALID_BRANCHES + [_("Back")]
        )
        
        if result is None or result[0] == len(VALID_BRANCHES):
            return False
        
        self.branches["community"] = VALID_BRANCHES[result[0]]
        return True
    
    def get_kernel(self) -> bool:
        """Select the kernel version"""
        result = self.menu.show_menu(
            _("Choose the {0} version:").format("[yellow]KERNEL[/]"),
            VALID_KERNELS + [_("Back")]
        )
        
        if result is None or result[0] == len(VALID_KERNELS):
            return False
        
        self.kernel = VALID_KERNELS[result[0]]
        return True
    
    def get_debug(self) -> bool:
        """Select whether to enable TMATE debug session"""
        result = self.menu.show_menu(
            _("Enable TMATE debug session?"),
            [_("No"), _("Yes"), _("Back")]
        )
        
        if result is None or result[0] == 2:
            return False
        
        self.tmate = (result[0] == 1)  # Yes = index 1
        return True
    
    def resume_and_build(self) -> bool:
        """Display build summary and trigger workflow if confirmed"""
        # Generate tag for this build
        tag = datetime.now().strftime("%Y-%m-%d_%H-%M")
        
        # Get display name of the distribution
        distro_display = DISTRO_DISPLAY_NAMES.get(self.distroname, self.distroname)
        
        # Create summary data
        data = [
            (_("Organization"), self.organization),
            (_("User Name"), self.github_user_name),
            (_("Distribution"), distro_display), 
            (_("ISO Profiles Repo"), self.iso_profiles_repo),
            (_("Build Dir"), self.build_dir),
            (_("Edition"), self.edition),
            (_("Manjaro Branch"), self.branches.get("manjaro", "")),
            (_("Community Branch"), self.branches.get("community", "")),
            (_("BigLinux Branch"), self.branches.get("biglinux", "")),
            (_("Kernel"), self.kernel),
            (_("Release Tag"), tag),
            (_("TMATE Debug"), _("Yes") if self.tmate else _("No"))
        ]
        
        # Display summary
        self.logger.display_summary(_("ISO Build Summary"), data)
        
        # Confirm build
        if not self.menu.confirm(_("Do you want to proceed with building the ISO?")):
            self.logger.log("red", _("ISO build cancelled."))
            return False
        
        # Trigger the workflow
        return self.github_api.trigger_workflow(
            self.distroname,
            self.iso_profiles_repo,
            self.build_dir,
            self.edition,
            self.branches,
            self.kernel,
            self.tmate,
            self.logger
        )
    
    def run_automatic_mode(self) -> bool:
        """Run in automatic mode with default settings"""
        
        # Get default configuration for the organization
        org_config = ORG_DEFAULT_CONFIGS.get(self.organization)
        
        if not org_config:
            self.logger.die("red", _("No default configuration found for organization '{0}'.").format(self.organization))
            return False
        
        # Apply organization default settings
        self.distroname = org_config["distroname"]
        self.iso_profiles_repo = org_config["iso_profiles_repo"] 
        self.branches = org_config["branches"].copy()  # Copy to avoid modifying the original
        self.kernel = org_config["kernel"]
        self.build_dir = org_config["build_dir"]
        self.edition = org_config["edition"]
        
        # Override with command line arguments (if provided)
        if self.args.distroname:
            self.distroname = self.args.distroname
        if self.args.edition:
            self.edition = self.args.edition
        if self.args.kernel:
            self.kernel = self.args.kernel
                
        # Display summary and trigger build
        return self.resume_and_build()
    
    def interactive_menu(self) -> bool:
        """Run the interactive menu flow"""
        while True:
            # Step 1: Select organization
            if not self.get_organization():
                return False
            
            # Step 2: Select distribution
            if not self.get_distroname():
                continue
            
            # Step 3: Select ISO profiles repository
            if not self.get_iso_profiles_repo():
                continue
            
            # Step 4: Select build directory
            if not self.get_build_list():
                continue
            
            # Step 5: Select edition
            if not self.get_edition():
                continue
            
            # Step 6: Select Manjaro branch
            if not self.get_manjaro_branch():
                continue
            
            # Step 7: Select branches based on distribution
            if self.distroname == "biglinux":
                # For BigLinux, we only need biglinux branch
                if not self.get_biglinux_branch():
                    continue
                self.branches["community"] = ""
            elif self.distroname == "bigcommunity":
                # For Big Community, we need both branches
                if not self.get_biglinux_branch():
                    continue
                if not self.get_bigcomm_branch():
                    continue
            else:
                # For other distros, no additional branches needed
                self.branches["biglinux"] = ""
                self.branches["community"] = ""
            
            # Step 8: Select kernel
            if not self.get_kernel():
                continue
            
            # Step 9: Select debug option
            if not self.get_debug():
                continue
            
            # Step 10: Show summary and build
            return self.resume_and_build()
    
    def run(self):
        """Main entry point for the application"""
        self.logger.log("blue", _("{0} (version {1})").format(APP_NAME, VERSION))
        
        if self.args.auto:
            # Run in automatic mode
            return self.run_automatic_mode()
        else:
            # Run in interactive mode
            return self.interactive_menu()