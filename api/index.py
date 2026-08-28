import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]
                       / "backend"))
from app.static_api import create_static_app  # noqa: E402

app = create_static_app()
