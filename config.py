"""Settings for both sides, from ``.env`` next to this file.

Only Google AI Studio keys are used: ADK's native Gemini client reads
``GOOGLE_API_KEY`` from the environment. ``use_key("server")`` puts the
server's key there (falling back to the shared one) so the two processes can
spend different per-minute quotas.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

SERVER_HOST = os.getenv("SERVER_HOST", "localhost")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8002"))
SERVER_URL = os.getenv("SERVER_URL", f"http://{SERVER_HOST}:{SERVER_PORT}").rstrip("/")

CLIENT_MODEL = os.getenv("CLIENT_MODEL", "gemini-3.5-flash-lite")
SERVER_MODEL = os.getenv("SERVER_MODEL", "gemini-3.5-flash-lite")


def use_key(side: str) -> None:
    """Point ADK's Gemini client at the key for this side: 'client' or 'server'."""
    key = os.getenv(f"{side.upper()}_GOOGLE_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
    if not key or key.startswith("paste-"):
        raise RuntimeError(f"No API key: set GOOGLE_API_KEY (or {side.upper()}_GOOGLE_API_KEY) in {ROOT / '.env'}")
    os.environ["GOOGLE_API_KEY"] = key
