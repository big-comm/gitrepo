import sys
from pathlib import Path


PROJECT_MODULES = Path(__file__).resolve().parents[1] / "usr/share/build-package"
sys.path.insert(0, str(PROJECT_MODULES))
