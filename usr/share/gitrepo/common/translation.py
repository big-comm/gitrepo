"""Shared gettext domain used by both GitRepo applications."""

import gettext
from pathlib import Path


DOMAIN = "gitrepo"
LOCALE_DIR = Path(__file__).resolve().parents[2] / "locale"

gettext.bindtextdomain(DOMAIN, LOCALE_DIR)
gettext.textdomain(DOMAIN)

_ = gettext.gettext
