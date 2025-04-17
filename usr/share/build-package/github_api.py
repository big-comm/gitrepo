#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# github_api.py - GitHub API interface
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import os
import requests
from git_utils import GitUtils
from config import TOKEN_FILE

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
                logger.die("red", "Could not determine repository name.")
                return ""
            
            # Get the current commit SHA
            current_sha = GitUtils.get_current_commit_sha()
            if not current_sha:
                logger.die("red", "Could not determine current commit SHA.")
                return ""
            
            # Generate a reference name with timestamp
            from datetime import datetime
            timestamp = datetime.now().strftime("%y.%m.%d-%H%M")
            ref_name = f"{branch_type}-{timestamp}"
            
            # Create the reference in GitHub
            logger.log("cyan", f"Creating reference: {ref_name}...")
            
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
                logger.log("red", f"Error creating reference: {response.status_code}")
                return ""
            
            logger.log("green", f"Reference {ref_name} created successfully!")
            return ref_name
        except Exception as e:
            logger.log("red", f"Error creating reference: {e}")
            return ""
    
    def create_remote_branch(self, branch_type: str, logger) -> str:
        """Creates a branch directly on GitHub without triggering PR notifications"""
        try:
            repo_name = GitUtils.get_repo_name()
            if not repo_name:
                logger.die("red", "Could not determine repository name.")
                return ""
            
            # Generate a branch name with timestamp
            from datetime import datetime
            timestamp = datetime.now().strftime("%y.%m.%d-%H%M")
            new_branch_name = f"{branch_type}-{timestamp}"
            
            # Find the base branch to use
            latest_branch = self.get_latest_branch_of_type(branch_type, logger)
            base_branch = latest_branch or "main"
            
            # Get SHA of latest commit
            base_sha = self.get_branch_sha(base_branch, logger)
            if not base_sha:
                logger.log("red", f"Could not determine SHA for {base_branch}.")
                return ""
            
            # Create branch without notification by using different API endpoint
            # Instead of creating refs/heads directly, we'll create via Git DB API
            logger.log("cyan", f"Creating branch: {new_branch_name} based on {base_branch}...")
            
            # First create a Git reference
            url = f"https://api.github.com/repos/{repo_name}/git/refs"
            data = {
                "ref": f"refs/heads/{new_branch_name}",
                "sha": base_sha,
                "force": True  # Override if exists
            }
            
            response = requests.post(url, headers=self.headers, json=data)
            
            if response.status_code not in [201, 200]:
                logger.log("red", f"Error creating branch: {response.status_code}")
                logger.log("red", f"Error details: {response.text}")
                return ""
            
            # Hide branch from pull request suggestions by updating branch_protection
            # This is the crucial part to prevent PR notifications
            protection_url = f"https://api.github.com/repos/{repo_name}/branches/{new_branch_name}/protection"
            protection_data = {
                "required_status_checks": None,
                "enforce_admins": False,
                "required_pull_request_reviews": None,
                "restrictions": None,
                "required_linear_history": False
            }
            
            # Set minimal protection to hide from PR suggestions
            requests.put(
                protection_url,
                headers=self.headers,
                json=protection_data
            )
            
            logger.log("green", f"Branch {new_branch_name} created successfully!")
            return new_branch_name
        except Exception as e:
            logger.log("red", f"Error creating branch: {e}")
            return ""

    def get_latest_branch_of_type(self, branch_type: str, logger) -> str:
        """Gets the latest branch of specified type"""
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
            matching_branches = [
                b['name'] for b in branches 
                if b['name'].startswith(f"{branch_type}-")
            ]
            
            # Sort by name (assuming format type-YY.MM.DD-HHMM)
            matching_branches.sort(reverse=True)
            
            if matching_branches:
                return matching_branches[0]
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
            new_branch = self.create_remote_branch(branch_type, logger)
            if not new_branch:
                logger.log("red", "Failed to create branch for the build.")
                return False
        
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
                logger.die("red", f"Error retrieving remote repository URL for package: {package_name}")
                return False
            
            logger.log("cyan", f"Detected repository: {repo_name}")
            
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
            logger.log("cyan", "Triggering build workflow on GitHub...")
            
            response = requests.post(
                f"https://api.github.com/repos/{repo_workflow}/dispatches",
                headers=self.headers,
                json=data
            )
            
            if response.status_code != 204:
                logger.log("red", f"Error triggering workflow. Response code: {response.status_code}")
                return False
            
            logger.log("green", f"Build workflow ({event_type}) triggered successfully.")
            
            # Generate Action link
            action_url = f"https://github.com/{repo_workflow}/actions"
            logger.log("cyan", f"URL to monitor the build: {action_url}")
            
            return True
        except Exception as e:
            logger.log("red", f"Error triggering workflow: {e}")
            return False
    
    def get_github_token(self, logger) -> str:
        """Gets the GitHub token saved locally"""
        token_file = os.path.expanduser(TOKEN_FILE)
        
        if not os.path.exists(token_file):
            logger.die("red", f"Token file '{token_file}' not found.")
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
            
            logger.die("red", f"Token for organization '{self.organization}' not found.")
            return ""
        except Exception as e:
            logger.die("red", f"Error reading token: {e}")
            return ""
            
    def clean_action_jobs(self, status: str, logger) -> bool:
        """Cleans Actions jobs with specific status (success, failure)"""
        try:
            repo_name = GitUtils.get_repo_name()
            if not repo_name:
                logger.die("red", "Could not determine repository name.")
                return False
                
            logger.log("cyan", f"Cleaning Actions jobs with '{status}' status...")
            
            # Fetch workflows runs
            response = requests.get(
                f"https://api.github.com/repos/{repo_name}/actions/runs?status={status}",
                headers=self.headers
            )
            
            if response.status_code != 200:
                logger.log("red", f"Error fetching Actions jobs. Code: {response.status_code}")
                return False
                
            data = response.json()
            workflow_runs = data.get('workflow_runs', [])
            
            if not workflow_runs:
                logger.log("yellow", f"No Action jobs with '{status}' status found.")
                return True
                
            # Delete each workflow run
            deleted_count = 0
            for run in workflow_runs:
                run_id = run.get('id')
                logger.log("yellow", f"Deleting job {run_id}...")
                
                delete_response = requests.delete(
                    f"https://api.github.com/repos/{repo_name}/actions/runs/{run_id}",
                    headers=self.headers
                )
                
                if delete_response.status_code in [204, 200]:
                    deleted_count += 1
                else:
                    logger.log("red", f"Error deleting job {run_id}. Code: {delete_response.status_code}")
            
            logger.log("green", f"Deleted {deleted_count} Actions jobs with '{status}' status.")
            return True
        except Exception as e:
            logger.log("red", f"Error cleaning Actions jobs: {e}")
            return False
            
    def clean_all_tags(self, logger) -> bool:
        """Deletes all tags in the remote repository"""
        try:
            repo_name = GitUtils.get_repo_name()
            if not repo_name:
                logger.die("red", "Could not determine repository name.")
                return False
                
            logger.log("cyan", "Getting tag list...")
            
            # Fetch tags
            response = requests.get(
                f"https://api.github.com/repos/{repo_name}/tags",
                headers=self.headers
            )
            
            if response.status_code != 200:
                logger.log("red", f"Error fetching tags. Code: {response.status_code}")
                return False
                
            tags = response.json()
            
            if not tags:
                logger.log("yellow", "No tags found.")
                return True
                
            # Delete each tag
            deleted_count = 0
            for tag in tags:
                tag_name = tag.get('name')
                logger.log("yellow", f"Deleting tag {tag_name}...")
                
                # To delete a tag, we need to delete the corresponding reference
                delete_response = requests.delete(
                    f"https://api.github.com/repos/{repo_name}/git/refs/tags/{tag_name}",
                    headers=self.headers
                )
                
                if delete_response.status_code in [204, 200]:
                    deleted_count += 1
                else:
                    logger.log("red", f"Error deleting tag {tag_name}. Code: {delete_response.status_code}")
            
            logger.log("green", f"Deleted {deleted_count} tags.")
            return True
        except Exception as e:
            logger.log("red", f"Error cleaning tags: {e}")
            return False
        
    def create_pull_request(self, source_branch: str, target_branch: str = "dev", auto_merge: bool = False, logger = None) -> dict:
        """Creates a pull request and optionally merges it automatically"""
        if not source_branch:
            if logger:
                logger.log("red", "Source branch name is required to create a pull request")
            return {}
        
        # Get repository name
        repo_name = GitUtils.get_repo_name()
        if not repo_name:
            if logger:
                logger.log("cyan", f"Token length: {len(self.token) if self.token else 0}") # Debug
                logger.log("cyan", f"Repository name: {repo_name}") # Debug
                logger.log("cyan", f"Creating PR from '{source_branch}' to '{target_branch}'") #Debug
                logger.log("red", "Repository name could not be determined")
            return {}
        
        if logger:
            logger.log("cyan", f"Creating pull request from {source_branch} to {target_branch}...")
        
        # Create PR data
        pr_data = {
            "title": f"Merge {source_branch} into {target_branch}",
            "body": f"Automated PR created by build_package.py",
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
                    logger.log("red", f"Failed to create PR: {response.json().get('message', '')}")
                    logger.log("cyan", f"API response status: {response.status_code}")
                    if response.status_code not in [200, 201]: # Debug
                        logger.log("red", f"Error details: {response.text}") # Debug
                return {}
            
            pr_info = response.json()
            pr_url = pr_info.get("html_url", "")
            pr_number = pr_info.get("number", 0)
            
            if logger:
                logger.log("green", f"Pull request created successfully: {pr_url}")
            
            # Auto-merge if requested
            if auto_merge and pr_number:
                if logger:
                    logger.log("cyan", "Attempting to merge pull request automatically...")
                
                merge_url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}/merge"
                merge_response = requests.put(merge_url, headers=headers)
                
                if merge_response.status_code == 200:
                    if logger:
                        logger.log("green", "Pull request merged successfully")
                else:
                    if logger:
                        logger.log("yellow", f"Pull request created but could not be merged automatically: {merge_response.json().get('message', '')}")
            
            return pr_info
        
        except Exception as e:
            if logger:
                logger.log("red", f"Error creating pull request: {str(e)}")
            return {}