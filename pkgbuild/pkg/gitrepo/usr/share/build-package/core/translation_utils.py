#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# core/translation_utils.py - Utilities for translation support
#
import gettext

# Configure the translation repo/name
gettext.textdomain("gitrepo")

# Export _ directly as the translation function
_ = gettext.gettext