import sys
from pathlib import Path

PIPELINE_SRC = Path(__file__).resolve().parents[1] / "src"
CONFIG_SRC = Path(__file__).resolve().parents[3] / "packages" / "config" / "src"
SHARED_SRC = Path(__file__).resolve().parents[3] / "packages" / "shared" / "src"

sys.path.insert(0, str(PIPELINE_SRC))
sys.path.insert(0, str(SHARED_SRC))
sys.path.insert(0, str(CONFIG_SRC))
