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
    
    def trigger_workflow(self, package_name: str, branch_type: str, 
                         new_branch: str, is_aur: bool, tmate_option: bool,
                         logger) -> bool:
        """Triggers a workflow on GitHub"""
        repo_workflow = f"{self.organization}/build-package"
        
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