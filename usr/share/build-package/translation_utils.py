#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# translation_utils.py - Utilities for translation support
#
import gettext

# Configure the translation repo/name
gettext.textdomain("gitrepo")

# Use a more unique and descriptive name
def translate_text(text):
    """Translates the text using gettext"""
    if not isinstance(text, str):
        return text
    return gettext.gettext(text)