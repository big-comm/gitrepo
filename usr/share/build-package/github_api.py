#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# github_api.py - GitHub API interface
#

import os
import requests
from git_utils import GitUtils
from config import TOKEN_FILE
from translation_utils import _

class GitHubAPI:
    """Interface with GitHub API"""
    
    def __init__(self, token: str, organization: str):
        self.token = token
        self.organization = organization
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"token {self.token}"
        } if token else {}
    
    def create_reference(self, branch_type: str, logger) -> str:
        """Creates a reference (tag) in GitHub without creating a local branch"""
        try:
            repo_name = GitUtils.get_repo_name()
            if not repo_name:
                logger.die("red", _("Could not determine repository name."))
                return ""
            
            # Get the current commit SHA
            current_sha = GitUtils.get_current_commit_sha()
            if not current_sha:
                logger.die("red", _("Could not determine current commit SHA."))
                return ""
            
            # Generate a reference name with timestamp
            from datetime import datetime
            timestamp = datetime.now().strftime("%y.%m.%d-%H%M")
            ref_name = f"{branch_type}-{timestamp}"
            
            # Create the reference in GitHub
            logger.log("cyan", _("Creating reference: {0}...").format(ref_name))
            
            url = f"https://api.github.com/repos/{repo_name}/git/refs"
            data = {
                "ref": f"refs/tags/{ref_name}",
                "sha": current_sha
            }
            
            response = requests.post(
                url,
                headers=self.headers,
                json=data
            )
            
            if response.status_code not in [201, 200]:
                logger.log("red", _("Error creating reference: {0}").format(response.status_code))
                return ""
            
            logger.log("green", _("Reference {0} created successfully!").format(ref_name))
            return ref_name
        except Exception as e:
            logger.log("red", _("Error creating reference: {0}").format(e))
            return ""
    
    def create_remote_branch(self, branch_type: str, logger) -> str:
        """Creates a branch directly on GitHub without triggering PR notifications"""
        try:
            repo_name = GitUtils.get_repo_name()
            if not repo_name:
                logger.die("red", _("Could not determine repository name."))
                return ""
            
            # Generate a branch name with timestamp
            from datetime import datetime
            timestamp = datetime.now().strftime("%y.%m.%d-%H%M")
            new_branch_name = f"dev-{timestamp}"  # Always use dev- prefix

            # Use dev branch as base, or main if dev doesn't exist
            base_branch = self.get_branch_sha("dev", logger) and "dev" or "main"
            
            base_sha = self.get_branch_sha(base_branch, logger)
            if not base_sha:
                logger.log("red", _("Could not determine SHA for {0}.").format(base_branch))
                return ""
            
            logger.log("cyan", _("Creating branch: {0} based on {1}...").format(new_branch_name, base_branch))
            
            # First create a Git reference
            url = f"https://api.github.com/repos/{repo_name}/git/refs"
            data = {
                "ref": f"refs/heads/{new_branch_name}",
                "sha": base_sha
            }
            
            response = requests.post(url, headers=self.headers, json=data)
            
            if response.status_code not in [201, 200]:
                logger.log("red", _("Error creating branch: {0}").format(response.status_code))
                logger.log("red", _("Error details: {0}").format(response.text))
                return ""
            
            logger.log("green", _("Branch {0} created successfully!").format(new_branch_name))
            return new_branch_name
        except Exception as e:
            logger.log("red", _("Error creating branch: {0}").format(e))
            return ""

    def get_latest_dev_branch(self, logger) -> str:
        """Gets the most recent dev branch"""
        try:
            repo_name = GitUtils.get_repo_name()
            if not repo_name:
                return ""
            
            # Get all branches
            response = requests.get(
                f"https://api.github.com/repos/{repo_name}/branches",
                headers=self.headers
            )
            
            if response.status_code != 200:
                return ""
            
            branches = response.json()
            dev_branches = [
                b['name'] for b in branches 
                if b['name'] == 'dev' or b['name'].startswith('dev-')
            ]
            
            # Sort by name (assuming format dev-YY.MM.DD-HHMM)
            dev_branches.sort(reverse=True)
            
            # Return 'dev' branch if it exists, otherwise the most recent dev-* branch
            if 'dev' in dev_branches:
                return 'dev'
            elif dev_branches:
                return dev_branches[0]
            return ""
        except Exception:
            return ""

    def get_branch_sha(self, branch_name: str, logger) -> str:
        """Gets the SHA of the latest commit on a branch"""
        try:
            repo_name = GitUtils.get_repo_name()
            if not repo_name:
                return ""
            
            response = requests.get(
                f"https://api.github.com/repos/{repo_name}/branches/{branch_name}",
                headers=self.headers
            )
            
            if response.status_code != 200:
                # Try with main if branch doesn't exist
                if branch_name != "main":
                    return self.get_branch_sha("main", logger)
                return ""
            
            return response.json()['commit']['sha']
        except Exception:
            return ""

    def trigger_workflow(self, package_name: str, branch_type: str, 
                        new_branch: str, is_aur: bool, tmate_option: bool,
                        logger) -> bool:
        """Triggers a workflow on GitHub"""
        repo_workflow = f"{self.organization}/build-package"
        
        # If new_branch is empty, create a branch directly via API
        if not new_branch and not is_aur:
            # Get current branch name first to check if we already have a branch
            current_branch = GitUtils.get_current_branch()
            
            # Only create a new branch if we're not already on a dev-* branch
            if not current_branch.startswith("dev-"):
                new_branch = self.create_remote_branch("dev", logger)
                if not new_branch:
                    logger.log("red", _("Failed to create branch for the build."))
                    return False
            else:
                # Use the current branch instead of creating a new one
                new_branch = current_branch
                logger.log("white", _("Using existing branch: {0}").format(new_branch))
        
        if is_aur:
            # Clean package name (remove aur- prefixes)
            cleaned_package_name = package_name.replace("aur-", "").replace("aur/", "")
            aur_url = f"https://aur.archlinux.org/{cleaned_package_name}.git"
            
            data = {
                "event_type": f"aur-{cleaned_package_name}",
                "client_payload": {
                    "package_name": cleaned_package_name,
                    "aur_url": aur_url,
                    "branch_type": "aur",
                    "build_env": "aur",
                    "tmate": tmate_option
                }
            }
            event_type = "aur-build"
        else:
            # Get remote repository name
            repo_name = GitUtils.get_repo_name()
            if not repo_name:
                logger.die("red", _("Error retrieving remote repository URL for package: {0}").format(package_name))
                return False
            
            logger.log("white", _("Detected repository: {0}").format(repo_name))
            
            data = {
                "event_type": package_name,
                "client_payload": {
                    "branch": new_branch,
                    "branch_type": branch_type,
                    "build_env": "normal",
                    "url": f"https://github.com/{repo_name}",
                    "tmate": tmate_option
                }
            }
            event_type = "package-build"
        
        try:
            logger.log("cyan", _("Triggering build workflow on GitHub..."))
            
            response = requests.post(
                f"https://api.github.com/repos/{repo_workflow}/dispatches",
                headers=self.headers,
                json=data
            )
            
            if response.status_code != 204:
                logger.log("red", _("Error triggering workflow. Response code: {0}").format(response.status_code))
                return False
            
            logger.log("green", _("Build workflow ({0}) triggered successfully.").format(event_type))
            
            # Generate Action link
            action_url = f"https://github.com/{repo_workflow}/actions"
            logger.log("cyan", _("URL to monitor the build: {0}").format(action_url))
            
            return True
        except Exception as e:
            logger.log("red", _("Error triggering workflow: {0}").format(e))
            return False
    
    def get_github_token(self, logger) -> str:
        """Gets the GitHub token saved locally"""
        token_file = os.path.expanduser(TOKEN_FILE)
        
        if not os.path.exists(token_file):
            logger.die("red", _("Token file '{0}' not found.").format(token_file))
            return ""
        
        try:
            with open(token_file, 'r') as f:
                token_lines = f.readlines()
            
            # Look for token associated with current organization
            for line in token_lines:
                line = line.strip()
                if '=' in line:
                    org, token = line.split('=', 1)
                    if org.lower() == self.organization.lower():
                        return token
                elif line and not '=' in line:
                    # If it's just a token without a specific organization
                    return line
            
            logger.die("red", _("Token for organization '{0}' not found.").format(self.organization))
            return ""
        except Exception as e:
            logger.die("red", _("Error reading token: {0}").format(e))
            return ""
            
    def clean_action_jobs(self, status: str, logger) -> bool:
        """Cleans Actions jobs with specific status (success, failure)"""
        try:
            repo_name = GitUtils.get_repo_name()
            if not repo_name:
                logger.die("red", _("Could not determine repository name."))
                return False
                
            logger.log("cyan", _("Cleaning Actions jobs with '{0}' status...").format(status))
            
            # Fetch workflows runs
            response = requests.get(
                f"https://api.github.com/repos/{repo_name}/actions/runs?status={status}",
                headers=self.headers
            )
            
            if response.status_code != 200:
                logger.log("red", _("Error fetching Actions jobs. Code: {0}").format(response.status_code))
                return False
                
            data = response.json()
            workflow_runs = data.get('workflow_runs', [])
            
            if not workflow_runs:
                logger.log("yellow", _("No Action jobs with '{0}' status found.").format(status))
                return True
                
            # Delete each workflow run
            deleted_count = 0
            for run in workflow_runs:
                run_id = run.get('id')
                logger.log("yellow", _("Deleting job {0}...").format(run_id))
                
                delete_response = requests.delete(
                    f"https://api.github.com/repos/{repo_name}/actions/runs/{run_id}",
                    headers=self.headers
                )
                
                if delete_response.status_code in [204, 200]:
                    deleted_count += 1
                else:
                    logger.log("red", _("Error deleting job {0}. Code: {1}").format(run_id, delete_response.status_code))
            
            logger.log("green", _("Deleted {0} Actions jobs with '{1}' status.").format(deleted_count, status))
            return True
        except Exception as e:
            logger.log("red", _("Error cleaning Actions jobs: {0}").format(e))
            return False
            
    def clean_all_tags(self, logger) -> bool:
        """Deletes all tags in the remote repository"""
        try:
            repo_name = GitUtils.get_repo_name()
            if not repo_name:
                logger.die("red", _("Could not determine repository name."))
                return False
                
            logger.log("cyan", _("Getting tag list..."))
            
            # Fetch tags
            response = requests.get(
                f"https://api.github.com/repos/{repo_name}/tags",
                headers=self.headers
            )
            
            if response.status_code != 200:
                logger.log("red", _("Error fetching tags. Code: {0}").format(response.status_code))
                return False
                
            tags = response.json()
            
            if not tags:
                logger.log("yellow", _("No tags found."))
                return True
                
            # Delete each tag
            deleted_count = 0
            for tag in tags:
                tag_name = tag.get('name')
                logger.log("yellow", _("Deleting tag {0}...").format(tag_name))
                
                # To delete a tag, we need to delete the corresponding reference
                delete_response = requests.delete(
                    f"https://api.github.com/repos/{repo_name}/git/refs/tags/{tag_name}",
                    headers=self.headers
                )
                
                if delete_response.status_code in [204, 200]:
                    deleted_count += 1
                else:
                    logger.log("red", _("Error deleting tag {0}. Code: {1}").format(tag_name, delete_response.status_code))
            
            logger.log("green", _("Deleted {0} tags.").format(deleted_count))
            return True
        except Exception as e:
            logger.log("red", _("Error cleaning tags: {0}").format(e))
            return False
        
    def create_pull_request(self, source_branch: str, target_branch: str = "dev", auto_merge: bool = False, logger = None) -> dict:
        """Creates a pull request and optionally merges it automatically"""
        if not source_branch:
            if logger:
                logger.log("red", _("Source branch name is required to create a pull request"))
            return {}
        
        # Get repository name
        repo_name = GitUtils.get_repo_name()
        if not repo_name:
            if logger:
                logger.log("cyan", _("Token length: {0}").format(len(self.token) if self.token else 0)) # Debug
                logger.log("cyan", _("Repository name: {0}").format(repo_name)) # Debug
                logger.log("cyan", _("Creating PR from '{0}' to '{1}'").format(source_branch, target_branch)) #Debug
                logger.log("red", _("Repository name could not be determined"))
            return {}
        
        if logger:
            logger.log("cyan", _("Creating pull request from {0} to {1}...").format(source_branch, target_branch))
        
        # Create PR data
        pr_data = {
            "title": _("Merge {0} into {1}").format(source_branch, target_branch),
            "body": _("Automated PR created by build_package.py"),
            "head": source_branch,
            "base": target_branch
        }
        
        try:
            # Create the PR through GitHub API
            url = f"https://api.github.com/repos/{repo_name}/pulls"
            headers = {
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github.v3+json"
            }
            
            response = requests.post(url, json=pr_data, headers=headers)
            
            if response.status_code not in [200, 201]:
                if logger:
                    logger.log("red", _("Failed to create PR: {0}").format(response.json().get('message', '')))
                    logger.log("cyan", _("API response status: {0}").format(response.status_code))
                    if response.status_code not in [200, 201]: # Debug
                        logger.log("red", _("Error details: {0}").format(response.text)) # Debug
                return {}
            
            pr_info = response.json()
            pr_url = pr_info.get("html_url", "")
            pr_number = pr_info.get("number", 0)
            
            if logger:
                logger.log("green", _("Pull request created successfully: {0}").format(pr_url))
            
            # Auto-merge if requested
            if auto_merge and pr_number:
                if logger:
                    logger.log("cyan", _("Attempting to merge pull request automatically..."))
                
                merge_url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}/merge"
                merge_response = requests.put(merge_url, headers=headers)
                
                if merge_response.status_code == 200:
                    if logger:
                        logger.log("green", _("Pull request merged successfully"))
                else:
                    if logger:
                        logger.log("yellow", _("Pull request created but could not be merged automatically: {0}").format(merge_response.json().get('message', '')))
            
            return pr_info
        
        except Exception as e:
            if logger:
                logger.log("red", _("Error creating pull request: {0}").format(str(e)))
            return {}