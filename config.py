"""Read local settings and derive the application name from its source."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
START = (13.73830, 100.52956)  # Phaya Thai Road by Chulalongkorn University
START_HEADING = 7.0
PORT = 8765
SOURCES = (
    "main.py", "controller.py", "navigation.py", "bridge.py", "config.py",
    "static/index.html", "static/app.js", "static/style.css", "static/hud.qss",
)


def application_name() -> str:
    lines = 0
    for source in SOURCES:
        contents = (ROOT / source).read_text(encoding="utf-8")
        lines += len(contents.splitlines())
    return f"Earthsplorer{lines}"


def load_settings() -> str:
    """Allow shell environment variables to override the local .env file."""
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            name, separator, value = line.partition("=")
            name = name.strip()
            if separator and name in {"GOOGLE_MAPS_API_KEY", "SDL_GAMECONTROLLERCONFIG"}:
                os.environ.setdefault(name, value.strip().strip("\"'"))

    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    return "" if key == "your_key_here" else key
