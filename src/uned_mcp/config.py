from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_URL = os.environ.get("UNED_BASE_URL", "https://agora.uned.es").rstrip("/")
DATA_DIR = Path(os.environ.get("UNED_MCP_HOME", Path.home() / ".uned-mcp"))
TOKEN_FILE = DATA_DIR / "token.json"
SESSION_FILE = DATA_DIR / "session.json"
TZ = ZoneInfo("Europe/Madrid")

STUDY_DIR = Path(os.environ.get("UNED_STUDY_DIR", Path.home() / "UNED")).expanduser()
INDEX_DB = STUDY_DIR / ".uned-index.sqlite"
STATE_FILE = STUDY_DIR / ".uned-estado.json"
MAX_FILE_MB = float(os.environ.get("UNED_MCP_MAX_FILE_MB", "80"))
DOWNLOAD_DELAY = float(os.environ.get("UNED_MCP_DOWNLOAD_DELAY", "0.4"))
SKIP_MIMETYPES_PREFIX = ("video/", "audio/")
