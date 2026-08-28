#!/usr/bin/env python3
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
from app.api import create_app
app = create_app(pathlib.Path(__file__).resolve().parents[1] / "data")
print("Trace cockpit -> http://localhost:8000")
app.run(port=8000)
