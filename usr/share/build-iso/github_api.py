#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# github_api.py - GitHub API interface for build_iso.py
#

import os
import time
from datetime import datetime

import requests
from config import TOKEN_FILE
from translation_utils import _


class GitHubAPI:
    """Interface with GitHub API for ISO building"""
    
    def __init__(self, token: str, organization: str):
        self.token = token
        self.organization = organization
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"token {self.token}"
        } if token else {}
    
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
                elif line and '=' not in line:
                    # If it's just a token without a specific organization
                    return line
            
            logger.die("red", _("Token for organization '{0}' not found.").format(self.organization))
            return ""
        except Exception as e:
            logger.die("red", _("Error reading token: {0}").format(e))
            return ""
    
    def trigger_workflow(self, distroname: str, iso_profiles_repo: str, build_dir: str, 
                     edition: str, branches: dict, kernel: str, tmate: bool, logger) -> bool:
        """Triggers an ISO build workflow on GitHub"""
        # NOTE: We use self.organization to ensure that we are using the organization selected by the user
        repo_workflow = f"{self.organization}/build-iso"
        
        # Generate unique tag for the workflow
        tag = datetime.now().strftime("%Y-%m-%d_%H-%M")
        
        # Create the event type string
        # Determine ISO type based on branches (same logic as build-iso.sh)
        manjaro_branch = branches.get('manjaro', 'stable')
        biglinux_branch = branches.get('biglinux', 'stable') 
        community_branch = branches.get('community', 'stable')

        if distroname == 'bigcommunity':
            if manjaro_branch == 'stable' and community_branch == 'stable':
                iso_type = 'STABLE'
            elif manjaro_branch == 'stable' and community_branch == 'testing':
                iso_type = 'BETA'
            elif 'unstable' in [manjaro_branch, community_branch]:
                iso_type = 'DEVELOPMENT'
            else:
                iso_type = 'BETA'
        elif distroname == 'biglinux':
            if manjaro_branch == 'stable' and biglinux_branch == 'stable':
                iso_type = 'STABLE' 
            elif manjaro_branch == 'stable' and biglinux_branch == 'testing':
                iso_type = 'BETA'
            elif 'unstable' in [manjaro_branch, biglinux_branch]:
                iso_type = 'DEVELOPMENT'
            else:
                iso_type = 'BETA'
        else:
            iso_type = manjaro_branch.upper()

        event_type = f"ISO-{distroname}_{iso_type}_{edition.lower()}_{tag}"
        
        # Convert tmate boolean to string for JSON
        tmate_option = "true" if tmate else "false"
        
        # Prepare the payload
        data = {
            "event_type": event_type,
            "client_payload": {
                "distroname": distroname,
                "iso_profiles_repo": iso_profiles_repo,
                "build_dir": build_dir,
                "edition": edition,
                "manjaro_branch": branches.get("manjaro", ""),
                "community_branch": branches.get("community", ""),
                "biglinux_branch": branches.get("biglinux", ""),
                "kernel": kernel,
                "tmate": tmate_option
            }
        }
        
        try:
            logger.log("cyan", _("Triggering ISO build workflow on GitHub..."))
            
            # Print the URL being used for debugging
            workflow_url = f"https://api.github.com/repos/{repo_workflow}/dispatches"
            logger.log("cyan", _("Sending request to: {0}").format(workflow_url))
            
            response = requests.post(workflow_url, headers=self.headers, json=data, timeout=30)
            
            if response.status_code == 422:
                logger.die("red", _("Error triggering workflow (code 422). Can't have more than 10 entries in the event."))
                return False
            
            if response.status_code != 204:
                logger.die("red", _("Error triggering workflow. Response code: {0}").format(response.status_code))
                return False
            
            logger.log("green", _("ISO build workflow triggered successfully for {0}.").format(event_type))
            logger.log("yellow", _("Please check the 'Actions' tab on GitHub to monitor the build progress."))
            
            if tmate:
                logger.log("yellow", _("TMATE session will be enabled. Watch the GitHub Actions logs for connection information."))
            
            logger.log("orange", _("Waiting 3 seconds for the API to trigger the Action to get the 'id'."))
            
            # Wait a moment for the workflow to start
            time.sleep(3)
            
            # Generate Action link
            action_url = self.get_action_url(repo_workflow)
            logger.log("cyan", _("URL to monitor the build: {0}").format(action_url))
            
            return True
        except Exception as e:
            logger.log("red", _("Error triggering workflow: {0}").format(e))
            return False
        
    def get_action_url(self, repo_workflow=None) -> str:
        """Gets the URL for the Actions tab in GitHub"""
        if not repo_workflow:
            repo_workflow = f"{self.organization}/build-iso"
        
        return f"https://github.com/{repo_workflow}/actions"