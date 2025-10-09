#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# github_api_fixed.py - Fixed version with automatic conflict resolution
#

import os
import requests
import subprocess
import time
from .git_utils import GitUtils
from .config import TOKEN_FILE
from .translation_utils import _

class GitHubAPI:
    """Interface with GitHub API - Fixed version with automatic conflict resolution"""
    
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
            
            # Generate a branch name with username
            username = GitUtils.get_github_username() or "unknown"
            new_branch_name = f"dev-{username}"  # Use dev- prefix with username

            # STEP 1: Check if branch already exists
            logger.log("cyan", _("Checking if branch {0} already exists...").format(new_branch_name))
            check_response = requests.get(
                f"https://api.github.com/repos/{repo_name}/branches/{new_branch_name}",
                headers=self.headers
            )
            
            if check_response.status_code == 200:
                # Branch already exists, use it
                logger.log("green", _("Branch {0} already exists - using existing branch").format(new_branch_name))
                return new_branch_name
            
            # STEP 2: Branch doesn't exist, create it
            # Use dev branch as base, or main if dev doesn't exist
            base_branch = self.get_branch_sha("dev", logger) and "dev" or "main"
            
            base_sha = self.get_branch_sha(base_branch, logger)
            if not base_sha:
                logger.log("red", _("Could not determine SHA for {0}.").format(base_branch))
                return ""
            
            logger.log("cyan", _("Creating new branch: {0} based on {1}...").format(new_branch_name, base_branch))
            
            # Create a Git reference
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

    def resolve_conflicts_automatically(self, source_branch: str, target_branch: str, logger) -> bool:
        """
        Resolve conflicts automatically by updating source branch with target
        """
        logger.log("cyan", _("Resolving conflicts automatically..."))
        
        try:
            # Save current branch to restore later
            current_branch = GitUtils.get_current_branch()
            
            # Backup local changes if they exist
            has_local_changes = GitUtils.has_changes()
            stashed = False
            
            if has_local_changes:
                logger.log("cyan", _("Backing up local changes..."))
                stash_result = subprocess.run(
                    ["git", "stash", "push", "-m", "auto-backup-before-conflict-resolution"], 
                    capture_output=True, text=True, check=False
                )
                stashed = stash_result.returncode == 0
            
            # Fetch latest changes
            logger.log("cyan", _("Updating remote references..."))
            subprocess.run(["git", "fetch", "--all"], check=True)
            
            # Switch to source branch
            logger.log("cyan", _("Switching to branch {0}...").format(source_branch))
            subprocess.run(["git", "checkout", source_branch], check=True)
            
            # Pull latest source branch
            subprocess.run(["git", "pull", "origin", source_branch], check=True)
            
            # Try to merge target branch into source branch
            logger.log("cyan", _("Merging {0} into {1}...").format(target_branch, source_branch))
            
            # Strategy 1: Try normal merge
            merge_result = subprocess.run(
                ["git", "merge", f"origin/{target_branch}", "--no-edit"],
                capture_output=True, text=True
            )
            
            if merge_result.returncode == 0:
                logger.log("green", _("Merge completed without conflicts!"))
            else:
                # Strategy 2: Merge with conflict resolution strategy
                logger.log("yellow", _("Conflicts detected, resolving automatically..."))
                
                # Abort current merge
                subprocess.run(["git", "merge", "--abort"], capture_output=True)
                
                # Try merge with strategy (favor source branch changes)
                merge_result = subprocess.run(
                    ["git", "merge", f"origin/{target_branch}", "--strategy-option=ours", "--no-edit"],
                    capture_output=True, text=True
                )
                
                if merge_result.returncode != 0:
                    # Strategy 3: Nuclear option - reset to main and apply changes
                    logger.log("yellow", _("Using advanced resolution strategy..."))
                    
                    # Get the diff of changes in source branch
                    diff_result = subprocess.run(
                        ["git", "diff", f"origin/{target_branch}...{source_branch}"],
                        capture_output=True, text=True, check=True
                    )
                    
                    if diff_result.stdout.strip():
                        # Reset to target branch
                        subprocess.run(["git", "reset", "--hard", f"origin/{target_branch}"], check=True)
                        
                        # Try to apply the diff
                        patch_process = subprocess.Popen(
                            ["git", "apply", "--3way"],
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True
                        )
                        
                        patch_output, patch_error = patch_process.communicate(input=diff_result.stdout)
                        
                        if patch_process.returncode == 0:
                            # Add and commit the resolved changes
                            subprocess.run(["git", "add", "."], check=True)
                            subprocess.run(["git", "commit", "-m", f"Auto-resolve conflicts: merge {target_branch} into {source_branch}"], check=True)
                            logger.log("green", _("Conflicts resolved automatically!"))
                        else:
                            logger.log("red", _("Could not resolve conflicts automatically"))
                            return False
                    else:
                        logger.log("green", _("No differences detected"))
            
            # Push resolved branch
            logger.log("cyan", _("Pushing resolved branch..."))
            subprocess.run(["git", "push", "origin", source_branch], check=True)
            
            # Restore original branch
            if current_branch != source_branch:
                subprocess.run(["git", "checkout", current_branch], check=True)
            
            # Restore stashed changes
            if stashed:
                logger.log("cyan", _("Restoring local changes..."))
                subprocess.run(["git", "stash", "pop"], capture_output=True)
            
            logger.log("green", _("Conflict resolution completed successfully!"))
            return True
            
        except subprocess.CalledProcessError as e:
            logger.log("red", _("Error during conflict resolution: {0}").format(e))
            
            # Try to restore original state
            try:
                if current_branch:
                    subprocess.run(["git", "checkout", current_branch], capture_output=True)
                if stashed:
                    subprocess.run(["git", "stash", "pop"], capture_output=True)
            except:
                pass
                
            return False
        except Exception as e:
            logger.log("red", _("Unexpected error: {0}").format(e))
            return False

    def wait_for_pr_checks(self, pr_number: int, logger, max_wait: int = 30) -> tuple[bool, str]:
        """
        Wait for PR to be ready for merge by checking status periodically
        """
        repo_name = GitUtils.get_repo_name()
        if not repo_name:
            return False, "unknown"
        
        logger.log("cyan", _("Waiting for PR to be ready for merge..."))
        
        for attempt in range(max_wait):
            try:
                response = requests.get(
                    f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}",
                    headers=self.headers
                )
                
                if response.status_code == 200:
                    pr_data = response.json()
                    mergeable = pr_data.get('mergeable')
                    mergeable_state = pr_data.get('mergeable_state')
                    
                    logger.log("cyan", _("Attempt {0}/{1}: mergeable={2}, state={3}").format(
                        attempt + 1, max_wait, mergeable, mergeable_state))
                    
                    if mergeable is True and mergeable_state == 'clean':
                        logger.log("green", _("PR ready for merge!"))
                        return True, mergeable_state
                    elif mergeable is False and mergeable_state == 'dirty':
                        logger.log("red", _("PR has conflicts"))
                        return False, mergeable_state
                    elif mergeable_state in ['unknown', 'checking']:
                        if attempt < max_wait - 1:
                            time.sleep(2)
                            continue
                    else:
                        logger.log("yellow", _("Unexpected state: {0}").format(mergeable_state))
                        return False, mergeable_state
                else:
                    logger.log("red", _("Error checking PR: {0}").format(response.status_code))
                    return False, "error"
                    
            except Exception as e:
                logger.log("red", _("Error: {0}").format(e))
                return False, "error"
        
        logger.log("yellow", _("Timeout waiting for PR to be ready"))
        return False, "timeout"

    def trigger_workflow(self, package_name: str, branch_type: str, 
                        new_branch: str, is_aur: bool, tmate_option: bool,
                        logger) -> bool:
        """Triggers a workflow on GitHub"""
        repo_workflow = f"{self.organization}/build-package"
        
        # If new_branch is empty, create a branch directly via API
        if not new_branch and not is_aur and branch_type != "stable" and branch_type != "extra":
            # Only create new branch for types different from stable/extra
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
            
            # CRITICAL FIX: Determine the correct branch to send to workflow
            if branch_type == "testing":
                # Testing always uses dev-* branch
                workflow_branch = new_branch
                logger.log("green", _("Testing package: workflow will use branch {0}").format(workflow_branch))
            else:
                # For stable/extra, determine if we successfully merged to main
                current_branch = GitUtils.get_current_branch()
                
                if current_branch == "main":
                    # We're on main, check if it has latest changes
                    try:
                        # Get latest commit hash from main
                        main_commit = subprocess.run(
                            ["git", "rev-parse", "HEAD"],
                            stdout=subprocess.PIPE, text=True, check=True
                        ).stdout.strip()
                        
                        # Get latest commit hash from source branch (if different from main)
                        if new_branch and new_branch != "main":
                            source_commit = subprocess.run(
                                ["git", "rev-parse", f"origin/{new_branch}"],
                                stdout=subprocess.PIPE, text=True, check=True
                            ).stdout.strip()
                            
                            if main_commit == source_commit:
                                workflow_branch = "main"
                                logger.log("green", _("Stable/Extra package: main is up-to-date, workflow will use main"))
                            else:
                                # Main doesn't have latest changes, use source branch
                                workflow_branch = new_branch
                                logger.log("yellow", _("Stable/Extra package: main not up-to-date, workflow will use {0}").format(workflow_branch))
                                logger.log("yellow", _("⚠️  Warning: Package will be built from {0} instead of main").format(workflow_branch))
                        else:
                            workflow_branch = "main"
                            logger.log("green", _("Stable/Extra package: workflow will use main"))
                            
                    except subprocess.CalledProcessError:
                        # If we can't determine, use current branch
                        workflow_branch = current_branch
                        logger.log("yellow", _("Could not verify branch status, using current: {0}").format(workflow_branch))
                else:
                    # We're not on main, use current branch
                    workflow_branch = current_branch
                    logger.log("yellow", _("Stable/Extra package: not on main, workflow will use {0}").format(workflow_branch))
                    logger.log("yellow", _("⚠️  Warning: Package will be built from {0} instead of main").format(workflow_branch))
            
            # Prepare payload data
            payload = {
                "branch": workflow_branch,
                "branch_type": branch_type,
                "build_env": "normal",
                "url": f"https://github.com/{repo_name}",
                "tmate": tmate_option
            }
            
            # Only add new_branch if it's different from workflow_branch (avoid redundancy)
            if branch_type == "testing" and new_branch and new_branch != workflow_branch:
                payload["new_branch"] = new_branch
            
            data = {
                "event_type": package_name,
                "client_payload": payload
            }
            event_type = "package-build"  # ← ESTA LINHA ERA NECESSÁRIA!
            
            # Log what we're sending to the workflow (clean)
            logger.log("cyan", _("Workflow payload:"))
            logger.log("cyan", _("  - branch: {0}").format(workflow_branch))
            logger.log("cyan", _("  - branch_type: {0}").format(branch_type))
            if payload.get("new_branch"):
                logger.log("cyan", _("  - new_branch: {0}").format(payload["new_branch"]))
        
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
                elif line and '=' not in line:
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
        
    def create_pull_request(self, source_branch: str, target_branch: str = "main", auto_merge: bool = False, logger = None) -> dict:
        """
        Creates pull request with automatic conflict resolution and robust auto-merge
        """
        if not source_branch:
            if logger:
                logger.log("red", _("Source branch name is required to create a pull request"))
            return {}
        
        # Get repository name
        repo_name = GitUtils.get_repo_name()
        if not repo_name:
            if logger:
                logger.log("red", _("Repository name could not be determined"))
            return {}
        
        if logger:
            logger.log("cyan", _("Creating pull request: {0} → {1}").format(source_branch, target_branch))
        
        # STEP 1: Resolve conflicts BEFORE creating the PR
        if auto_merge:
            if logger:
                logger.log("cyan", _("Resolving possible conflicts before merge..."))
            
            conflicts_resolved = self.resolve_conflicts_automatically(source_branch, target_branch, logger)
            if not conflicts_resolved:
                if logger:
                    logger.log("yellow", _("Warning: Could not resolve conflicts automatically"))
                    logger.log("yellow", _("Trying to create PR anyway..."))
        
        # STEP 2: Create the PR
        pr_data = {
            "title": _("Merge {0} into {1}").format(source_branch, target_branch),
            "body": _("Automated PR created by build_package.py") + "\n\n" + 
                   _("Conflicts resolved automatically (if any)") + "\n" +
                   _("Ready for automatic merge"),
            "head": source_branch,
            "base": target_branch
        }
        
        try:
            url = f"https://api.github.com/repos/{repo_name}/pulls"
            response = requests.post(url, json=pr_data, headers=self.headers)
            
            if response.status_code not in [200, 201]:
                if logger:
                    error_msg = response.json().get('message', '') if response.text else 'Unknown error'
                    logger.log("red", _("Failed to create PR: {0}").format(error_msg))
                return {}
            
            pr_info = response.json()
            pr_url = pr_info.get("html_url", "")
            pr_number = pr_info.get("number", 0)
            
            if logger:
                logger.log("green", _("Pull request created successfully: {0}").format(pr_url))
            
            # STEP 3: Auto-merge if requested
            if auto_merge and pr_number:
                if logger:
                    logger.log("cyan", _("Starting auto-merge process..."))
                
                # Wait for PR to be ready
                is_ready, pr_state = self.wait_for_pr_checks(pr_number, logger)
                
                if is_ready:
                    # Try merge with complete payload (confirmed working method)
                    merge_url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}/merge"
                    merge_data = {
                        "commit_title": _("Auto-merge: {0} → {1}").format(source_branch, target_branch),
                        "commit_message": _("Automated merge performed by build_package.py"),
                        "merge_method": "merge"
                    }
                    
                    merge_response = requests.put(merge_url, json=merge_data, headers=self.headers)
                    
                    if merge_response.status_code == 200:
                        merge_info = merge_response.json()
                        if logger:
                            logger.log("green", _("AUTO-MERGE COMPLETED SUCCESSFULLY!"))
                            logger.log("green", _("SHA: {0}").format(merge_info.get('sha', 'N/A')))
                        
                        # Add merge info to pr_info
                        pr_info['auto_merged'] = True
                        pr_info['merge_sha'] = merge_info.get('sha')
                    else:
                        merge_error = merge_response.json() if merge_response.text else {}
                        if logger:
                            logger.log("red", _("Auto-merge failed: {0}").format(
                                merge_error.get('message', 'Unknown error')))
                            logger.log("yellow", _("PR created but must be merged manually"))
                        
                        pr_info['auto_merged'] = False
                        pr_info['merge_error'] = merge_error.get('message', 'Unknown error')
                else:
                    if logger:
                        logger.log("yellow", _("PR not ready for merge (state: {0})").format(pr_state))
                        logger.log("yellow", _("PR created but must be merged manually"))
                    
                    pr_info['auto_merged'] = False
                    pr_info['merge_error'] = f"PR not ready: {pr_state}"
            
            # Show operation summary
            if pr_info and pr_number:
                self._show_pr_summary(pr_info, source_branch, target_branch, auto_merge, logger)
            
            return pr_info
        
        except Exception as e:
            if logger:
                logger.log("red", _("Error creating pull request: {0}").format(str(e)))
            return {}

    def _show_pr_summary(self, pr_info: dict, source_branch: str, target_branch: str, auto_merge: bool, logger):
        """Show pull request operation summary"""
        try:
            from menu_system import MenuSystem
            menu = MenuSystem(logger)
            
            pr_number = pr_info.get('number', 'unknown')
            pr_url = pr_info.get('html_url', '')
            
            summary_lines = [
                f"🎉 **{_('PULL REQUEST COMPLETED SUCCESSFULLY!')}**",
                f"",
                f"🔗 {_('PR #{0} created and processed').format(pr_number)}",
                f"🌿 {source_branch} → {target_branch}",
            ]
            
            if pr_info.get('auto_merged'):
                summary_lines.extend([
                    f"⚡ {_('Auto-merge')}: **{_('SUCCESS')}**",
                    f"✅ {_('Code automatically merged to target branch')}",
                    f"🎯 {_('Merge SHA')}: {pr_info.get('merge_sha', 'unknown')[:7]}"
                ])
            else:
                summary_lines.extend([
                    f"⏳ {_('Manual merge required')}",
                    f"🌐 {pr_url}"
                ])
            
            summary_lines.extend([
                f"",
                f"📋 **{_('Operation completed successfully!')}**"
            ])
            
            summary_text = '\n'.join(summary_lines)
            
            menu.show_menu(
                f"✅ {_('PULL REQUEST COMPLETED')}",
                [_("Press Enter to return to menu")],
                additional_content=summary_text
            )
        except Exception as e:
            if logger:
                logger.log("yellow", f"Could not show PR summary: {e}")