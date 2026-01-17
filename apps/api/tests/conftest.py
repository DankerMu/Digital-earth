import sys
from pathlib import Path

API_SRC = Path(__file__).resolve().parents[1] / "src"
CONFIG_SRC = Path(__file__).resolve().parents[3] / "packages" / "config" / "src"
SHARED_SRC = Path(__file__).resolve().parents[3] / "packages" / "shared" / "src"
PIPELINE_SRC = (
    Path(__file__).resolve().parents[3] / "services" / "data-pipeline" / "src"
)

sys.path.insert(0, str(SHARED_SRC))
sys.path.insert(0, str(CONFIG_SRC))
sys.path.insert(0, str(PIPELINE_SRC))
sys.path.insert(0, str(API_SRC))
