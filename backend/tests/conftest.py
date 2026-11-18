import os
import sys
import tempfile
from pathlib import Path

# Isolate all test data from the real user data directory.
_TMP = Path(tempfile.mkdtemp(prefix="clipforge-test-"))
# Re-use already-downloaded models (read-only) so integration tests can run offline.
_real_models = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ClipForgeAI" / "models"
if _real_models.exists() and "CLIPFORGE_MODELS_DIR" not in os.environ:
    os.environ["CLIPFORGE_MODELS_DIR"] = str(_real_models)
os.environ["CLIPFORGE_HOME"] = str(_TMP / "home")
os.environ.setdefault("DISABLE_SQLALCHEMY_CEXT_RUNTIME", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from app import config  # noqa: E402

config.save_settings({"projects_dir": str(_TMP / "projects"), "exports_dir": str(_TMP / "exports")})

REPO = ROOT.parent
TEST_MEDIA = REPO / "test_media"


def make_words(text: str, start: float = 0.0, wps: float = 3.0, gap_after: dict[int, float] | None = None):
    """Create synthetic timed words for unit tests."""
    words = []
    t = start
    gap_after = gap_after or {}
    for i, w in enumerate(text.split()):
        d = 1.0 / wps
        words.append({"w": w, "s": round(t, 3), "e": round(t + d * 0.85, 3), "p": 0.95})
        t += d + gap_after.get(i, 0.0)
    return words


@pytest.fixture
def words_factory():
    return make_words
