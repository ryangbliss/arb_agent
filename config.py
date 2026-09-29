"""
config.py — loads all settings from environment variables / .env file.
Raises clearly if required secrets are missing.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Load .env if present (python-dotenv)
try:
    from dotenv import load_dotenv
    _env = Path(__file__).parent / ".env"
    if _env.exists():
        load_dotenv(_env)
    else:
        load_dotenv()  # search CWD and parents
except ImportError:
    pass  # dotenv optional; fall back to real env vars


def _require(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        print(f"\n❌  Missing required env var: {key}")
        print(f"    Copy .env.example → .env and fill in your values.\n")
        sys.exit(1)
    return val


def _opt(key: str, default: str) -> str:
    return os.environ.get(key, default).strip()


# ── Secrets ──────────────────────────────────────────────────────────────────

KALSHI_KEY_ID: str = _require("KALSHI_KEY_ID")
KALSHI_PRIVATE_KEY_PATH: str = _require("KALSHI_PRIVATE_KEY_PATH")
ANTHROPIC_API_KEY: str = _opt("ANTHROPIC_API_KEY", "")

# ── Paper-trading ─────────────────────────────────────────────────────────────

PAPER_CASH_KALSHI: float = float(_opt("PAPER_CASH_KALSHI", "10000"))
PAPER_CASH_POLY: float = float(_opt("PAPER_CASH_POLY", "10000"))
MAX_DAILY_LOSS: float = float(_opt("MAX_DAILY_LOSS", "500"))
MAX_POSITION_PER_MARKET: float = float(_opt("MAX_POSITION_PER_MARKET", "200"))
MIN_NET_EDGE: float = float(_opt("MIN_NET_EDGE", "0.02"))
MATCH_CONFIDENCE: float = float(_opt("MATCH_CONFIDENCE", "0.80"))

# ── Timing ────────────────────────────────────────────────────────────────────

PRICE_CHECK_INTERVAL: int = int(_opt("PRICE_CHECK_INTERVAL", "60"))
MARKET_REFRESH_MINUTES: int = int(_opt("MARKET_REFRESH_MINUTES", "30"))
STALE_QUOTE_SECONDS: int = int(_opt("STALE_QUOTE_SECONDS", "300"))

# ── Exchange fees ─────────────────────────────────────────────────────────────
# Kalshi: 7% of profit (i.e. 0.07 * (1 - price) per contract if YES wins)
# Polymarket: 2% of profit
KALSHI_FEE_RATE: float = 0.07
POLY_FEE_RATE: float = 0.02

# ── Dashboard ────────────────────────────────────────────────────────────────

DASHBOARD_PORT: int = int(_opt("DASHBOARD_PORT", "8765"))

# ── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR: Path = Path(__file__).parent
DATA_DIR: Path = BASE_DIR / "data"
REPORTS_DIR: Path = BASE_DIR / "reports"
DASHBOARD_DIR: Path = BASE_DIR / "dashboard"

DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

DB_PATH: Path = DATA_DIR / "arb.db"
STATE_JSON: Path = DATA_DIR / "state.json"   # live state for dashboard
