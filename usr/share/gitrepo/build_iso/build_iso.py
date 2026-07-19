# intentional-log: this CLI owner renders prompts, help, and summaries to stdout.
#
# build_iso.py - Main class for ISO building management

import argparse
import os
import shutil
import sys
from datetime import datetime

import requests
from gitrepo.common.network_url import validate_https_url
from gitrepo.common.version_display import print_version_panel
from gitrepo.build_iso.config import (
    API_PROFILES,
    APP_DESC,
    APP_NAME,
    APP_VERSION,
    BUILD_MODE_LOCAL,
    BUILD_MODE_REMOTE,
    DEFAULT_ISO_PROFILES,
    DEFAULT_ORGANIZATION,
    DISTRO_DISPLAY_NAMES,
    ISO_PROFILES,
    LOG_DIR_BASE,
    ORG_DEFAULT_CONFIGS,
    VALID_BRANCHES,
    VALID_DISTROS,
    VALID_KERNELS,
    VALID_ORGANIZATIONS,
)
from gitrepo.build_iso.git_utils import GitUtils
from gitrepo.build_iso.github_api import GitHubAPI
from gitrepo.build_iso.menu_system import MenuSystem
from gitrepo.common.rich_logger import RichLogger
from rich.console import Console
from gitrepo.common.translation import _


class BuildISO:
    """Main class for ISO building management"""

    def __init__(self):
        self.args = self.parse_arguments()
        self.logger = RichLogger(APP_NAME, APP_DESC, LOG_DIR_BASE, use_colors=not self.args.nocolor)
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
        self.branches = {"manjaro": "stable", "community": "stable", "biglinux": "stable"}
        self.tmate = self.args.tmate

        # Local build attributes
        self.build_mode = None  # 'local' or 'remote'
        self.output_dir = None  # For local builds
        self.local_config = None  # LocalConfig instance

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
        dependencies = ["git"]

        for dep in dependencies:
            if shutil.which(dep) is None:
                self.logger.die(
                    "red", _("Dependency '{0}' not found. Please install it before continuing.").format(dep)
                )

    def parse_arguments(self) -> argparse.Namespace:
        """Parses command line arguments"""
        parser = argparse.ArgumentParser(
            description=f"{APP_NAME} v{APP_VERSION} - {APP_DESC}", formatter_class=argparse.RawDescriptionHelpFormatter
        )

        parser.add_argument(
            "-o",
            "--org",
            "--organization",
            dest="organization",
            help=_("Configure GitHub organization (default: {0})").format(DEFAULT_ORGANIZATION),
            choices=VALID_ORGANIZATIONS,
            default=DEFAULT_ORGANIZATION,
        )

        parser.add_argument(
            "-d",
            "--distro",
            "--distroname",
            dest="distroname",
            help=_("Set the distribution name"),
            choices=VALID_DISTROS,
        )

        parser.add_argument("-e", "--edition", help=_("Set the edition (desktop environment)"))

        parser.add_argument("-k", "--kernel", help=_("Set the kernel type"), choices=VALID_KERNELS)

        parser.add_argument(
            "-a", "--auto", "--automatic", action="store_true", help=_("Automatic mode using default values")
        )

        parser.add_argument("-n", "--nocolor", action="store_true", help=_("Suppress color printing"))

        parser.add_argument("-V", "--version", action="store_true", help=_("Print application version"))

        parser.add_argument("-t", "--tmate", action="store_true", help=_("Enable tmate for debugging"))

        parser.add_argument("-l", "--local", action="store_true", help=_("Use local build mode"))

        parser.add_argument("--output-dir", help=_("Output directory for local builds"))

        args = parser.parse_args()

        if args.version:
            self.print_version()
            sys.exit(0)

        return args

    def print_version(self):
        """Print the localized application version and license notice."""
        print_version_panel(
            Console(),
            app_name=APP_NAME,
            app_version=APP_VERSION,
            app_description=APP_DESC,
        )

    def get_organization(self) -> bool:
        """Select the GitHub organization"""
        result = self.menu.show_menu(
            _("Choose the GitHub {0}:").format("[yellow]organization[/]"), VALID_ORGANIZATIONS + [_("Exit")]
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
            _("Choose the {0}:").format("[yellow]distribution[/]"), display_names + [_("Back")]
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
            _("Choose the ISO profiles repository:"), ISO_PROFILES + [_("Back")], default_index=default_index
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

        try:
            build_list = self._fetch_profile_directories(api_url)
            if not build_list:
                raise ValueError(_("the selected source returned no build directories"))
            title = _("Choose a {0} for {1}:").format("[yellow]BUILD_DIR[/]", f"[yellow]{self.distroname}[/]")
        except (requests.RequestException, TypeError, ValueError) as error:
            self.logger.log("yellow", _("Could not load remote build directories: {0}").format(str(error)))
            self.logger.log("yellow", _("Using the built-in fallback. Retry this step to query the source again."))
            build_list = [self.distroname]
            title = _("Choose a {0} for {1} (built-in fallback):").format(
                "[yellow]BUILD_DIR[/]", f"[yellow]{self.distroname}[/]"
            )
        return self._select_profile_value(title, build_list, "build_dir")

    def get_edition(self) -> bool:
        """Select the edition (desktop environment)"""
        if not self.iso_profiles_repo or not self.build_dir:
            self.logger.log("red", _("Repository and build directory must be selected first."))
            return False

        api_url = API_PROFILES.get(self.iso_profiles_repo)
        if not api_url:
            self.logger.log("red", _("Error: Repository API URL not found: {0}").format(self.iso_profiles_repo))
            return False
        try:
            editions = self._fetch_profile_directories(api_url, self.build_dir)
            editions = [edition for edition in editions if edition.lower() not in {"hyprland", "core", "minimal"}]
            if not editions:
                raise ValueError(_("the selected source returned no supported editions"))
            title = _("Choose an {0} for {1}:").format("[yellow]EDITION[/]", f"[yellow]{self.distroname}[/]")
        except (requests.RequestException, TypeError, ValueError) as error:
            self.logger.log("yellow", _("Could not load remote editions: {0}").format(str(error)))
            self.logger.log("yellow", _("Using the built-in fallback. Retry this step to query the source again."))
            editions = ["xfce", "kde", "gnome", "cinnamon"]
            title = _("Choose an {0} for {1} (built-in fallback):").format(
                "[yellow]EDITION[/]", f"[yellow]{self.distroname}[/]"
            )
        return self._select_profile_value(title, editions, "edition")

    @staticmethod
    def _fetch_profile_directories(api_url: str, path: str = "") -> list[str]:
        url = validate_https_url(f"{api_url}{path}", {"api.github.com"})
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        ignored = {"shared", "grub", "temp_repo", ".github"}
        return sorted(
            item["name"]
            for item in response.json()
            if item.get("type") == "dir" and item.get("name") and item["name"] not in ignored
        )

    def _select_profile_value(self, title: str, values: list[str], attribute: str) -> bool:
        result = self.menu.show_menu(title, values + [_("Back")])
        if result is None or result[0] == len(values):
            return False
        setattr(self, attribute, values[result[0]])
        return True

    def get_manjaro_branch(self) -> bool:
        """Select the Manjaro branch"""
        result = self.menu.show_menu(
            _("Choose the {0} branch for {1}:").format("[yellow]Manjaro[/]", "[yellow]base system[/]"),
            VALID_BRANCHES + [_("Back")],
        )

        if result is None or result[0] == len(VALID_BRANCHES):
            return False

        self.branches["manjaro"] = VALID_BRANCHES[result[0]]
        return True

    def get_biglinux_branch(self) -> bool:
        """Select the BigLinux branch"""
        result = self.menu.show_menu(
            _("Choose the {0} branch for {1}:").format("[yellow]BigLinux[/]", "[yellow]customizations[/]"),
            VALID_BRANCHES + [_("Back")],
        )

        if result is None or result[0] == len(VALID_BRANCHES):
            return False

        self.branches["biglinux"] = VALID_BRANCHES[result[0]]
        return True

    def get_bigcomm_branch(self) -> bool:
        """Select the Big Community branch"""
        result = self.menu.show_menu(
            _("Choose the {0} branch for {1}:").format("[yellow]Big Community[/]", "[yellow]customizations[/]"),
            VALID_BRANCHES + [_("Back")],
        )

        if result is None or result[0] == len(VALID_BRANCHES):
            return False

        self.branches["community"] = VALID_BRANCHES[result[0]]
        return True

    def get_kernel(self) -> bool:
        """Select the kernel version"""
        result = self.menu.show_menu(
            _("Choose the {0} version:").format("[yellow]KERNEL[/]"), VALID_KERNELS + [_("Back")]
        )

        if result is None or result[0] == len(VALID_KERNELS):
            return False

        self.kernel = VALID_KERNELS[result[0]]
        return True

    def get_debug(self) -> bool:
        """Select whether to enable TMATE debug session"""
        result = self.menu.show_menu(_("Enable TMATE debug session?"), [_("No"), _("Yes"), _("Back")])

        if result is None or result[0] == 2:
            return False

        self.tmate = result[0] == 1  # Yes = index 1
        return True

    def get_build_mode(self) -> bool:
        """Select build mode (Local or Remote)"""
        result = self.menu.show_menu(
            _("Choose the {0}:").format("[yellow]build mode[/]"),
            [_("Local Build"), _("Remote Build (GitHub Actions)"), _("Exit")],
        )

        if result is None or result[0] == 2:
            return False

        self.build_mode = BUILD_MODE_LOCAL if result[0] == 0 else BUILD_MODE_REMOTE
        return True

    def get_output_directory(self) -> bool:
        """Configure output directory for local builds"""
        from gitrepo.build_iso.local_config import LocalConfig
        from rich.prompt import Prompt

        self.local_config = LocalConfig()
        current_dir = self.local_config.get_output_dir()

        result = self.menu.show_menu(
            _("Output directory configuration:"),
            [_("Keep current: {0}").format(current_dir), _("Change directory"), _("Back")],
        )

        if result is None or result[0] == 2:
            return False

        if result[0] == 1:
            new_dir = Prompt.ask(_("Enter new output directory"), default=current_dir)
            new_dir = os.path.expanduser(new_dir)

            if self.local_config.set_output_dir(new_dir):
                self.output_dir = new_dir
                self.logger.log("green", _("Directory configured: {0}").format(new_dir))
            else:
                self.logger.log("red", _("Failed to configure directory"))
                return False
        else:
            self.output_dir = current_dir

        return True

    def resume_and_build_local(self) -> bool:
        """Display summary and execute local build"""
        from datetime import datetime

        from gitrepo.build_iso.local_builder import LocalBuilder

        tag = datetime.now().strftime("%Y-%m-%d_%H-%M")

        # Prepare summary data
        data = [
            (_("Build Mode"), _(self.build_mode.upper())),
            (_("Distribution"), _(DISTRO_DISPLAY_NAMES.get(self.distroname, self.distroname))),
            (_("ISO Profiles Repo"), self.iso_profiles_repo),
            (_("Build Dir"), self.build_dir),
            (_("Edition"), self.edition),
            (_("Manjaro Branch"), self.branches.get("manjaro", "")),
            (_("Community Branch"), self.branches.get("community", "")),
            (_("BigLinux Branch"), self.branches.get("biglinux", "")),
            (_("Kernel"), self.kernel),
            (_("Output Directory"), self.output_dir),
            (_("Release Tag"), tag),
        ]

        self.logger.display_summary(_("Local ISO Build Configuration"), data)

        if not self.menu.confirm(_("Do you want to proceed with local build?")):
            self.logger.log("red", _("Local build cancelled."))
            return False

        # Save configuration
        if self.local_config:
            config_dict = {
                "distroname": self.distroname,
                "edition": self.edition,
                "manjaro_branch": self.branches.get("manjaro", "stable"),
                "biglinux_branch": self.branches.get("biglinux", "stable"),
                "bigcommunity_branch": self.branches.get("community", "stable"),
                "kernel": self.kernel,
                "output_dir": self.output_dir,
            }
            self.local_config.save_config(config_dict)

        # Execute build
        builder_config = {
            "distroname": self.distroname,
            "edition": self.edition,
            "branches": self.branches,
            "kernel": self.kernel,
            "iso_profiles_repo": self.iso_profiles_repo,
            "build_dir": self.build_dir,
            "output_dir": self.output_dir,
        }

        builder = LocalBuilder(self.logger, builder_config)
        return builder.execute_build()

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
            (_("TMATE Debug"), _("Yes") if self.tmate else _("No")),
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
            self.logger,
        )

    def run_automatic_mode(self) -> bool:
        """Run in automatic mode with default settings"""
        from gitrepo.build_iso.local_config import LocalConfig

        # Get default configuration for the organization
        org_config = ORG_DEFAULT_CONFIGS.get(self.organization)

        if not org_config:
            self.logger.die(
                "red", _("No default configuration found for organization '{0}'.").format(self.organization)
            )
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

        # Determine build mode
        if self.args.local:
            self.build_mode = BUILD_MODE_LOCAL

            # Configure output directory
            self.local_config = LocalConfig()
            if self.args.output_dir:
                expanded_dir = os.path.expanduser(self.args.output_dir)
                if self.local_config.set_output_dir(expanded_dir):
                    self.output_dir = expanded_dir
                else:
                    self.logger.die("red", _("Invalid output directory: {0}").format(self.args.output_dir))
            else:
                self.output_dir = self.local_config.get_output_dir()

            # Display summary and trigger local build
            return self.resume_and_build_local()
        else:
            self.build_mode = BUILD_MODE_REMOTE

            # Display summary and trigger remote build
            return self.resume_and_build()

    def interactive_menu(self) -> bool:
        """Run the interactive menu flow"""
        while True:
            if not self._select_build_configuration():
                return False
            if not self._select_distribution_configuration():
                continue
            return self._complete_selected_build()

    def _select_build_configuration(self) -> bool:
        return self.get_build_mode()

    def _select_distribution_configuration(self) -> bool:
        selectors = (
            self.get_organization,
            self.get_distroname,
            self.get_iso_profiles_repo,
            self.get_build_list,
            self.get_edition,
            self.get_manjaro_branch,
        )
        return all(select() for select in selectors) and self._select_distribution_branches() and self.get_kernel()

    def _select_distribution_branches(self) -> bool:
        if self.distroname == "biglinux":
            self.branches["community"] = ""
            return self.get_biglinux_branch()
        if self.distroname == "bigcommunity":
            return self.get_biglinux_branch() and self.get_bigcomm_branch()
        self.branches["biglinux"] = ""
        self.branches["community"] = ""
        return True

    def _complete_selected_build(self) -> bool:
        if self.build_mode == BUILD_MODE_LOCAL:
            return self.get_output_directory() and self.resume_and_build_local()
        return self.get_debug() and self.resume_and_build()

    def run(self):
        """Main entry point for the application"""
        self.logger.log("blue", _("{0} (version {1})").format(APP_NAME, APP_VERSION))

        if self.args.auto:
            # Run in automatic mode
            return self.run_automatic_mode()
        else:
            # Run in interactive mode
            return self.interactive_menu()
