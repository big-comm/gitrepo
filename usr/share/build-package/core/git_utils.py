#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# git_utils.py - Git repository utilities
#

import os
import re
import subprocess
import requests
from .config import TOKEN_FILE
from datetime import datetime
from .translation_utils import _

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
        """Gets the real GitHub username from authenticated user"""
        try:
            # First: try to get authenticated user from GitHub API
            
            
            token_file = os.path.expanduser(TOKEN_FILE)
            if os.path.exists(token_file):
                try:
                    with open(token_file, 'r') as f:
                        token_lines = f.readlines()
                    
                    # Get token (try organization-specific or general token)
                    token = None
                    for line in token_lines:
                        line = line.strip()
                        if '=' in line:
                            org, t = line.split('=', 1)
                            token = t
                            break
                        elif line and '=' not in line:
                            token = line
                            break
                    
                    if token:
                        # Use GitHub API to get authenticated user
                        headers = {
                            "Authorization": f"token {token}",
                            "Accept": "application/vnd.github.v3+json"
                        }
                        
                        response = requests.get("https://api.github.com/user", headers=headers)
                        if response.status_code == 200:
                            user_data = response.json()
                            username = user_data.get('login', '')
                            if username:
                                return username
                except Exception:
                    pass
            
            # Second: try git config github.user (if configured)
            result = subprocess.run(
                ["git", "config", "github.user"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                username = result.stdout.strip()
                if username:
                    return username
            
            # Third: try to extract from user.email if it's a GitHub email
            result = subprocess.run(
                ["git", "config", "user.email"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                email = result.stdout.strip()
                # If email format is username@users.noreply.github.com
                github_email_match = re.search(r'^(\d+\+)?([^@]+)@users\.noreply\.github\.com$', email)
                if github_email_match:
                    return github_email_match.group(2)
            
            # Fourth: fallback to "unknown"
            return "unknown"
            
        except Exception:
            return "unknown"
    
    @staticmethod
    def has_changes() -> bool:
        """Checks if there are changes in the repository"""
        try:
            # Check if there are changes to commit - simplified and more reliable
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False
            ).stdout.strip()
            
            return bool(status)
        except Exception:
            return False
        
    @staticmethod
    def git_pull(logger=None) -> bool:
        """Performs git pull operation, prioritizing the most recent branch"""
        if not GitUtils.is_git_repo():
            if logger:
                logger.log("red", _("This operation is only available in Git repositories."))
            return False
        
        try:
            # Check and abort any merge in progress
            merge_head_path = os.path.join(GitUtils.get_repo_root_path(), '.git', 'MERGE_HEAD')
            if os.path.exists(merge_head_path):
                if logger:
                    logger.log("yellow", _("Aborting merge in progress..."))
                subprocess.run(["git", "merge", "--abort"], capture_output=True, check=False)
            
            # Check for unmerged files and reset if needed
            status_result = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False
            )
            if status_result.stdout.strip():
                if logger:
                    logger.log("yellow", _("Resolving conflicts automatically..."))
                subprocess.run(["git", "reset", "--hard", "HEAD"], check=True)
            
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
            
            if logger:
                # logger.log("cyan", f"Current branch: {current_branch}")
                logger.log("cyan", _("Current branch: {0}").format(logger.format_branch_name(current_branch)))
            
            # Find the most recent branch
            branches_output = subprocess.run(
                ["git", "for-each-ref", "--sort=-committerdate", "refs/remotes/origin", "--format=%(refname:short)"],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            ).stdout.strip().split('\n')
            
            # Filter relevant branches (dev, dev-*) and remove origin/ prefix
            relevant_branches = []
            for branch in branches_output:
                branch = branch.strip()
                if branch:
                    branch_name = branch.replace('origin/', '')
                    if branch_name == 'dev' or branch_name.startswith('dev-'):
                        relevant_branches.append(branch_name)
            
            most_recent_branch = relevant_branches[0] if relevant_branches else 'dev'
            
            if logger:
                # logger.log("cyan", f"Most recent branch identified: {most_recent_branch}")
                logger.log("cyan", _("Most recent branch identified: {0}").format(logger.format_branch_name(most_recent_branch)))
            
            # Try to pull from most recent branch first
            try:
                if logger:
                    # logger.log("cyan", f"Pulling latest changes from most recent branch: {most_recent_branch}")
                    logger.log("cyan", _("Pulling latest changes from most recent branch: {0}").format(logger.format_branch_name(most_recent_branch)))
                
                subprocess.run(
                    ["git", "pull", "origin", most_recent_branch, "--rebase", "--no-edit"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=True
                )
                
                if logger:
                    logger.log("green", _("Successfully pulled latest changes from {0}").format(most_recent_branch))
                return True
                
            except subprocess.CalledProcessError:
                # If most recent branch pull fails, try current branch
                if logger:
                    logger.log("yellow", _("Failed to pull from {0}, trying current branch: {1}").format(most_recent_branch, current_branch))
                
                try:
                    subprocess.run(
                        ["git", "pull", "origin", current_branch, "--rebase", "--no-edit"],
                        check=True
                    )
                    
                    if logger:
                        logger.log("green", _("Successfully pulled latest changes from {0}").format(current_branch))
                    return True
                    
                except subprocess.CalledProcessError:
                    # If both fail, try dev as last resort
                    if logger:
                        logger.log("yellow", _("Failed to pull from current branch, trying dev branch"))
                    
                    try:
                        subprocess.run(
                            ["git", "pull", "origin", "dev", "--rebase", "--no-edit"],
                            check=True
                        )
                        
                        if logger:
                            logger.log("green", _("Successfully pulled latest changes from dev"))
                        return True
                        
                    except subprocess.CalledProcessError as e:
                        if logger:
                            error_msg = str(e)
                            if hasattr(e, 'stderr') and e.stderr:
                                error_msg = e.stderr.strip()
                            logger.log("red", _("Error pulling changes: {0}").format(error_msg))
                        return False
                    
        except Exception as e:
            if logger:
                logger.log("red", _("Unexpected error: {0}").format(str(e)))
            return False

    @staticmethod
    def get_most_recent_branch(logger=None):
        """Finds the branch with the most recent commit"""
        try:
            # Get list of all remote branches
            branches_output = subprocess.run(
                ["git", "for-each-ref", "--sort=-committerdate", "refs/remotes/origin", "--format=%(refname:short)"],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            ).stdout.strip().split('\n')
            
            # Filter relevant branches and remove origin/ prefix
            relevant_branches = []
            for branch in branches_output:
                branch = branch.strip()
                if branch:
                    branch_name = branch.replace('origin/', '')
                    if branch_name in ['dev'] or branch_name.startswith('dev-'):
                        relevant_branches.append(branch_name)
            
            if relevant_branches:
                return relevant_branches[0]  # The first branch is the most recent
            return 'dev'  # Default to dev if no relevant branches are found
            
        except Exception as e:
            if logger:
                logger.log("red", _("Error finding most recent branch: {0}").format(e))
            return 'dev'
    
    @staticmethod
    def create_branch_and_push(branch_type: str, logger) -> str:
        """Creates a new branch and pushes to remote"""
        if not GitUtils.is_git_repo():
            logger.die("red", _("This operation is only available in Git repositories."))
            return ""
        
        # Generate branch name with username (only for AUR, others use different logic)
        if branch_type == "aur":
            timestamp = datetime.now().strftime("%y.%m.%d-%H%M") 
            new_branch = f"{branch_type}-{timestamp}"  # Keep timestamp for AUR
        else:
            username = GitUtils.get_github_username() or "unknown"
            new_branch = f"{branch_type}-{username}"
        
        try:
            # Check if branch already exists locally
            local_branches = subprocess.run(
                ["git", "branch", "--list", new_branch],
                stdout=subprocess.PIPE,
                text=True,
                check=False
            ).stdout.strip()
            
            if local_branches:
                # Branch exists locally, just checkout
                logger.log("cyan", _("Switching to existing branch: {0}").format(new_branch))
                subprocess.run(["git", "checkout", new_branch], check=True)
            else:
                # Check if branch exists remotely
                remote_check = subprocess.run(
                    ["git", "ls-remote", "--heads", "origin", new_branch],
                    stdout=subprocess.PIPE,
                    text=True,
                    check=False
                ).stdout.strip()
                
                if remote_check:
                    # Branch exists remotely, checkout and track
                    logger.log("cyan", _("Checking out remote branch: {0}").format(new_branch))
                    subprocess.run(["git", "checkout", "-t", f"origin/{new_branch}"], check=True)
                else:
                    # Branch doesn't exist, create it
                    logger.log("cyan", _("Creating new branch: {0}").format(new_branch))
                    subprocess.run(["git", "checkout", "-b", new_branch], check=True)
            
            # Push to remote (with -u to set upstream)
            logger.log("cyan", _("Pushing branch to remote repository..."))
            subprocess.run(["git", "push", "-u", "origin", new_branch], check=True)
            
            logger.log("green", _("Branch {0} ready and pushed!").format(new_branch))
            return new_branch
        except subprocess.CalledProcessError as e:
            logger.log("red", _("Error creating or pushing branch: {0}").format(e))
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
            logger.die("red", _("This operation is only available in Git repositories."))
            return False
            
        try:
            # Get all branches
            logger.log("cyan", _("Getting branch list..."))
            
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
                    logger.log("yellow", _("Keeping only the most recent dev branch: {0}").format(dev_branches[0]))
            
            # Remove local branches
            for branch in branches_local:
                if branch not in to_keep and branch not in ['main', 'master']:
                    logger.log("yellow", _("Removing local branch: {0}").format(branch))
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
                        logger.log("red", _("Error removing local branch {0}: {1}").format(branch, e))
            
            # Remove remote branches
            for branch in branches_remote:
                if branch not in to_keep and branch not in ['main', 'master']:
                    logger.log("yellow", _("Removing remote branch: {0}").format(branch))
                    try:
                        subprocess.run(["git", "push", "origin", "--delete", branch], check=True)
                    except subprocess.CalledProcessError as e:
                        logger.log("red", _("Error removing remote branch {0}: {1}").format(branch, e))
            
            logger.log("green", _("Branch cleanup completed successfully!"))
            return True
        except Exception as e:
            logger.log("red", _("Error during branch cleanup: {0}").format(e))
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
    
    @staticmethod
    def check_branch_divergence(branch: str = None) -> dict:
        """
        Verifica se o branch local divergiu do remoto.
        
        Args:
            branch: Nome do branch (usa o atual se não especificado)
        
        Returns:
            dict com:
            - diverged: bool - Se há divergência (ambos têm commits únicos)
            - ahead: int - Commits locais à frente do remoto
            - behind: int - Commits atrás do remoto  
            - local_commits: list - Lista de (sha, mensagem) dos commits locais
            - remote_commits: list - Lista de (sha, mensagem) dos commits remotos
            - error: str - Mensagem de erro se houver
        """
        result = {
            'diverged': False,
            'ahead': 0,
            'behind': 0,
            'local_commits': [],
            'remote_commits': [],
            'error': None
        }
        
        if not GitUtils.is_git_repo():
            result['error'] = _("Not a git repository")
            return result
        
        try:
            # Get current branch if not specified
            if not branch:
                branch = GitUtils.get_current_branch()
            
            if not branch:
                result['error'] = _("Could not determine current branch")
                return result
            
            # Fetch latest from remote first
            subprocess.run(
                ["git", "fetch", "origin", branch],
                capture_output=True,
                check=False
            )
            
            # Check if remote branch exists
            remote_check = subprocess.run(
                ["git", "rev-parse", "--verify", f"origin/{branch}"],
                capture_output=True,
                check=False
            )
            
            if remote_check.returncode != 0:
                # Remote branch doesn't exist - not diverged, just needs push
                result['ahead'] = 1  # At least current commit needs push
                return result
            
            # Count commits ahead (local commits not in remote)
            ahead_result = subprocess.run(
                ["git", "rev-list", "--count", f"origin/{branch}..HEAD"],
                capture_output=True,
                text=True,
                check=False
            )
            
            if ahead_result.returncode == 0:
                result['ahead'] = int(ahead_result.stdout.strip() or "0")
            
            # Count commits behind (remote commits not in local)
            behind_result = subprocess.run(
                ["git", "rev-list", "--count", f"HEAD..origin/{branch}"],
                capture_output=True,
                text=True,
                check=False
            )
            
            if behind_result.returncode == 0:
                result['behind'] = int(behind_result.stdout.strip() or "0")
            
            # Diverged = both ahead AND behind
            result['diverged'] = result['ahead'] > 0 and result['behind'] > 0
            
            # If diverged, get commit details for user information
            if result['diverged']:
                # Get local commits (not in remote)
                local_log = subprocess.run(
                    ["git", "log", "--oneline", f"origin/{branch}..HEAD"],
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if local_log.returncode == 0 and local_log.stdout.strip():
                    for line in local_log.stdout.strip().split('\n'):
                        if line:
                            parts = line.split(' ', 1)
                            sha = parts[0]
                            msg = parts[1] if len(parts) > 1 else ""
                            result['local_commits'].append((sha, msg))
                
                # Get remote commits (not in local)
                remote_log = subprocess.run(
                    ["git", "log", "--oneline", f"HEAD..origin/{branch}"],
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if remote_log.returncode == 0 and remote_log.stdout.strip():
                    for line in remote_log.stdout.strip().split('\n'):
                        if line:
                            parts = line.split(' ', 1)
                            sha = parts[0]
                            msg = parts[1] if len(parts) > 1 else ""
                            result['remote_commits'].append((sha, msg))
            
            return result
            
        except Exception as e:
            result['error'] = str(e)
            return result
    
    @staticmethod
    def resolve_divergence(branch: str, method: str, logger=None) -> bool:
        """
        Resolve divergência entre branch local e remoto.
        
        Args:
            branch: Nome do branch
            method: Método de resolução ('rebase', 'merge', 'force_push')
            logger: Logger para mensagens
        
        Returns:
            bool: True se resolvido com sucesso
        """
        if not GitUtils.is_git_repo():
            if logger:
                logger.log("red", _("Not a git repository"))
            return False
        
        try:
            if method == 'rebase':
                # Pull with rebase - applies local commits on top of remote
                if logger:
                    logger.log("cyan", _("Pulling with rebase..."))
                
                result = subprocess.run(
                    ["git", "pull", "--rebase", "origin", branch],
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if result.returncode != 0:
                    # Check for conflicts
                    if "conflict" in result.stderr.lower() or "conflict" in result.stdout.lower():
                        if logger:
                            logger.log("yellow", _("⚠️ Rebase conflicts detected!"))
                            logger.log("white", _("Resolve conflicts in the marked files, then:"))
                            logger.log("white", _("  1. Edit files to resolve conflicts"))
                            logger.log("white", _("  2. git add <resolved-files>"))
                            logger.log("white", _("  3. git rebase --continue"))
                            logger.log("white", _("Or abort with: git rebase --abort"))
                        return False
                    else:
                        if logger:
                            logger.log("red", _("Rebase failed: {0}").format(
                                result.stderr.strip() or result.stdout.strip()
                            ))
                        return False
                
                if logger:
                    logger.log("green", _("✓ Rebase successful"))
                return True
                
            elif method == 'merge':
                # Pull with merge - creates merge commit
                if logger:
                    logger.log("cyan", _("Pulling with merge..."))
                
                result = subprocess.run(
                    ["git", "pull", "--no-rebase", "origin", branch],
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if result.returncode != 0:
                    if "conflict" in result.stderr.lower() or "conflict" in result.stdout.lower():
                        if logger:
                            logger.log("yellow", _("⚠️ Merge conflicts detected!"))
                            logger.log("white", _("Resolve conflicts in the marked files, then:"))
                            logger.log("white", _("  1. Edit files to resolve conflicts"))
                            logger.log("white", _("  2. git add <resolved-files>"))
                            logger.log("white", _("  3. git commit"))
                            logger.log("white", _("Or abort with: git merge --abort"))
                        return False
                    else:
                        if logger:
                            logger.log("red", _("Merge failed: {0}").format(
                                result.stderr.strip() or result.stdout.strip()
                            ))
                        return False
                
                if logger:
                    logger.log("green", _("✓ Merge successful"))
                return True
                
            elif method == 'force_push':
                # Force push with lease - safer than --force
                if logger:
                    logger.log("yellow", _("⚠️ Force pushing (this overwrites remote!)..."))
                
                result = subprocess.run(
                    ["git", "push", "--force-with-lease", "origin", branch],
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if result.returncode != 0:
                    if logger:
                        logger.log("red", _("Force push failed: {0}").format(
                            result.stderr.strip() or result.stdout.strip()
                        ))
                    return False
                
                if logger:
                    logger.log("green", _("✓ Force push successful"))
                return True
            
            else:
                if logger:
                    logger.log("red", _("Unknown resolution method: {0}").format(method))
                return False
                
        except Exception as e:
            if logger:
                logger.log("red", _("Error resolving divergence: {0}").format(e))
            return False