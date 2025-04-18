#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# git_utils.py - Git repository utilities
#
# Copyright (c) 2025, BigCommunity Team
# All rights reserved.
#

import os
import re
import subprocess
from datetime import datetime

class GitUtils:
    """Utilities for Git repository operations"""
    
    @staticmethod
    def is_git_repo() -> bool:
        """Checks if the current directory is a Git repository"""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False
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
            result = subprocess.run(
                ["git", "config", "--get", "remote.origin.url"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False
            )
            
            if result.returncode != 0:
                return ""
            
            url = result.stdout.strip()
            
            # Pattern for https or git URLs
            match = re.search(r'[:/]([^/]+/[^.]+)(?:\.git)?$', url)
            if match:
                return match.group(1)
            return ""
        except Exception:
            return ""
    
    @staticmethod
    def get_repo_root_path() -> str:
        """Gets the root path of the Git repository"""
        if not GitUtils.is_git_repo():
            return os.getcwd()
        
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False
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
            result = subprocess.run(
                ["git", "config", "user.name"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                return result.stdout.strip()
            return ""
        except Exception:
            return ""
    
    @staticmethod
    def has_changes() -> bool:
        """Checks if there are changes in the repository"""
        try:
            # Check if there are changes to commit - simplified and more reliable
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                stdout=subprocess.PIPE,
                text=True,
                check=False
            ).stdout.strip()
            
            result = bool(status)
            print(f"Git has changes: {result} - {status}")
            return result
        except Exception as e:
            print(f"Error checking changes: {e}")
            return False
        
    @staticmethod
    def git_pull(logger=None) -> bool:
        """Performs git pull operation with automatic merge - always gets the most recent code"""
        if not GitUtils.is_git_repo():
            if logger:
                logger.log("red", "This operation is only available in Git repositories.")
            return False
        
        try:
            # Configure Git to accept automatic merges
            subprocess.run(["git", "config", "pull.rebase", "false"], check=True)
            
            # Fetch first to update branch information
            subprocess.run(["git", "fetch", "--all"], check=True)
            
            # Get current branch
            current_branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            ).stdout.strip()
            
            # First try to pull from the current branch's upstream
            if logger:
                logger.log("cyan", f"Trying to pull latest changes for current branch: {current_branch}")
                
            try:
                # Try to pull current branch first
                subprocess.run(
                    ["git", "pull", "--no-edit"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=True
                )
                if logger:
                    logger.log("green", f"Successfully pulled latest changes for {current_branch}")
                
                # Now check for newer branches to merge
                newer_branches = GitUtils.find_newer_branches(current_branch, logger)
                
                if newer_branches and logger:
                    logger.log("yellow", f"Note: Found newer branches: {', '.join(newer_branches[:3])}... but staying on current branch")
                
                return True
            except subprocess.CalledProcessError:
                # Current branch pull failed, look for alternatives
                if logger:
                    logger.log("yellow", f"Could not pull from current branch, looking for alternatives...")
                
                # Try dev branch if exists
                try:
                    # Check if dev branch exists
                    dev_exists = subprocess.run(
                        ["git", "rev-parse", "--verify", "origin/dev"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=True
                    ).returncode == 0
                    
                    if dev_exists:
                        if logger:
                            logger.log("cyan", "Trying to pull from dev branch...")
                        
                        subprocess.run(
                            ["git", "pull", "origin", "dev", "--no-edit"],
                            check=True
                        )
                        if logger:
                            logger.log("green", "Successfully pulled latest changes from dev")
                        return True
                except subprocess.CalledProcessError:
                    # Dev branch pull failed, try main
                    pass
                
                # Final fallback: try main
                if logger:
                    logger.log("cyan", "Trying to pull from main branch...")
                
                try:
                    subprocess.run(
                        ["git", "pull", "origin", "main", "--no-edit"],
                        check=True
                    )
                    if logger:
                        logger.log("green", "Successfully pulled latest changes from main")
                    return True
                except subprocess.CalledProcessError as e:
                    if logger:
                        error_msg = str(e)
                        if hasattr(e, 'stderr') and e.stderr:
                            error_msg = e.stderr.strip()
                        logger.log("red", f"Error pulling changes: {error_msg}")
                    return False
                    
        except subprocess.CalledProcessError as e:
            if logger:
                error_msg = str(e)
                if hasattr(e, 'stderr') and e.stderr:
                    error_msg = e.stderr.strip()
                logger.log("red", f"Error pulling changes: {error_msg}")
            return False
        except Exception as e:
            if logger:
                logger.log("red", f"Unexpected error: {str(e)}")
            return False

    @staticmethod
    def find_newer_branches(current_branch, logger=None):
        """Finds branches with commits newer than the current branch"""
        try:
            # Get all remote branches with their last commit date
            branches_with_dates = []
            
            # Get list of all remote branches
            remote_branches_output = subprocess.run(
                ["git", "branch", "-r"],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            ).stdout.strip().split('\n')
            
            # Get current branch's latest commit date
            current_date_output = subprocess.run(
                ["git", "log", "-1", "--format=%ct", "HEAD"],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            ).stdout.strip()
            
            if not current_date_output:
                return []
                
            current_date = int(current_date_output)
            
            # For each branch, get the last commit date
            for branch in remote_branches_output:
                branch = branch.strip()
                if branch and not branch.endswith('/HEAD'):
                    # Remove 'origin/' prefix
                    branch_name = branch.replace('origin/', '')
                    
                    # Only consider main, dev, and dev-* branches
                    if branch_name in ['main', 'dev'] or branch_name.startswith('dev-'):
                        try:
                            # Get the commit date in Unix timestamp format
                            date_output = subprocess.run(
                                ["git", "log", "-1", "--format=%ct", branch],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                                check=True
                            ).stdout.strip()
                            
                            if date_output:
                                commit_date = int(date_output)
                                # Only add branches with newer commits
                                if commit_date > current_date:
                                    branches_with_dates.append((branch_name, commit_date))
                        except (subprocess.CalledProcessError, ValueError):
                            # If we can't get the date, ignore this branch
                            pass
            
            # Sort branches by date, newest first
            branches_with_dates.sort(key=lambda x: x[1], reverse=True)
            
            # Return just the branch names
            return [branch for branch, _ in branches_with_dates]
        except Exception:
            return []
    
    @staticmethod
    def update_commit_push(commit_message: str, logger) -> bool:
        """Performs commit and push of local changes"""
        if not GitUtils.is_git_repo():
            logger.die("red", "This operation is only available in Git repositories.")
            return False
        
        try:
            changes = GitUtils.has_changes()
            logger.log("cyan", f"Changes detected: {changes}")
            
            if not changes:
                logger.log("yellow", "No changes to commit.")
                return True
            
            # Add all changes
            logger.log("cyan", "Adding changes to stage...")
            subprocess.run(["git", "add", "--all"], check=True)
            
            # Commit
            logger.log("cyan", f"Making commit: {commit_message}")
            subprocess.run(["git", "commit", "-m", commit_message], check=True)
            
            # Push changes to remote
            logger.log("cyan", "Pushing changes to remote repository...")
            subprocess.run(["git", "push", "origin", "HEAD"], check=True)
            
            logger.log("green", "Commit and push completed successfully!")
            return True
            
        except subprocess.CalledProcessError as e:
            logger.log("red", f"Error executing Git operation: {e}")
            return False
    
    @staticmethod
    def create_branch_and_push(branch_type: str, logger) -> str:
        """Creates a new branch and pushes to remote"""
        if not GitUtils.is_git_repo():
            logger.die("red", "This operation is only available in Git repositories.")
            return ""
        
        # Generate branch name with timestamp
        timestamp = datetime.now().strftime("%y.%m.%d-%H%M")
        new_branch = f"{branch_type}-{timestamp}"
        
        try:
            # Create new branch
            logger.log("cyan", f"Creating new branch: {new_branch}")
            subprocess.run(["git", "checkout", "-b", new_branch], check=True)
            
            # Push to remote
            logger.log("cyan", "Pushing new branch to remote repository...")
            subprocess.run(["git", "push", "origin", new_branch], check=True)
            
            logger.log("green", f"Branch {new_branch} created and pushed successfully!")
            return new_branch
        except subprocess.CalledProcessError as e:
            logger.log("red", f"Error creating or pushing branch: {e}")
            return ""
    
    @staticmethod
    def get_package_name() -> str:
        """Gets the package name from PKGBUILD"""
        # Look for PKGBUILD file
        repo_path = GitUtils.get_repo_root_path()
        pkgbuild_path = None
        
        for root, _, files in os.walk(repo_path):
            if "PKGBUILD" in files:
                pkgbuild_path = os.path.join(root, "PKGBUILD")
                break
        
        if not pkgbuild_path:
            return "error2"  # Error: PKGBUILD not found
        
        # Extract package name from PKGBUILD
        try:
            with open(pkgbuild_path, 'r') as f:
                pkgbuild_content = f.read()
            
            # Look for pkgname definition
            match = re.search(r'pkgname\s*=\s*[\'"]?([^\'"\n]+)[\'"]?', pkgbuild_content)
            if match:
                return match.group(1).strip()
            
            return "error3"  # Error: Package name not found
        except Exception:
            return "error3"  # Error in case of exception

    @staticmethod
    def cleanup_old_branches(logger) -> bool:
        """Cleans up old branches, keeping only main and the latest testing, stable and extra"""
        if not GitUtils.is_git_repo():
            logger.die("red", "This operation is only available in Git repositories.")
            return False
            
        try:
            # Get all branches
            logger.log("cyan", "Getting branch list...")
            
            # Update remote branches locally
            subprocess.run(["git", "fetch", "--all", "--prune"], check=True)
            
            # Get local branches
            branches_local = subprocess.run(
                ["git", "branch"],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            ).stdout.strip().split('\n')
            
            # Clean formatting
            branches_local = [b.strip('* ') for b in branches_local if b.strip()]
            
            # Get remote branches
            branches_remote = subprocess.run(
                ["git", "branch", "-r"],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            ).stdout.strip().split('\n')
            
            # Clean formatting (remove "origin/")
            branches_remote = [b.strip().replace('origin/', '') for b in branches_remote if b.strip()]
            
            # Filter branches to keep
            to_keep = ['main', 'dev', 'master']
            
            # Filter branches to keep - manter apenas os branches principais
            to_keep = ['main', 'master', 'dev']  # Branches permanentes

            # Add the most recent dev branch based on dev
            dev_branches = [
                b for b in branches_local + branches_remote 
                if b.startswith('dev-')
            ]

            # Sort chronologically (assuming format dev-YY.MM.DD-HHMM)
            dev_branches.sort(reverse=True)

            # Add only the most recent development branch
            if dev_branches:
                to_keep.append(dev_branches[0])
                if len(dev_branches) > 1:
                    logger.log("yellow", f"Keeping only the most recent dev branch: {dev_branches[0]}")
            
            # Remove local branches
            for branch in branches_local:
                if branch not in to_keep and branch not in ['main', 'master']:
                    logger.log("yellow", f"Removing local branch: {branch}")
                    try:
                        # Check if we're not on the branch
                        current_branch = subprocess.run(
                            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                            stdout=subprocess.PIPE,
                            text=True,
                            check=True
                        ).stdout.strip()
                        
                        if current_branch == branch:
                            # Switch to main/master
                            if 'main' in branches_local:
                                subprocess.run(["git", "checkout", "main"], check=True)
                            elif 'master' in branches_local:
                                subprocess.run(["git", "checkout", "master"], check=True)
                        
                        # Remove local branch
                        subprocess.run(["git", "branch", "-D", branch], check=True)
                    except subprocess.CalledProcessError as e:
                        logger.log("red", f"Error removing local branch {branch}: {e}")
            
            # Remove remote branches
            for branch in branches_remote:
                if branch not in to_keep and branch not in ['main', 'master']:
                    logger.log("yellow", f"Removing remote branch: {branch}")
                    try:
                        subprocess.run(["git", "push", "origin", "--delete", branch], check=True)
                    except subprocess.CalledProcessError as e:
                        logger.log("red", f"Error removing remote branch {branch}: {e}")
            
            logger.log("green", "Branch cleanup completed successfully!")
            return True
        except Exception as e:
            logger.log("red", f"Error during branch cleanup: {e}")
            return False
        
    @staticmethod
    def get_current_commit_sha() -> str:
        """Gets the SHA of the current commit"""
        if not GitUtils.is_git_repo():
            return ""
        
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                return result.stdout.strip()
            return ""
        except Exception:
            return ""
    @staticmethod
    def get_current_branch() -> str:
        """Gets the name of the current branch"""
        if not GitUtils.is_git_repo():
            return ""
        
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stdout=subprocess.PIPE,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                return result.stdout.strip()
            return ""
        except Exception:
            return ""