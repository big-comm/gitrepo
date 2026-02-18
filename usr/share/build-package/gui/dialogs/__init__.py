#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/dialogs/__init__.py - GUI dialogs package initialization
#

"""
Dialogs package for the GUI interface.
Contains modal dialogs and confirmation windows.
"""

from .conflict_dialog import ConflictDialog, ConflictFileRow
from .preview_dialog import PreviewDialog, SimplePreviewDialog
from .progress_dialog import OperationRunner, ProgressDialog, SimpleProgressDialog
from .welcome_dialog import WelcomeDialog, should_show_welcome

__all__ = [
    "ProgressDialog",
    "SimpleProgressDialog",
    "OperationRunner",
    "ConflictDialog",
    "ConflictFileRow",
    "PreviewDialog",
    "SimplePreviewDialog",
    "WelcomeDialog",
    "should_show_welcome",
]