import importlib
import sys
from pathlib import Path

import pytest


SHARE_ROOT = Path(__file__).resolve().parents[2] / "usr" / "share"
sys.path.insert(0, str(SHARE_ROOT))


@pytest.fixture
def build_package_modules(monkeypatch):
    monkeypatch.syspath_prepend(str(SHARE_ROOT))
    settings = importlib.import_module("gitrepo.build_package.core.settings")
    token_store = importlib.import_module("gitrepo.build_package.core.token_store")
    return settings, token_store
