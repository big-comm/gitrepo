#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GitRepo - Nautilus Extension
Adds a context menu option to open Git repositories in GitRepo application.
Only shows the menu item for directories containing a .git folder.
"""

import gettext
import subprocess
from pathlib import Path
from urllib.parse import unquote

# Import 'gi' and explicitly require GTK and Nautilus versions.
import gi
gi.require_version('Gtk', '4.0')

from gi.repository import GObject, Nautilus

# --- Internationalization (i18n) Setup ---
APP_NAME = "gitrepo"

try:
    gettext.textdomain(APP_NAME)
except Exception as e:
    print(f"GitRepo Extension: Could not set up localization: {e}")

_ = gettext.gettext


class GitRepoExtension(GObject.GObject, Nautilus.MenuProvider):
    """
    Provides the context menu items for Nautilus to open Git repositories.
    """

    def __init__(self):
        """Initializes the extension."""
        super().__init__()
        # Use absolute path to ensure it works in Nautilus environment
        self.app_executable = '/usr/bin/gitrepo'

    def get_file_items(self, *args):
        """
        Returns menu items for the selected files or folders.
        Only shows menu for directories that are Git repositories.
        """
        files = args[-1]

        # Only work with single directory selection
        if len(files) != 1:
            return []
        
        file_info = files[0]
        
        # Must be a directory
        if not file_info.is_directory():
            return []
        
        # Get the path
        folder_path = self._get_file_path(file_info)
        if not folder_path:
            return []
        
        # Check if it's inside a Git repository (search up directory tree)
        git_root = self._find_git_root(folder_path)
        if not git_root:
            return []
        
        # It's inside a Git repository - show the menu
        label = _('Open in GitRepo')
        menu_item = Nautilus.MenuItem(
            name='GitRepo::Open',
            label=label,
            tip=_('Manage this Git repository with GitRepo')
        )
        # Pass the git root as the path to open
        menu_item.connect('activate', self._launch_application_path, git_root)
        return [menu_item]

    def get_background_items(self, *args):
        """
        Returns menu items for the background (empty area) of a folder.
        Shows menu if the current folder is a Git repository.
        """
        # The current folder is passed as the file argument
        current_folder = args[-1] if args else None
        
        if not current_folder:
            return []
        
        folder_path = self._get_file_path(current_folder)
        if not folder_path:
            return []
        
        # Check if current folder is inside a Git repository
        git_root = self._find_git_root(folder_path)
        if not git_root:
            return []
        
        label = _('Open in GitRepo')
        menu_item = Nautilus.MenuItem(
            name='GitRepo::OpenBackground',
            label=label,
            tip=_('Manage this Git repository with GitRepo')
        )
        # Pass the git root as the path to open
        menu_item.connect('activate', self._launch_application_path, git_root)
        return [menu_item]

    def _get_file_path(self, file_info) -> str | None:
        """
        Gets the local file path from a Nautilus.FileInfo object.
        """
        uri = file_info.get_uri()
        if not uri or not uri.startswith('file://'):
            return None
        return unquote(uri[7:])

    def _find_git_root(self, folder_path: str) -> str | None:
        """
        Finds the root of a Git repository by searching up the directory tree.
        Returns the path to the Git root directory, or None if not in a repo.
        """
        current = Path(folder_path).resolve()
        
        # Search up to root
        while current != current.parent:
            if (current / '.git').exists():
                return str(current)
            current = current.parent
        
        # Check root as well
        if (current / '.git').exists():
            return str(current)
        
        return None

    def _launch_application_path(self, menu_item, file_path: str):
        """
        Launches the GitRepo application with the given path directly.
        """
        if not file_path or not Path(file_path).exists():
            self._show_notification(
                _("Error"),
                _("Could not get the path for the selected folder.")
            )
            return

        try:
            cmd = [self.app_executable, file_path]
            print(f"GitRepo Extension: Launching command: {cmd}")

            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

        except FileNotFoundError:
            print(f"GitRepo Extension: Executable not found: {self.app_executable}")
            self._show_notification(
                _("Application Not Found"),
                _("Could not find GitRepo. Is it installed?")
            )
        except Exception as e:
            print(f"GitRepo Extension: Error launching: {e}")
            self._show_notification(
                _("Launch Error"),
                str(e)
            )

    def _launch_application(self, menu_item, files):
        """
        Launches the GitRepo application with the selected folder.
        """
        if not files:
            return
            
        file_path = self._get_file_path(files[0])
        if not file_path or not Path(file_path).exists():
            self._show_notification(
                _("Error"),
                _("Could not get the path for the selected folder.")
            )
            return

        try:
            cmd = [self.app_executable, file_path]
            print(f"GitRepo Extension: Launching command: {cmd}")

            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

        except FileNotFoundError:
            print(f"GitRepo Extension: Executable not found: {self.app_executable}")
            self._show_notification(
                _("Application Not Found"),
                _("Could not find GitRepo. Is it installed?")
            )
        except Exception as e:
            print(f"GitRepo Extension: Error launching: {e}")
            self._show_notification(
                _("Launch Error"),
                str(e)
            )

    def _show_notification(self, title: str, message: str):
        """
        Displays a desktop notification using 'notify-send'.
        """
        try:
            subprocess.run([
                'notify-send',
                '--icon=dialog-error',
                f'--app-name={APP_NAME}',
                title,
                message
            ], check=False)
        except FileNotFoundError:
            print(f"ERROR: [{title}] {message}")
