#
# git_utils.py - Git repository utilities for build_iso
#

import os
import re
from gitrepo.common.network_url import is_github_path_segment
from gitrepo.common import child_process as subprocess


class GitUtils:
    """Utilities for Git repository operations"""

    @staticmethod
    def is_git_repo() -> bool:
        """Checks if the current directory is a Git repository"""
        try:
            result = subprocess.run_git(
                ["git", "rev-parse", "--is-inside-work-tree"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                intent="ordinary",
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    @staticmethod
    def get_repo_name() -> str:
        """Gets the repository name"""
        if not GitUtils.is_git_repo():
            return ""

        try:
            result = subprocess.run_git(
                ["git", "config", "--get", "remote.origin.url"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                intent="ordinary",
            )

            if result.returncode != 0:
                return ""

            url = result.stdout.strip()

            # Pattern for https or git URLs
            match = re.search(r"[:/]([^/]+/[^.]+)(?:\.git)?$", url)
            if not match:
                return ""
            # The result becomes a log directory, so it must not escape it: a
            # remote ending in "x/../foo" would otherwise create the log tree
            # outside the application's state directory.
            owner, _separator, repository = match.group(1).partition("/")
            if not all(is_github_path_segment(segment) for segment in (owner, repository)):
                return ""
            return match.group(1)
        except Exception:
            return ""

    @staticmethod
    def get_repo_root_path() -> str:
        """Gets the root path of the Git repository"""
        if not GitUtils.is_git_repo():
            return os.getcwd()

        try:
            result = subprocess.run_git(
                ["git", "rev-parse", "--show-toplevel"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                intent="ordinary",
            )

            if result.returncode == 0:
                return result.stdout.strip()
            return os.getcwd()
        except Exception:
            return os.getcwd()

    @staticmethod
    def get_github_username() -> str:
        """Gets the GitHub username configured in Git"""
        try:
            result = subprocess.run_git(
                ["git", "config", "user.name"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                intent="ordinary",
            )

            if result.returncode == 0:
                return result.stdout.strip()
            return ""
        except Exception:
            return ""
