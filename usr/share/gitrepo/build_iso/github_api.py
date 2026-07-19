#
# github_api.py - GitHub API interface for build_iso.py
#

from datetime import datetime

import requests
from gitrepo.common.token_store import GitHubTokenStore
from gitrepo.common.translation import _


def _iso_release_type(distroname: str, branches: dict) -> str:
    manjaro = branches.get("manjaro", "stable")
    distribution = branches.get("community" if distroname == "bigcommunity" else "biglinux", "stable")
    if distroname not in {"bigcommunity", "biglinux"}:
        return manjaro.upper()
    if "unstable" in {manjaro, distribution}:
        return "DEVELOPMENT"
    if {manjaro, distribution} == {"stable"}:
        return "STABLE"
    return "BETA"


def _workflow_payload(distroname, iso_profiles_repo, build_dir, edition, branches, kernel, tmate):
    release_type = _iso_release_type(distroname, branches)
    tag = datetime.now().strftime("%Y-%m-%d_%H-%M")
    return {
        "event_type": f"ISO-{distroname}_{release_type}_{edition.lower()}_{tag}",
        "client_payload": {
            "distroname": distroname,
            "iso_profiles_repo": iso_profiles_repo,
            "build_dir": build_dir,
            "edition": edition,
            "manjaro_branch": branches.get("manjaro", ""),
            "community_branch": branches.get("community", ""),
            "biglinux_branch": branches.get("biglinux", ""),
            "kernel": kernel,
            "tmate": "true" if tmate else "false",
        },
    }


class GitHubAPI:
    """Interface with GitHub API for ISO building"""

    def __init__(self, token: str, organization: str):
        self.token = token
        self.organization = organization
        self.headers = (
            {"Accept": "application/vnd.github.v3+json", "Authorization": f"token {self.token}"} if token else {}
        )

    def get_github_token(self, logger) -> str:
        """Gets the GitHub token saved locally"""
        store = GitHubTokenStore()
        token = store.get_token(self.organization)
        if token:
            return token
        if store.last_read_error:
            logger.die("red", _("Error reading token: {0}").format(store.last_read_error))
        else:
            logger.die("red", _("Token for organization '{0}' not found.").format(self.organization))
        return ""

    def trigger_workflow(
        self,
        distroname: str,
        iso_profiles_repo: str,
        build_dir: str,
        edition: str,
        branches: dict,
        kernel: str,
        tmate: bool,
        logger,
    ) -> bool:
        """Dispatch one validated ISO build event to GitHub Actions."""
        repository = f"{self.organization}/build-iso"
        payload = _workflow_payload(distroname, iso_profiles_repo, build_dir, edition, branches, kernel, tmate)
        url = f"https://api.github.com/repos/{repository}/dispatches"
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        except requests.RequestException as error:
            logger.log("red", _("Could not reach GitHub: {0}").format(error))
            return False
        if response.status_code != 204:
            logger.log("red", _("GitHub rejected the workflow request ({0}).").format(response.status_code))
            return False
        logger.log("green", _("ISO build workflow triggered: {0}").format(payload["event_type"]))
        logger.log("cyan", _("Monitor the build at: {0}").format(self.get_action_url(repository)))
        return True

    def get_action_url(self, repo_workflow=None) -> str:
        """Gets the URL for the Actions tab in GitHub"""
        if not repo_workflow:
            repo_workflow = f"{self.organization}/build-iso"

        return f"https://github.com/{repo_workflow}/actions"
