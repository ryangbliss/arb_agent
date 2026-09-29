"""
paper_trader.py — Simulated trade execution and P&L tracking.

Paper trades are NEVER sent to any exchange.
All fills are simulated against visible bid/ask prices.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Optional

from arbitrage import ArbOpportunity
import config

log = logging.getLogger(__name__)

Venue = Literal["kalshi", "polymarket"]


@dataclass
class SimFill:
    fill_id: str
    opp_id: str
    venue: Venue
    side: Literal["YES", "NO"]
    action: Literal["BUY"]
    contracts: int
    price: float           # fill price per contract
    fee: float             # total fee for this leg
    timestamp: float = field(default_factory=time.time)

    @property
    def cost(self) -> float:
        return round(self.contracts * self.price, 4)

    @property
    def dt(self) -> str:
        return datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S")


@dataclass
class Position:
    kalshi_ticker: str
    poly_slug: str
    event_title: str
    opp_id: str

    # Legs
    k_venue: Venue
    k_side: Literal["YES", "NO"]
    k_contracts: int
    k_avg_price: float

    p_venue: Venue
    p_side: Literal["YES", "NO"]
    p_contracts: int
    p_avg_price: float

    entry_time: float = field(default_factory=time.time)
    closed: bool = False
    resolved_outcome: Optional[Literal["YES", "NO"]] = None
    realized_pnl: float = 0.0

    def mark_to_market(self, k_mid: float, p_mid: float) -> float:
        """Unrealised P&L at current midpoints."""
        if self.closed:
            return self.realized_pnl
        # Cost basis
        cost = (self.k_contracts * self.k_avg_price +
                self.p_contracts * self.p_avg_price)
        # Mark value
        k_mark = self.k_contracts * (k_mid if self.k_side == "YES" else 1 - k_mid)
        p_mark = self.p_contracts * (p_mid if self.p_side == "YES" else 1 - p_mid)
        return round(k_mark + p_mark - cost, 4)


class PaperTrader:
    def __init__(self) -> None:
        self.cash: dict[Venue, float] = {
            "kalshi": config.PAPER_CASH_KALSHI,
            "polymarket": config.PAPER_CASH_POLY,
        }
        self.positions: dict[str, Position] = {}   # opp_id → Position
        self.fills: list[SimFill] = []
        self.daily_realized_pnl: float = 0.0
        self.total_fees_paid: float = 0.0
        self._today = date.today()

    # ── Reset daily counters ──────────────────────────────────────────────────

    def check_new_day(self) -> None:
        today = date.today()
        if today != self._today:
            self.daily_realized_pnl = 0.0
            self._today = today

    # ── Execute a simulated arb trade ─────────────────────────────────────────

    def execute(self, opp: ArbOpportunity, storage=None) -> Optional[str]:
        """
        Simulate both legs of the arb trade.
        Returns opp_id if filled, None if skipped.
        """
        self.check_new_day()

        n = opp.max_contracts
        if n < 1:
            return None

        # Determine legs
        if opp.strategy == "buy_yes_kalshi":
            k_side: Literal["YES", "NO"] = "YES"
            k_price = opp.k_yes_ask
            p_side: Literal["YES", "NO"] = "NO"
            p_price = opp.p_quote_age_s  # placeholder — use actual price
            p_price = round(1 - opp.p_yes_bid, 4)  # NO ask ≈ 1 - YES bid
        else:
            k_side = "NO"
            k_price = round(1 - opp.k_yes_bid, 4)
            p_side = "YES"
            p_price = opp.p_yes_ask

        k_cost = round(n * k_price, 4)
        p_cost = round(n * p_price, 4)

        # Cash checks
        if k_cost > self.cash["kalshi"]:
            log.info(f"[Paper] Insufficient Kalshi cash for {opp.event_title[:40]}")
            return None
        if p_cost > self.cash["polymarket"]:
            log.info(f"[Paper] Insufficient Poly cash for {opp.event_title[:40]}")
            return None

        opp_id = str(uuid.uuid4())[:8]

        # Compute fees per leg
        k_fee = round(n * config.KALSHI_FEE_RATE * (1 - k_price) if k_side == "YES"
                      else n * config.KALSHI_FEE_RATE * k_price, 4)
        p_fee = round(n * config.POLY_FEE_RATE * (1 - p_price) if p_side == "YES"
                      else n * config.POLY_FEE_RATE * p_price, 4)

        # Deduct cash
        self.cash["kalshi"] -= k_cost
        self.cash["polymarket"] -= p_cost
        self.total_fees_paid += k_fee + p_fee

        # Record fills
        kf = SimFill(fill_id=f"{opp_id}-K", opp_id=opp_id,
                     venue="kalshi", side=k_side, action="BUY",
                     contracts=n, price=k_price, fee=k_fee)
        pf = SimFill(fill_id=f"{opp_id}-P", opp_id=opp_id,
                     venue="polymarket", side=p_side, action="BUY",
                     contracts=n, price=p_price, fee=p_fee)
        self.fills.extend([kf, pf])

        pos = Position(
            kalshi_ticker=opp.kalshi_ticker,
            poly_slug=opp.poly_slug,
            event_title=opp.event_title,
            opp_id=opp_id,
            k_venue="kalshi", k_side=k_side,
            k_contracts=n, k_avg_price=k_price,
            p_venue="polymarket", p_side=p_side,
            p_contracts=n, p_avg_price=p_price,
        )
        self.positions[opp_id] = pos

        log.info(
            f"[Paper] ✅ Trade {opp_id}: {opp.event_title[:40]}\n"
            f"         Kalshi {k_side} {n}@{k_price*100:.1f}¢  "
            f"Poly {p_side} {n}@{p_price*100:.1f}¢  "
            f"edge={opp.min_edge*100:.2f}¢/contract"
        )

        if storage:
            storage.save_fill(kf)
            storage.save_fill(pf)
            storage.save_opportunity(opp, opp_id, simulated=True)

        return opp_id

    # ── Resolve a position (market settled) ───────────────────────────────────

    def resolve(self, opp_id: str, outcome: Literal["YES", "NO"], storage=None) -> float:
        pos = self.positions.get(opp_id)
        if pos is None or pos.closed:
            return 0.0

        KFEE = config.KALSHI_FEE_RATE
        PFEE = config.POLY_FEE_RATE

        # Kalshi payout
        if pos.k_side == outcome:
            k_payout = pos.k_contracts * (1 - KFEE * (1 - pos.k_avg_price))
        else:
            k_payout = 0.0

        # Poly payout
        if pos.p_side == outcome:
            p_payout = pos.p_contracts * (1 - PFEE * (1 - pos.p_avg_price))
        else:
            p_payout = 0.0

        cost_basis = (pos.k_contracts * pos.k_avg_price +
                      pos.p_contracts * pos.p_avg_price)
        realized = round(k_payout + p_payout - cost_basis, 4)

        self.cash["kalshi"] += k_payout
        self.cash["polymarket"] += p_payout
        pos.resolved_outcome = outcome
        pos.realized_pnl = realized
        pos.closed = True
        self.daily_realized_pnl += realized

        log.info(f"[Paper] Resolved {opp_id} → {outcome}: P&L = ${realized:+.4f}")
        if storage:
            storage.update_position_resolved(opp_id, outcome, realized)
        return realized

    # ── Snapshot for reporting ────────────────────────────────────────────────

    def snapshot(self, live_quotes: dict[str, tuple[float, float]] = None) -> dict:
        """
        live_quotes: {opp_id: (k_mid, p_mid)} for MTM calculation.
        """
        open_positions = [p for p in self.positions.values() if not p.closed]
        closed_positions = [p for p in self.positions.values() if p.closed]

        mtm_total = 0.0
        if live_quotes:
            for p in open_positions:
                km, pm = live_quotes.get(p.opp_id, (0.5, 0.5))
                mtm_total += p.mark_to_market(km, pm)

        return {
            "cash_kalshi": round(self.cash["kalshi"], 2),
            "cash_poly": round(self.cash["polymarket"], 2),
            "total_cash": round(sum(self.cash.values()), 2),
            "open_positions": len(open_positions),
            "closed_positions": len(closed_positions),
            "daily_realized_pnl": round(self.daily_realized_pnl, 4),
            "unrealized_pnl": round(mtm_total, 4),
            "total_fees_paid": round(self.total_fees_paid, 4),
            "positions": [
                {
                    "opp_id": p.opp_id,
                    "event": p.event_title,
                    "k_side": p.k_side,
                    "k_contracts": p.k_contracts,
                    "k_price": p.k_avg_price,
                    "p_side": p.p_side,
                    "p_contracts": p.p_contracts,
                    "p_price": p.p_avg_price,
                    "status": "closed" if p.closed else "open",
                    "realized_pnl": p.realized_pnl,
                }
                for p in list(open_positions) + list(closed_positions)
            ],
        }
