"""
exchanges/kalshi.py — Kalshi Elections API adapter.

Auth: RSA-PKCS1v15 signed headers.
Prices: yes_ask_dollars / yes_bid_dollars (0.0–1.0 scale).
Fees: 7% of profit per winning contract.
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Optional

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding

from .base import Quote, MarketInfo

BASE_URL = "https://api.elections.kalshi.com"


class KalshiExchange:
    def __init__(self, key_id: str, private_key_path: str):
        self.key_id = key_id
        pem = Path(private_key_path).read_bytes()
        self._private_key = serialization.load_pem_private_key(pem, password=None)
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _headers(self, method: str, path: str) -> dict:
        ts = str(int(time.time() * 1000))
        msg = f"{ts}{method.upper()}{path}".encode()
        sig = base64.b64encode(
            self._private_key.sign(msg, asym_padding.PKCS1v15(), hashes.SHA256())
        ).decode()
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        r = self._session.get(
            BASE_URL + path,
            headers=self._headers("GET", path),
            params=params or {},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    # ── Market discovery ──────────────────────────────────────────────────────

    def fetch_markets(self) -> list[MarketInfo]:
        """Fetch all open binary markets."""
        all_raw: list[dict] = []
        cursor: Optional[str] = None
        path = "/trade-api/v2/markets"
        page = 0

        while True:
            params: dict = {"limit": 200, "status": "open"}
            if cursor:
                params["cursor"] = cursor
            try:
                data = self._get(path, params)
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 429:
                    time.sleep(5)
                    continue
                print(f"  [Kalshi] HTTP error fetching markets: {e}")
                break
            except Exception as e:
                print(f"  [Kalshi] Error fetching markets: {e}")
                break

            batch = data.get("markets", [])
            if not batch:
                break
            all_raw.extend(batch)
            page += 1
            cursor = data.get("cursor")
            if not cursor or page >= 50:
                break

        markets = []
        for m in all_raw:
            title = m.get("title") or ""
            ticker = m.get("ticker", "")
            if not ticker or not title:
                continue
            markets.append(
                MarketInfo(
                    exchange="kalshi",
                    market_id=ticker,
                    title=title,
                    category=m.get("category"),
                    close_time=m.get("close_time") or m.get("expiration_time"),
                    resolution_rules=m.get("rules_primary") or m.get("subtitle"),
                )
            )
        return markets

    # ── Live quotes ───────────────────────────────────────────────────────────

    def fetch_quote(self, ticker: str) -> Optional[Quote]:
        """Fetch best bid/ask for a single market."""
        path = f"/trade-api/v2/markets/{ticker}"
        try:
            data = self._get(path)
        except Exception:
            return None

        m = data.get("market", {})

        yes_ask = self._price(m, "yes_ask_dollars")
        yes_bid = self._price(m, "yes_bid_dollars")

        if yes_ask is None and yes_bid is None:
            # Fall back to last price only if both bid/ask missing
            lp = self._price(m, "last_price_dollars")
            if lp is None:
                return None
            yes_ask = yes_bid = lp

        if yes_ask is None:
            yes_ask = yes_bid
        if yes_bid is None:
            yes_bid = yes_ask

        # Sanity: bid <= ask
        if yes_bid > yes_ask:
            yes_bid, yes_ask = yes_ask, yes_bid

        return Quote(
            exchange="kalshi",
            market_id=ticker,
            title=m.get("title", ticker),
            yes_ask=yes_ask,
            yes_bid=yes_bid,
            no_ask=round(1 - yes_bid, 4),
            no_bid=round(1 - yes_ask, 4),
            volume_24h=float(m.get("volume", 0) or 0),
            close_time=m.get("close_time") or m.get("expiration_time"),
            category=m.get("category"),
        )

    @staticmethod
    def _price(m: dict, field: str) -> Optional[float]:
        v = m.get(field)
        if v is None:
            return None
        try:
            p = round(float(v), 4)
            return p if 0.005 < p < 0.995 else None
        except (TypeError, ValueError):
            return None

    # ── Order book depth (for size estimation) ────────────────────────────────

    def fetch_orderbook(self, ticker: str) -> dict:
        """Returns {yes_bids: [(price, size)...], yes_asks: [(price, size)...]}"""
        path = f"/trade-api/v2/markets/{ticker}/orderbook"
        try:
            data = self._get(path)
            ob = data.get("orderbook", {})
            return {
                "yes_bids": [(float(l["price"]), int(l["quantity"])) for l in ob.get("yes", []) if l.get("side") == "bid"],
                "yes_asks": [(float(l["price"]), int(l["quantity"])) for l in ob.get("yes", []) if l.get("side") == "ask"],
            }
        except Exception:
            return {"yes_bids": [], "yes_asks": []}
