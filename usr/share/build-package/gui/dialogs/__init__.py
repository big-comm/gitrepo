#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/dialogs/__init__.py - GUI dialogs package initialization
#

"""
Dialogs package for the GUI interface.
Contains modal dialogs and confirmation windows.
"""

from .progress_dialog import ProgressDialog, SimpleProgressDialog, OperationRunner
from .settings_dialog import SettingsDialog
from .conflict_dialog import ConflictDialog, ConflictFileRow
from .preview_dialog import PreviewDialog, SimplePreviewDialog

__all__ = [
    'ProgressDialog',
    'SimpleProgressDialog',
    'OperationRunner',
    'SettingsDialog',
    'ConflictDialog',
    'ConflictFileRow',
    'PreviewDialog',
    'SimplePreviewDialog',
]