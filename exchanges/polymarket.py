"""
exchanges/polymarket.py — Polymarket Gamma API adapter.

Public endpoints — no auth needed.
Prices: outcomePrices JSON array, 0.0–1.0 scale.
Fees: 2% of profit per winning contract.
"""
from __future__ import annotations

import json
import time
from typing import Optional

import requests

from .base import Quote, MarketInfo

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE  = "https://clob.polymarket.com"


class PolymarketExchange:
    def __init__(self) -> None:
        self._session = requests.Session()

    def _get(self, base: str, path: str, params: Optional[dict] = None) -> object:
        r = self._session.get(base + path, params=params or {}, timeout=15)
        r.raise_for_status()
        return r.json()

    # ── Market discovery ──────────────────────────────────────────────────────

    def fetch_markets(self) -> list[MarketInfo]:
        """Fetch all active binary Yes/No markets."""
        all_raw: list[dict] = []
        offset = 0
        page = 0

        while True:
            try:
                batch = self._get(
                    GAMMA_BASE,
                    "/markets",
                    {"limit": 200, "active": "true", "closed": "false", "limit": 500, "offset": offset},
                )
            except Exception as e:
                print(f"  [Poly] Error fetching markets: {e}")
                break
            if not batch:
                break
            all_raw.extend(batch)
            page += 1
            offset += 200
            if len(batch) < 100 or page >= 30:
                break

        markets = []
        for m in all_raw:
            question = m.get("question", "")
            slug = m.get("slug", "")
            if not question or not slug:
                continue

            try:
                outcomes = m.get("outcomes", '["Yes","No"]')
                if isinstance(outcomes, str):
                    outcomes = json.loads(outcomes)
                # Only binary Yes/No
                if len(outcomes) != 2 or "Yes" not in outcomes:
                    continue
            except Exception:
                continue

            markets.append(
                MarketInfo(
                    exchange="polymarket",
                    market_id=slug,
                    title=question,
                    category=m.get("category") or m.get("tags", [None])[0] if m.get("tags") else None,
                    close_time=m.get("endDate") or m.get("end_date_iso"),
                    resolution_rules=m.get("description"),
                )
            )
        return markets

    # ── Live quotes ───────────────────────────────────────────────────────────

    def fetch_quote(self, slug: str) -> Optional[Quote]:
        """Fetch best bid/ask for a single market via Gamma API."""
        try:
            data = self._get(GAMMA_BASE, "/markets", {"slug": slug})
        except Exception:
            return None

        if not data:
            return None

        m = data[0] if isinstance(data, list) else data

        try:
            prices_raw = m.get("outcomePrices", "[]")
            prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
            outcomes = m.get("outcomes", '["Yes","No"]')
            if isinstance(outcomes, str):
                outcomes = json.loads(outcomes)
            if len(outcomes) != 2 or "Yes" not in outcomes:
                return None
            yes_idx = outcomes.index("Yes")
            mid = round(float(prices[yes_idx]), 4)
        except Exception:
            return None

        if not (0.005 < mid < 0.995):
            return None

        # Polymarket's Gamma API only provides midpoint ("outcomePrices")
        # Use a synthetic half-spread of 0.5¢ as a conservative estimate
        # for paper-trading cost modelling
        half_spread = 0.005
        yes_ask = min(round(mid + half_spread, 4), 0.99)
        yes_bid = max(round(mid - half_spread, 4), 0.01)

        return Quote(
            exchange="polymarket",
            market_id=slug,
            title=m.get("question", slug),
            yes_ask=yes_ask,
            yes_bid=yes_bid,
            no_ask=round(1 - yes_bid, 4),
            no_bid=round(1 - yes_ask, 4),
            volume_24h=float(m.get("volume24hr") or m.get("volumeNum") or 0),
            close_time=m.get("endDate") or m.get("end_date_iso"),
            category=m.get("category"),
        )
