"""
risk.py — Pre-trade risk checks.

All checks must pass before a paper trade is simulated.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from arbitrage import ArbOpportunity
from exchanges.base import Quote
import config

log = logging.getLogger(__name__)


@dataclass
class RiskResult:
    approved: bool
    reason: str


class RiskManager:
    def __init__(self, paper_trader) -> None:
        self._pt = paper_trader
        self._halted: bool = False
        self._halt_reason: str = ""

    @property
    def is_halted(self) -> bool:
        return self._halted

    def halt(self, reason: str) -> None:
        if not self._halted:
            self._halted = True
            self._halt_reason = reason
            log.warning(f"[Risk] 🛑 HALT: {reason}")

    def check(self, opp: ArbOpportunity, k_quote: Quote, p_quote: Quote) -> RiskResult:
        # ── Global halt ───────────────────────────────────────────────────────
        if self._halted:
            return RiskResult(False, f"globally_halted: {self._halt_reason}")

        # ── Daily loss limit ──────────────────────────────────────────────────
        daily_loss = self._pt.daily_realized_pnl
        if daily_loss < -config.MAX_DAILY_LOSS:
            self.halt(f"daily_loss_limit(${config.MAX_DAILY_LOSS})")
            return RiskResult(False, "daily_loss_limit")

        # ── Stale quotes ──────────────────────────────────────────────────────
        if k_quote.is_stale:
            return RiskResult(False, f"kalshi_quote_stale({opp.k_quote_age_s:.0f}s)")
        if p_quote.is_stale:
            return RiskResult(False, f"poly_quote_stale({opp.p_quote_age_s:.0f}s)")

        # ── Net edge threshold ────────────────────────────────────────────────
        if opp.min_edge < config.MIN_NET_EDGE:
            return RiskResult(False, f"edge_too_low({opp.min_edge*100:.2f}%<{config.MIN_NET_EDGE*100:.1f}%)")

        # ── Degenerate prices ─────────────────────────────────────────────────
        if not (0.01 <= k_quote.yes_ask <= 0.99):
            return RiskResult(False, "kalshi_price_out_of_range")
        if not (0.01 <= p_quote.yes_ask <= 0.99):
            return RiskResult(False, "poly_price_out_of_range")

        # ── Spread sanity ─────────────────────────────────────────────────────
        if k_quote.spread > 0.20:
            return RiskResult(False, f"kalshi_spread_too_wide({k_quote.spread*100:.1f}%)")
        if p_quote.spread > 0.20:
            return RiskResult(False, f"poly_spread_too_wide({p_quote.spread*100:.1f}%)")

        # ── Existing position check ───────────────────────────────────────────
        existing = [
            p for p in self._pt.positions.values()
            if not p.closed and p.kalshi_ticker == opp.kalshi_ticker
        ]
        if existing:
            return RiskResult(False, "position_already_open")

        # ── Capital check ─────────────────────────────────────────────────────
        k_cost = opp.max_contracts * opp.k_yes_ask
        p_cost = opp.max_contracts * (1 - opp.p_yes_bid)
        if k_cost > self._pt.cash["kalshi"] * 0.95:
            return RiskResult(False, "insufficient_kalshi_cash")
        if p_cost > self._pt.cash["polymarket"] * 0.95:
            return RiskResult(False, "insufficient_poly_cash")

        return RiskResult(True, "all_checks_passed")
