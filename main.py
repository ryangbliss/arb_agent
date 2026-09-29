"""
main.py — entry point for the Kalshi × Polymarket paper-trading arb agent.

Usage:
  python main.py              # continuous paper-trading mode
  python main.py --scan-once  # single scan, print results, exit
  python main.py --report     # print today's daily report and exit
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime

import os

import config  # noqa: E402 — must come after secret guard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

from exchanges import KalshiExchange, PolymarketExchange
from matching import match_markets
from arbitrage import analyse
from paper_trader import PaperTrader
from risk import RiskManager
from storage import Storage
from reporting import print_banner, print_opportunity, print_status, write_state
import dashboard_server


def run_continuous() -> None:
    print_banner()
    dashboard_server.start()

    kalshi = KalshiExchange(config.KALSHI_KEY_ID, config.KALSHI_PRIVATE_KEY_PATH)
    poly = PolymarketExchange()
    trader = PaperTrader()
    risk = RiskManager(trader)
    storage = Storage()

    matched_pairs: list = []
    k_info_map: dict = {}
    p_info_map: dict = {}
    last_refresh: float = 0
    check_count: int = 0
    daily_opp_count: int = 0

    while True:
        now = time.time()
        should_refresh = (last_refresh == 0 or
                          (now - last_refresh) / 60 >= config.MARKET_REFRESH_MINUTES)

        if should_refresh:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"\n{'─'*68}")
            print(f"  🔍 MARKET REFRESH — {ts}")
            print(f"{'─'*68}")
            try:
                k_markets = kalshi.fetch_markets()
                p_markets = poly.fetch_markets()
                matched, rejected = match_markets(
                    k_markets, p_markets,
                    anthropic_api_key=config.ANTHROPIC_API_KEY,
                    confidence_threshold=config.MATCH_CONFIDENCE,
                )
                matched_pairs = matched
                k_info_map = {m.market_id: m for m in k_markets}
                p_info_map = {m.market_id: m for m in p_markets}
                last_refresh = time.time()
                print(f"  ✅ Watching {len(matched_pairs)} matched pairs  "
                      f"({len(rejected)} near-misses rejected)")
                print()
            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"Market refresh error: {e}")
                last_refresh = time.time()

        # ── Price check cycle ──────────────────────────────────────────────
        check_count += 1
        current_opps = []

        for pair in matched_pairs:
            k_quote = kalshi.fetch_quote(pair.kalshi.market_id)
            p_quote = poly.fetch_quote(pair.poly.market_id)
            if k_quote is None or p_quote is None:
                continue

            opp = analyse(k_quote, p_quote, pair.kalshi.title)
            if opp is None:
                continue

            current_opps.append(opp)
            daily_opp_count += 1

            # Risk check
            rc = risk.check(opp, k_quote, p_quote)
            if not rc.approved:
                log.debug(f"[Risk] {opp.event_title[:40]} — {rc.reason}")
                continue

            # Paper trade
            opp_id = trader.execute(opp, storage=storage)
            if opp_id:
                print_opportunity(opp, is_new=True)
                storage.save_position(trader.positions[opp_id])

                # Mac notification
                try:
                    import subprocess
                    subprocess.run(
                        ["osascript", "-e",
                         f'display notification "Edge {opp.min_edge*100:.2f}¢ — {opp.event_title[:50]}" '
                         f'with title "🚨 Paper Arb Found" sound name "Ping"'],
                        timeout=2,
                    )
                except Exception:
                    pass

        # Ongoing opps (already have positions)
        for opp in current_opps:
            key = opp.kalshi_ticker
            already_traded = any(
                p.kalshi_ticker == key and not p.closed
                for p in trader.positions.values()
            )
            if not already_traded:
                pass  # new opps printed above

        secs_left = int(config.MARKET_REFRESH_MINUTES * 60 - (time.time() - last_refresh))
        snap = trader.snapshot()

        print_status(check_count, len(matched_pairs), snap, secs_left, len(current_opps))
        write_state(snap, current_opps, len(matched_pairs), check_count,
                    last_refresh, storage.history())

        # Save daily summary every cycle
        storage.save_daily_summary(
            opps=daily_opp_count,
            trades=len([f for f in trader.fills if f.opp_id]),
            pnl=snap["daily_realized_pnl"],
            fees=snap["total_fees_paid"],
            cash=snap["total_cash"],
        )

        try:
            time.sleep(config.PRICE_CHECK_INTERVAL)
        except KeyboardInterrupt:
            break

    # Shutdown
    print("\n\n  Shutting down…")
    csv_path = storage.export_today_csv()
    print(f"  📄 Report saved: {csv_path}")
    print(f"  💰 Final cash: Kalshi=${trader.cash['kalshi']:.2f}  Poly=${trader.cash['polymarket']:.2f}")
    print(f"  📈 Daily realized P&L: ${trader.daily_realized_pnl:+.4f}")
    print()


def run_scan_once() -> None:
    """Single scan — print opportunities and exit."""
    print_banner()
    kalshi = KalshiExchange(config.KALSHI_KEY_ID, config.KALSHI_PRIVATE_KEY_PATH)
    poly = PolymarketExchange()
    k_markets = kalshi.fetch_markets()
    p_markets = poly.fetch_markets()
    matched, rejected = match_markets(
        k_markets, p_markets,
        anthropic_api_key=config.ANTHROPIC_API_KEY,
        confidence_threshold=config.MATCH_CONFIDENCE,
    )
    print(f"  Matched {len(matched)} pairs, {len(rejected)} rejected")
    opps = []
    for pair in matched:
        kq = kalshi.fetch_quote(pair.kalshi.market_id)
        pq = poly.fetch_quote(pair.poly.market_id)
        if kq and pq:
            opp = analyse(kq, pq, pair.kalshi.title)
            if opp:
                opps.append(opp)
    print(f"\n  Found {len(opps)} opportunity/ies:\n")
    for o in sorted(opps, key=lambda x: x.min_edge, reverse=True):
        print_opportunity(o)


def run_report() -> None:
    """Print today's daily summary."""
    storage = Storage()
    opps = storage.today_opportunities()
    print(f"\n  Today's report ({datetime.now().date()})")
    print(f"  Opportunities found: {len(opps)}")
    sims = [o for o in opps if o["simulated"]]
    print(f"  Simulated trades:    {len(sims)}")
    if sims:
        total_edge = sum(o["min_edge"] for o in sims)
        print(f"  Total edge captured: ${total_edge:.4f}")
    history = storage.history(7)
    if history:
        print("\n  Last 7 days:")
        for h in history:
            sign = "+" if h["realized_pnl"] >= 0 else ""
            print(f"    {h['date']}  P&L: {sign}${h['realized_pnl']:.4f}  "
                  f"trades: {h['trades']}  fees: ${h['fees_paid']:.4f}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kalshi×Polymarket Paper Arb Agent")
    parser.add_argument("--scan-once", action="store_true", help="Single scan then exit")
    parser.add_argument("--report", action="store_true", help="Print daily report and exit")
    args = parser.parse_args()

    if args.scan_once:
        run_scan_once()
    elif args.report:
        run_report()
    else:
        run_continuous()
