import os
from pathlib import Path

# Stable, cwd-independent data location so the app behaves the same
# regardless of the directory it's launched from. Override with
# SWINGTRADE_DATA_DIR (e.g. for dev/test to keep using a local dir without
# touching ~/.swingtrade).
DATA_DIR = Path(os.environ.get("SWINGTRADE_DATA_DIR") or Path.home() / ".swingtrade")
DB_PATH = DATA_DIR / "app.db"

# Haiku model configuration
DEFAULT_HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Sonnet model configuration
DEFAULT_SONNET_MODEL = "claude-sonnet-5"


def haiku_session_mode() -> str:
    """'fake' or 'real'. SWINGTRADE_HAIKU_SESSION env var overrides; unset
    defaults to 'fake' for safety. Explicitly set to 'real' to use real Haiku API."""
    return os.environ.get("SWINGTRADE_HAIKU_SESSION", "fake").strip().lower()


def compilation_session_mode() -> str:
    """'fake' or 'real'. SWINGTRADE_COMPILATION_SESSION env var overrides; unset
    defaults to 'fake' for safety. Explicitly set to 'real' to use real Sonnet API."""
    return os.environ.get("SWINGTRADE_COMPILATION_SESSION", "fake").strip().lower()


def resolve_haiku_model() -> str:
    """SWINGTRADE_HAIKU_MODEL overrides (any CLI alias or full model id);
    unset falls back to DEFAULT_HAIKU_MODEL."""
    return os.environ.get("SWINGTRADE_HAIKU_MODEL") or DEFAULT_HAIKU_MODEL


def resolve_sonnet_model() -> str:
    """SWINGTRADE_SONNET_MODEL overrides (any CLI alias or full model id);
    unset falls back to DEFAULT_SONNET_MODEL."""
    return os.environ.get("SWINGTRADE_SONNET_MODEL") or DEFAULT_SONNET_MODEL
