#
# github_api_fixed.py - Fixed version with automatic conflict resolution
#

import getpass
import time
from typing import Any

import requests
from urllib.parse import quote

from .git_utils import GitUtils
from .token_store import TokenStore
from gitrepo.common.translation import _


class GitHubAPI:
    """Interface with GitHub API - Fixed version with automatic conflict resolution"""

    def __init__(self, token: str, organization: str):
        self.token = token
        self.organization = organization
        self.headers = (
            {"Accept": "application/vnd.github.v3+json", "Authorization": f"token {self.token}"} if token else {}
        )

    def wait_for_pr_checks(self, pr_number: int, logger, max_wait: int = 120) -> tuple[bool, str]:
        """Poll GitHub until the PR is clean, conflicting, or times out."""
        repo_name = GitUtils.get_repo_name()
        if not repo_name:
            return False, "unknown"
        logger.log("cyan", _("Waiting for GitHub to report whether the PR can be merged..."))
        last_state = "unknown"
        for attempt in range(max_wait):
            try:
                response = requests.get(
                    f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}",
                    headers=self.headers,
                    timeout=30,
                )
                if response.status_code != 200:
                    logger.log("red", _("Error checking PR: {0}").format(response.status_code))
                    return False, "error"
                mergeable = response.json().get("mergeable")
                last_state = response.json().get("mergeable_state") or "unknown"
                if attempt < 3 or attempt % 10 == 0:
                    logger.log(
                        "cyan",
                        _("Attempt {0}/{1}: state={2}").format(attempt + 1, max_wait, last_state),
                    )
                result = self._completed_pr_check(mergeable, last_state, logger)
                if result is not None:
                    return result
            except requests.RequestException as error:
                logger.log("yellow", _("Could not check the PR yet: {0}").format(error))
            if attempt < max_wait - 1:
                time.sleep(2)
        logger.log("yellow", _("Timed out waiting for PR state '{0}'. Merge it manually.").format(last_state))
        return False, "timeout"

    @staticmethod
    def _completed_pr_check(mergeable, mergeable_state, logger):
        if mergeable is True and mergeable_state == "clean":
            logger.log("green", _("PR ready for merge."))
            return True, mergeable_state
        if mergeable is False and mergeable_state == "dirty":
            logger.log("red", _("PR has conflicts; resolve them before merging."))
            return False, mergeable_state
        return None

    def trigger_workflow(
        self, package_name: str, branch_type: str, new_branch: str, is_aur: bool, tmate_option: bool, logger
    ) -> bool:
        """Trigger exactly one reviewed package workflow without mutating Git."""
        dispatch = (
            self._aur_workflow_dispatch(package_name, tmate_option)
            if is_aur
            else self._package_workflow_dispatch(package_name, branch_type, new_branch, tmate_option, logger)
        )
        if not dispatch:
            return False
        event_type, data = dispatch
        repo_workflow = f"{self.organization}/build-package"
        try:
            response = requests.post(
                f"https://api.github.com/repos/{repo_workflow}/dispatches",
                headers=self.headers,
                json=data,
                timeout=30,
            )
        except requests.RequestException as error:
            logger.log("red", _("Error triggering workflow: {0}").format(error))
            return False
        if response.status_code != 204:
            logger.log("red", _("Error triggering workflow. Response code: {0}").format(response.status_code))
            return False
        logger.log("green", _("Build workflow ({0}) triggered successfully.").format(event_type))
        monitor_url = f"https://github.com/{repo_workflow}/actions"
        logger.log("cyan", _("URL to monitor the build: {0}").format(monitor_url))
        return True

    @staticmethod
    def _aur_workflow_dispatch(package_name: str, tmate_option: bool):
        cleaned_name = package_name.removeprefix("aur-").removeprefix("aur/")
        if not cleaned_name or any(character.isspace() for character in cleaned_name):
            return None
        payload = {
            "package_name": cleaned_name,
            "aur_url": f"https://aur.archlinux.org/{cleaned_name}.git",
            "branch_type": "aur",
            "build_env": "aur",
            "tmate": tmate_option,
        }
        return "aur-build", {"event_type": f"aur-{cleaned_name}", "client_payload": payload}

    @staticmethod
    def _package_workflow_dispatch(package_name, branch_type, new_branch, tmate_option, logger):
        repo_name = GitUtils.get_repo_name()
        # Stable and extra packages are published only from main: the package
        # operation merges and pushes main before triggering the workflow and
        # then restores the user's working branch.
        if branch_type in ("stable", "extra"):
            workflow_branch = "main"
        else:
            workflow_branch = new_branch or GitUtils.get_current_branch()
        if not repo_name or not workflow_branch:
            logger.log("red", _("Repository and explicit workflow branch are required."))
            return None
        payload = {
            "branch": workflow_branch,
            "branch_type": branch_type,
            "build_env": "normal",
            "url": f"https://github.com/{repo_name}",
            "tmate": tmate_option,
        }
        if branch_type == "testing":
            payload["new_branch"] = workflow_branch
        logger.log("white", _("Detected repository: {0}").format(repo_name))
        logger.log("cyan", _("Workflow branch: {0}").format(workflow_branch))
        return "package-build", {"event_type": package_name, "client_payload": payload}

    def get_github_token(self, logger) -> str:
        """Gets the GitHub token saved locally (non-fatal if missing)"""
        token = self.get_github_token_optional()
        if not token:
            logger.log("yellow", _("GitHub token not configured. Package operations will require token setup."))
        return token

    def get_github_token_optional(self) -> str:
        """Gets GitHub token if available, returns empty string if not (no error)."""
        return TokenStore.get_token(self.organization)

    def ensure_github_token(self, logger) -> bool:
        """Ensures token is available, prompting user to create if missing.

        This method is called before operations that require GitHub API access
        (package generation, PR creation, workflow triggers). If the token is
        not available, it guides the user through creating one.

        Returns:
            True if token is now available, False if user cancelled setup.
        """
        # Check if we already have a valid token
        if self.token:
            return True

        # Try to read existing token
        token = self.get_github_token_optional()
        if token:
            self.token = token
            self.headers = {"Accept": "application/vnd.github.v3+json", "Authorization": f"token {self.token}"}
            return True

        # Token not found - guide user through setup
        logger.log("yellow", "")
        logger.log("yellow", _("═══ GitHub Token Setup Required ═══"))
        logger.log("yellow", "")
        logger.log("white", _("A GitHub Personal Access Token is required for this operation."))
        logger.log("white", "")
        logger.log("cyan", _("To create a Personal Access Token:"))
        logger.log("white", _("  1. Go to: {0}").format("https://github.com/settings/tokens"))
        logger.log("white", _("  2. Click 'Generate new token (classic)'"))
        logger.log("white", _("  3. Name: 'gitrepo' | Expiration: your choice"))
        logger.log("white", _("  4. Select scopes: 'repo' and 'workflow'"))
        logger.log("white", _("  5. Click 'Generate token' and copy it"))
        logger.log("white", "")

        try:
            # Prompt for username and token
            username = input(_("GitHub username (or press Enter to cancel): ")).strip()
            if not username:
                logger.log("yellow", _("Token setup cancelled."))
                return False

            token_input = getpass.getpass(_("GitHub token (or press Enter to cancel): ")).strip()
            if not token_input:
                logger.log("yellow", _("Token setup cancelled."))
                return False

            if not TokenStore.upsert(self.organization, token_input):
                logger.log(
                    "red",
                    _("The token could not be saved. Unlock the system keyring and try again."),
                )
                return False

            logger.log("green", _("✓ Token saved securely in the system keyring"))

            # Update instance
            self.token = token_input
            self.headers = {"Accept": "application/vnd.github.v3+json", "Authorization": f"token {self.token}"}
            return True

        except (EOFError, KeyboardInterrupt):
            logger.log("yellow", "")
            logger.log("yellow", _("Token setup cancelled."))
            return False

    def clean_action_jobs(self, status: str, logger, menu) -> bool:
        """Delete every Actions run with *status*, reporting what really went."""
        try:
            repo_name = GitUtils.get_repo_name()
            if not repo_name:
                logger.die("red", _("origin is not a GitHub repository; nothing was requested."))
                return False

            logger.log("cyan", _("Cleaning Actions jobs with '{0}' status...").format(status))
            pages = self._paged_items(
                f"https://api.github.com/repos/{repo_name}/actions/runs",
                {"status": status},
                "workflow_runs",
                logger,
            )
            if pages is None:
                return False
            workflow_runs = [run for run in pages if isinstance(run.get("id"), int)]

            if not workflow_runs:
                logger.log("yellow", _("No Action jobs with '{0}' status found.").format(status))
                return True

            preview = "\n".join(
                f"• {run['id']}: {run.get('display_title') or run.get('name') or _('unnamed run')}"
                for run in workflow_runs
            )
            if not menu.confirm(
                _("Permanently delete these {0} GitHub Actions runs from {1}?\n{2}").format(
                    len(workflow_runs), GitUtils.get_canonical_repository(), preview
                ),
                default_yes=False,
            ):
                logger.log("yellow", _("Actions cleanup cancelled."))
                return False

            failed = []
            for run in workflow_runs:
                run_id = run["id"]
                logger.log("yellow", _("Deleting job {0}...").format(run_id))
                if not self._delete_one(
                    f"https://api.github.com/repos/{repo_name}/actions/runs/{run_id}", str(run_id), logger
                ):
                    failed.append(str(run_id))

            return self._report_bulk_outcome(len(workflow_runs), failed, logger)
        except requests.RequestException as error:
            logger.log("red", _("Error cleaning Actions jobs: {0}").format(error))
            return False

    def clean_all_tags(self, logger, menu) -> bool:
        """Delete every remote tag, reporting what really went."""
        try:
            repo_name = GitUtils.get_repo_name()
            if not repo_name:
                logger.die("red", _("origin is not a GitHub repository; nothing was requested."))
                return False

            logger.log("cyan", _("Getting tag list..."))
            pages = self._paged_items(f"https://api.github.com/repos/{repo_name}/tags", {}, None, logger)
            if pages is None:
                return False
            tags = [tag["name"] for tag in pages if isinstance(tag.get("name"), str) and tag["name"]]

            if not tags:
                logger.log("yellow", _("No tags found."))
                return True

            preview = "\n".join(f"• {name}" for name in tags)
            if not menu.confirm(
                _("Permanently delete these {0} remote tags from {1}?\n{2}").format(
                    len(tags), GitUtils.get_canonical_repository(), preview
                ),
                default_yes=False,
            ):
                logger.log("yellow", _("Tag cleanup cancelled."))
                return False

            failed = []
            for tag_name in tags:
                logger.log("yellow", _("Deleting tag {0}...").format(tag_name))
                # Deleting a tag means deleting the reference behind it.
                url = f"https://api.github.com/repos/{repo_name}/git/refs/tags/{quote(tag_name, safe='')}"
                if not self._delete_one(url, tag_name, logger):
                    failed.append(tag_name)

            return self._report_bulk_outcome(len(tags), failed, logger)
        except requests.RequestException as error:
            logger.log("red", _("Error cleaning tags: {0}").format(error))
            return False

    # A "delete all" that stops at the first API page is not a delete all, and
    # a partial deletion reported as success is worse than a reported failure.
    PAGE_SIZE = 100
    PAGE_LIMIT = 50

    def _paged_items(self, url: str, params: dict, key: str | None, logger) -> list | None:
        """Collect every page of a listing, or None when the listing failed."""
        items: list = []
        for page in range(1, self.PAGE_LIMIT + 1):
            response = requests.get(
                url,
                params={**params, "per_page": self.PAGE_SIZE, "page": page},
                headers=self.headers,
                timeout=30,
            )
            if response.status_code != 200:
                logger.log("red", _("Error listing {0}. Code: {1}").format(url, response.status_code))
                return None
            payload = response.json()
            batch = payload.get(key, []) if key else payload
            if not isinstance(batch, list) or not batch:
                return items
            items.extend(batch)
            if len(batch) < self.PAGE_SIZE:
                return items
        logger.log(
            "yellow",
            _("Stopped after {0} pages; run the cleanup again to continue.").format(self.PAGE_LIMIT),
        )
        return items

    def _delete_one(self, url: str, label: str, logger) -> bool:
        try:
            response = requests.delete(url, headers=self.headers, timeout=30)
        except requests.RequestException as error:
            logger.log("red", _("Could not delete {0}: {1}").format(label, error))
            return False
        if response.status_code in (200, 204):
            return True
        logger.log("red", _("Error deleting {0}. Code: {1}").format(label, response.status_code))
        return False

    @staticmethod
    def _report_bulk_outcome(total: int, failed: list[str], logger) -> bool:
        """State the real outcome; a partial deletion never reads as success."""
        deleted = total - len(failed)
        if not failed:
            logger.log("green", _("Deleted {0} of {0} items.").format(total))
            return True
        logger.log("red", _("Deleted {0} of {1}; {2} could not be deleted.").format(deleted, total, len(failed)))
        logger.log("cyan", _("Still present: {0}").format(", ".join(failed[:20])))
        return False

    def create_pull_request(
        self, source_branch: str, target_branch: str = "main", auto_merge: bool = False, logger=None
    ) -> dict:
        """Create a PR and optionally merge it after GitHub reports a clean state."""
        repo_name = GitUtils.get_repo_name()
        if not source_branch or not repo_name:
            if logger:
                logger.log("red", _("Source branch and repository are required to create a pull request."))
            return {}
        if logger:
            logger.log("cyan", _("Creating pull request: {0} → {1}").format(source_branch, target_branch))
        try:
            if self._branches_are_identical(repo_name, source_branch, target_branch):
                if logger:
                    logger.log("green", _("Branches are already identical; no pull request is needed."))
                return {"auto_merged": True, "already_identical": True}
            pr_info = self._create_or_find_pull_request(repo_name, source_branch, target_branch, logger)
            if not pr_info:
                return {}
            if auto_merge and pr_info.get("number"):
                self._merge_ready_pull_request(repo_name, pr_info, source_branch, target_branch, logger)
            self._show_pr_summary(pr_info, source_branch, target_branch, logger)
            return pr_info
        except requests.RequestException as error:
            if logger:
                logger.log("red", _("Error creating pull request: {0}").format(error))
            return {}

    def _branches_are_identical(self, repo_name: str, source_branch: str, target_branch: str) -> bool:
        url = f"https://api.github.com/repos/{repo_name}/compare/{target_branch}...{source_branch}"
        response = requests.get(url, headers=self.headers, timeout=30)
        return response.status_code == 200 and response.json().get("status") == "identical"

    def _create_or_find_pull_request(self, repo_name, source_branch, target_branch, logger):
        data = {
            "title": f"Merge {source_branch} into {target_branch}",
            "body": "Pull request created by GitRepo.",
            "head": source_branch,
            "base": target_branch,
        }
        response = requests.post(
            f"https://api.github.com/repos/{repo_name}/pulls",
            json=data,
            headers=self.headers,
            timeout=30,
        )
        if response.status_code in (200, 201):
            return response.json()
        if response.status_code == 422:
            existing = self._find_existing_pr(repo_name, source_branch, target_branch)
            if existing and logger:
                logger.log("yellow", _("Using existing PR #{0}").format(existing.get("number", 0)))
            return existing
        if logger:
            message = response.json().get("message", _("Unknown error")) if response.text else _("Unknown error")
            logger.log("red", _("Failed to create PR: {0}").format(message))
        return {}

    def _merge_ready_pull_request(self, repo_name, pr_info, source_branch, target_branch, logger):
        pr_number = pr_info["number"]
        is_ready, pr_state = self.wait_for_pr_checks(pr_number, logger)
        if not is_ready:
            pr_info.update(auto_merged=False, merge_error=_("PR not ready: {0}").format(pr_state))
            return
        data = {
            "commit_title": f"Merge {source_branch} into {target_branch}",
            "commit_message": "Merge performed by GitRepo.",
            "merge_method": "merge",
        }
        response = requests.put(
            f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}/merge",
            json=data,
            headers=self.headers,
            timeout=30,
        )
        details = response.json() if response.text else {}
        if response.status_code == 200:
            pr_info.update(auto_merged=True, merge_sha=details.get("sha"))
            if logger:
                logger.log("green", _("Pull request merged successfully."))
            return
        pr_info.update(auto_merged=False, merge_error=details.get("message", _("Unknown error")))
        if logger:
            logger.log("red", _("Auto-merge failed: {0}").format(pr_info["merge_error"]))

    def _find_existing_pr(self, repo_name: str, source_branch: str, target_branch: str) -> dict:
        """Find an existing open PR for the same branch combination"""
        try:
            # GitHub API requires head in format "owner:branch"
            owner = repo_name.split("/")[0] if "/" in repo_name else repo_name
            url = f"https://api.github.com/repos/{repo_name}/pulls"
            params = {"head": f"{owner}:{source_branch}", "base": target_branch, "state": "open"}
            response = requests.get(url, params=params, headers=self.headers, timeout=30)
            if response.status_code == 200:
                prs = response.json()
                if prs:
                    return prs[0]
        except Exception:
            pass
        return {}

    def _show_pr_summary(self, pr_info: dict[str, Any], source_branch: str, target_branch: str, logger: Any) -> None:
        """Show pull request operation summary"""
        if not logger:
            return

        try:
            pr_number = pr_info.get("number", _("unknown"))
            pr_url = pr_info.get("html_url", "")

            logger.log("green", "=" * 50)
            logger.log("green", _("PULL REQUEST COMPLETED SUCCESSFULLY!"))
            logger.log("green", "=" * 50)
            logger.log("white", _("PR #{0} created").format(pr_number))
            logger.log("white", _("Flow: {0} → {1}").format(source_branch, target_branch))

            if pr_info.get("auto_merged"):
                logger.log("green", _("Auto-merge: SUCCESS"))
                logger.log("green", _("Merge SHA: {0}").format(pr_info.get("merge_sha", _("unknown"))[:7]))
            else:
                logger.log("yellow", _("Manual merge required"))
                logger.log("cyan", _("URL: {0}").format(pr_url))

            logger.log("green", "=" * 50)
        except Exception as e:
            logger.log("yellow", _("Could not show PR summary: {0}").format(e))
