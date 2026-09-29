"""
exchanges/base.py — shared data models for all exchange adapters.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import time


@dataclass
class Quote:
    """Best executable bid/ask for a binary YES outcome."""
    exchange: str
    market_id: str           # ticker (Kalshi) or slug (Polymarket)
    title: str
    yes_ask: float           # price to BUY YES (what you pay)
    yes_bid: float           # price to SELL YES (what you receive)
    no_ask: float            # price to BUY NO = 1 - yes_bid  (approx)
    no_bid: float            # price to SELL NO = 1 - yes_ask  (approx)
    volume_24h: float = 0.0
    close_time: Optional[str] = None
    category: Optional[str] = None
    fetched_at: float = field(default_factory=time.time)

    @property
    def mid(self) -> float:
        return round((self.yes_ask + self.yes_bid) / 2, 4)

    @property
    def spread(self) -> float:
        return round(self.yes_ask - self.yes_bid, 4)

    @property
    def is_stale(self) -> bool:
        from config import STALE_QUOTE_SECONDS
        return (time.time() - self.fetched_at) > STALE_QUOTE_SECONDS


@dataclass
class MarketInfo:
    """Static metadata about a market — used for matching."""
    exchange: str
    market_id: str
    title: str
    category: Optional[str] = None
    close_time: Optional[str] = None
    resolution_rules: Optional[str] = None
