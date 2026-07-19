import sys
from pathlib import Path


SHARE_ROOT = Path(__file__).resolve().parents[2] / "usr" / "share"
sys.path.insert(0, str(SHARE_ROOT))
