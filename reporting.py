"""
reporting.py — Console output and state.json writing for the dashboard.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import config


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def print_banner() -> None:
    print()
    print("=" * 68)
    print("  ⚠️   PAPER TRADING MODE — NO REAL ORDERS WILL BE PLACED   ⚠️")
    print("=" * 68)
    print(f"  Kalshi × Polymarket Arbitrage Scanner")
    print(f"  Threshold: {config.MIN_NET_EDGE*100:.1f}% net edge after fees")
    print(f"  Price checks: every {config.PRICE_CHECK_INTERVAL}s")
    print(f"  Market re-match: every {config.MARKET_REFRESH_MINUTES} min")
    print(f"  Dashboard: http://localhost:{config.DASHBOARD_PORT}")
    print(f"  ▶  Ctrl+C to stop")
    print("=" * 68)
    print()


def print_opportunity(opp, is_new: bool = True) -> None:
    tag = "🆕 NEW " if is_new else "  🔁 "
    strat = "BUY YES Kalshi + NO Poly" if opp.strategy == "buy_yes_kalshi" else "BUY YES Poly + NO Kalshi"
    print(f"\n  {tag}  {opp.event_title[:60]}")
    print(f"  {'─'*64}")
    print(f"  Strategy : {strat}")
    print(f"  Kalshi   : ask={opp.k_yes_ask*100:.1f}¢  bid={opp.k_yes_bid*100:.1f}¢")
    print(f"  Poly     : ask={opp.p_yes_ask*100:.1f}¢  bid={opp.p_yes_bid*100:.1f}¢")
    print(f"  Net edge : {opp.min_edge*100:.2f}¢/contract  "
          f"(YES scenario: {opp.net_edge_yes*100:.2f}¢  NO scenario: {opp.net_edge_no*100:.2f}¢)")
    print(f"  Size     : {opp.max_contracts} contracts × ${opp.cost_per_contract:.3f} = "
          f"${opp.gross_profit_potential:.2f} potential profit")
    print(f"  Kalshi   : kalshi.com/markets/{opp.kalshi_ticker}")
    print(f"  Poly     : polymarket.com/event/{opp.poly_slug}")
    print(f"  Why      : {opp.rationale[:120]}")
    print()


def print_status(check_n: int, n_pairs: int, trader_snap: dict,
                 secs_to_refresh: int, n_opps: int) -> None:
    ts = _ts()
    pnl = trader_snap["daily_realized_pnl"]
    sign = "+" if pnl >= 0 else ""
    print(f"  [{ts}] Check #{check_n} | pairs={n_pairs} | "
          f"opps={n_opps} | daily P&L={sign}${pnl:.2f} | "
          f"re-match in {max(0,secs_to_refresh//60)}m{max(0,secs_to_refresh%60):02d}s")


def write_state(
    trader_snap: dict,
    opportunities: list,
    matched_count: int,
    check_count: int,
    last_refresh: float,
    history: list,
) -> None:
    """Write live state for the dashboard to read."""
    state = {
        "last_update": datetime.now().isoformat(),
        "check_count": check_count,
        "matched_pairs": matched_count,
        "trader": trader_snap,
        "opportunities": [
            {
                "title": o.event_title,
                "strategy": o.strategy,
                "k_yes_ask": o.k_yes_ask,
                "p_yes_bid": o.p_yes_bid,
                "min_edge": o.min_edge,
                "min_edge_pct": round(o.min_edge * 100, 2),
                "max_contracts": o.max_contracts,
                "gross_profit": o.gross_profit_potential,
                "kalshi_url": f"https://kalshi.com/markets/{o.kalshi_ticker}",
                "poly_url": f"https://polymarket.com/event/{o.poly_slug}",
                "rationale": o.rationale,
            }
            for o in opportunities
        ],
        "last_refresh_ago_s": round(time.time() - last_refresh),
        "history": history,
    }
    try:
        tmp = config.STATE_JSON.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.replace(config.STATE_JSON)
    except Exception:
        pass
