"""
arbitrage.py — Arbitrage detection and edge calculation.

Detects:
  1. YES/YES direct: Kalshi YES cheaper than Poly YES → buy YES on Kalshi, NO on Poly
  2. NO/NO direct: Kalshi NO cheaper than Poly NO → buy NO on Kalshi, YES on Poly
  3. Stale quote rejection

Fee model:
  Kalshi: 7% of profit per winning contract
  Polymarket: 2% of profit per winning contract

For a pair (k_yes_ask, p_yes_bid) where Kalshi is cheaper:
  Strategy: buy YES on Kalshi, buy NO on Polymarket

  Cost = k_yes_ask + (1 - p_yes_bid)

  Scenario YES wins:
    Kalshi payout = 1 - KALSHI_FEE * (1 - k_yes_ask)
    Poly payout   = 0
    Net = Kalshi_payout - cost

  Scenario NO wins:
    Kalshi payout = 0
    Poly payout   = 1 - POLY_FEE * p_yes_bid   [NO contract wins]
    Net = Poly_payout - cost

  gross_edge = min(net_YES, net_NO)
  net_edge   = gross_edge  (fees already included)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Optional

from exchanges.base import Quote
import config

log = logging.getLogger(__name__)


@dataclass
class ArbOpportunity:
    kalshi_ticker: str
    poly_slug: str
    event_title: str

    # Strategy
    strategy: Literal["buy_yes_kalshi", "buy_yes_poly"]
    # "buy_yes_kalshi" → buy YES on Kalshi, buy NO on Poly
    # "buy_yes_poly"   → buy YES on Poly, buy NO on Kalshi

    # Prices used
    k_yes_ask: float
    k_yes_bid: float
    p_yes_ask: float
    p_yes_bid: float

    # Edge analysis
    cost_per_contract: float   # total $ spent per 1-contract pair
    net_edge_yes: float        # guaranteed profit if YES resolves
    net_edge_no: float         # guaranteed profit if NO resolves
    min_edge: float            # worst-case guaranteed profit (= min of the two)

    # Risk
    max_contracts: int         # limited by configurable position size
    gross_profit_potential: float   # min_edge * max_contracts

    # Staleness
    k_quote_age_s: float
    p_quote_age_s: float

    # Explanation
    rationale: str


def analyse(
    k_quote: Quote,
    p_quote: Quote,
    event_title: str,
    max_position_dollars: float = None,
) -> Optional[ArbOpportunity]:
    """
    Check a matched pair for arbitrage. Returns None if no opportunity.
    """
    if max_position_dollars is None:
        max_position_dollars = config.MAX_POSITION_PER_MARKET

    if k_quote.is_stale or p_quote.is_stale:
        log.debug(f"[Arb] Stale quote rejected: {k_quote.market_id}")
        return None

    KFEE = config.KALSHI_FEE_RATE
    PFEE = config.POLY_FEE_RATE

    def _edge(k_buy: float, p_sell_yes: float, k_fee: float, p_fee: float):
        """
        Buy YES on Kalshi at k_buy, sell YES on Poly (= buy NO) at price p_sell_yes.
        p_sell_yes is the Poly YES bid (what the market pays if we sell YES = NO position).
        """
        cost = k_buy + (1 - p_sell_yes)
        # YES wins:
        net_yes = (1 - k_fee * (1 - k_buy)) - cost
        # NO wins:
        net_no = (1 - p_fee * p_sell_yes) - cost
        return cost, net_yes, net_no

    def _edge_poly(p_buy: float, k_sell_yes: float, k_fee: float, p_fee: float):
        """Buy YES on Poly, sell YES on Kalshi (= buy NO on Kalshi)."""
        cost = p_buy + (1 - k_sell_yes)
        net_yes = (1 - p_fee * (1 - p_buy)) - cost
        net_no = (1 - k_fee * k_sell_yes) - cost
        return cost, net_yes, net_no

    best: Optional[ArbOpportunity] = None

    # Strategy A: buy YES on Kalshi, buy NO on Poly
    k_buy = k_quote.yes_ask          # what we pay to buy YES on Kalshi
    p_sell = k_quote.yes_bid         # actually, we want Poly YES bid
    p_sell = p_quote.yes_bid         # Poly YES bid (price we get if selling YES = buying NO)
    cost_a, ney_a, nen_a = _edge(k_buy, p_sell, KFEE, PFEE)
    min_edge_a = min(ney_a, nen_a)

    # Strategy B: buy YES on Poly, buy NO on Kalshi
    p_buy = p_quote.yes_ask
    k_sell = k_quote.yes_bid
    cost_b, ney_b, nen_b = _edge_poly(p_buy, k_sell, KFEE, PFEE)
    min_edge_b = min(ney_b, nen_b)

    best_edge = max(min_edge_a, min_edge_b)
    if best_edge < config.MIN_NET_EDGE:
        return None

    if min_edge_a >= min_edge_b:
        strategy = "buy_yes_kalshi"
        cost = cost_a
        net_yes, net_no, min_edge = ney_a, nen_a, min_edge_a
    else:
        strategy = "buy_yes_poly"
        cost = cost_b
        net_yes, net_no, min_edge = ney_b, nen_b, min_edge_b

    if cost <= 0 or cost >= 1.0:
        return None

    max_contracts = max(1, int(max_position_dollars / cost))
    gross = round(min_edge * max_contracts, 2)

    if strategy == "buy_yes_kalshi":
        rationale = (
            f"Buy YES on Kalshi @ {k_buy*100:.1f}¢, "
            f"buy NO on Polymarket @ {(1-p_sell)*100:.1f}¢ "
            f"(total cost {cost*100:.1f}¢/contract). "
            f"Guaranteed profit: {min_edge*100:.2f}¢/contract after fees "
            f"({'YES' if ney_a < nen_a else 'NO'} scenario is worst case). "
            f"Kalshi fee={KFEE*100:.0f}% of profit, Poly fee={PFEE*100:.0f}% of profit."
        )
    else:
        rationale = (
            f"Buy YES on Polymarket @ {p_buy*100:.1f}¢, "
            f"buy NO on Kalshi @ {(1-k_sell)*100:.1f}¢ "
            f"(total cost {cost*100:.1f}¢/contract). "
            f"Guaranteed profit: {min_edge*100:.2f}¢/contract after fees."
        )

    import time
    return ArbOpportunity(
        kalshi_ticker=k_quote.market_id,
        poly_slug=p_quote.market_id,
        event_title=event_title,
        strategy=strategy,
        k_yes_ask=k_quote.yes_ask,
        k_yes_bid=k_quote.yes_bid,
        p_yes_ask=p_quote.yes_ask,
        p_yes_bid=p_quote.yes_bid,
        cost_per_contract=round(cost, 4),
        net_edge_yes=round(net_yes, 4),
        net_edge_no=round(net_no, 4),
        min_edge=round(min_edge, 4),
        max_contracts=max_contracts,
        gross_profit_potential=gross,
        k_quote_age_s=round(time.time() - k_quote.fetched_at, 1),
        p_quote_age_s=round(time.time() - p_quote.fetched_at, 1),
        rationale=rationale,
    )
