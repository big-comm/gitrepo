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
            # Check if there are changes to commit
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                stdout=subprocess.PIPE,
                text=True,
                check=False
            ).stdout.strip()
            
            return bool(status)
        except Exception:
            return False
        
    @staticmethod
    def git_pull(logger=None) -> bool:
        """Performs git pull operation with automatic merge"""
        if not GitUtils.is_git_repo():
            if logger:
                logger.log("red", "This operation is only available in Git repositories.")
            return False
        
        try:
            # Configure Git to accept automatic merges
            subprocess.run(
                ["git", "config", "pull.rebase", "false"],
                check=True
            )
            
            # Execute git pull with automatic merge
            if logger:
                logger.log("cyan", "Pulling latest changes...")
            
            result = subprocess.run(
                ["git", "pull", "--no-edit"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True
            )
            
            if logger:
                logger.log("green", "Successfully pulled latest changes")
                
            return True
        except subprocess.CalledProcessError as e:
            if logger:
                logger.log("red", f"Error pulling changes: {e.stderr.strip()}")
            return False
    
    @staticmethod
    def update_commit_push(commit_message: str, logger) -> bool:
        """Performs commit and push of local changes"""
        if not GitUtils.is_git_repo():
            logger.die("red", "This operation is only available in Git repositories.")
            return False
        
        try:
            # Check if there are changes before proceeding
            if not GitUtils.has_changes():
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
            to_keep = ['main', 'master']
            
            # Find the latest branch of each type
            branch_types = ['testing', 'stable', 'extra']
            for branch_type in branch_types:
                # Filter all branches of this type (local + remote)
                type_branches = [
                    b for b in branches_local + branches_remote 
                    if b.startswith(f"{branch_type}-")
                ]
                
                # Sort by date (assuming format branch_type-YYYYMMDD_HHMMSS)
                type_branches.sort(reverse=True)
                
                # Add the most recent to the list of branches to keep
                if type_branches:
                    to_keep.append(type_branches[0])
            
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