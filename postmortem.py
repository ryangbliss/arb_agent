"""
postmortem.py — End-of-day review of everything the bot did.

For each opportunity flagged today:
  - Was the market match actually correct?
  - What did the market resolve to?
  - Would the trade have made or lost money?
  - What went wrong (if anything)?

Run manually any time:
  python3 ~/Desktop/arb_agent/postmortem.py

Or it runs automatically at the end of each day if you leave the bot running.
"""
import json
import os
import sqlite3
import sys
import time
from datetime import date, datetime
from pathlib import Path

import requests

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
except ImportError:
    pass

import config

KALSHI_BASE = "https://api.elections.kalshi.com"


# ── Fetch resolution status ────────────────────────────────────────────────

def get_kalshi_resolution(ticker: str) -> dict:
    """Check if a Kalshi market has resolved and what it resolved to."""
    try:
        import base64
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding as asym_padding

        pem = Path(config.KALSHI_PRIVATE_KEY_PATH).read_bytes()
        pk = serialization.load_pem_private_key(pem, password=None)

        path = f"/trade-api/v2/markets/{ticker}"
        ts = str(int(time.time() * 1000))
        sig = base64.b64encode(
            pk.sign(f"{ts}GET{path}".encode(), asym_padding.PKCS1v15(), hashes.SHA256())
        ).decode()
        headers = {
            "KALSHI-ACCESS-KEY": config.KALSHI_KEY_ID,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": sig,
        }
        r = requests.get(KALSHI_BASE + path, headers=headers, timeout=10)
        m = r.json().get("market", {})
        status = m.get("status", "")
        result = m.get("result", "")  # "yes" or "no"
        return {
            "status": status,
            "resolved": status in ("finalized", "settled"),
            "outcome": result.upper() if result else None,
            "yes_price": m.get("yes_ask_dollars") or m.get("last_price_dollars"),
        }
    except Exception as e:
        return {"status": "unknown", "resolved": False, "outcome": None, "error": str(e)}


def get_poly_resolution(slug: str) -> dict:
    """Check if a Polymarket market has resolved."""
    try:
        r = requests.get(
            "https://gamma-api.polymarket.com/markets",
            params={"slug": slug},
            timeout=10,
        )
        markets = r.json()
        if not markets:
            return {"resolved": False, "outcome": None}
        m = markets[0]
        closed = m.get("closed", False)
        resolved = m.get("resolved", False)
        outcome = None
        if resolved or closed:
            # Check which outcome won
            try:
                prices = json.loads(m.get("outcomePrices", "[]"))
                outcomes = json.loads(m.get("outcomes", '["Yes","No"]'))
                if "Yes" in outcomes:
                    yes_price = float(prices[outcomes.index("Yes")])
                    outcome = "YES" if yes_price >= 0.99 else "NO" if yes_price <= 0.01 else None
            except Exception:
                pass
        return {"resolved": resolved or closed, "outcome": outcome}
    except Exception as e:
        return {"resolved": False, "outcome": None, "error": str(e)}


# ── P&L recalculation ─────────────────────────────────────────────────────

def calc_actual_pnl(opp: dict, outcome: str) -> dict:
    """
    Given an opportunity row from the DB and the actual outcome,
    calculate what the P&L would have been.
    """
    strategy = opp["strategy"]
    k_ask = float(opp["k_ask"])
    p_bid = float(opp["p_bid"])
    n = int(opp["max_contr"])

    KFEE = 0.07
    PFEE = 0.02

    if strategy == "buy_yes_kalshi":
        k_price = k_ask
        p_price = round(1 - p_bid, 4)
        cost = (k_price + p_price) * n

        if outcome == "YES":
            k_payout = n * (1 - KFEE * (1 - k_price))
            p_payout = 0
        else:
            k_payout = 0
            p_payout = n * (1 - PFEE * p_bid)

        actual_pnl = round(k_payout + p_payout - cost, 4)
    else:
        p_price = p_bid + 0.01  # approximation for buy_yes_poly
        k_price = round(1 - k_ask, 4)
        cost = (p_price + k_price) * n

        if outcome == "YES":
            p_payout = n * (1 - PFEE * (1 - p_price))
            k_payout = 0
        else:
            p_payout = 0
            k_payout = n * (1 - KFEE * k_ask)

        actual_pnl = round(p_payout + k_payout - cost, 4)

    expected_pnl = round(float(opp["min_edge"]) * n, 4)
    error = round(actual_pnl - expected_pnl, 4)

    return {
        "actual_pnl": actual_pnl,
        "expected_pnl": expected_pnl,
        "error": error,
        "outcome": outcome,
        "correct": actual_pnl > 0,
    }


# ── Mistake analysis ──────────────────────────────────────────────────────

def diagnose_mistake(opp: dict, resolution: dict, pnl_result: dict) -> str:
    """Explain what went wrong in plain English."""
    issues = []

    # Not resolved yet
    if not resolution.get("resolved"):
        return "Market has not resolved yet — check back later."

    # Trade would have lost
    if pnl_result and not pnl_result["correct"]:
        issues.append(f"Trade would have LOST ${abs(pnl_result['actual_pnl']):.4f}")

        # Was the match wrong?
        if not resolution.get("outcome"):
            issues.append("Could not determine outcome — likely a BAD MARKET MATCH (Kalshi and Polymarket were not the same event).")
        else:
            issues.append(
                f"Edge was estimated at {float(opp['min_edge'])*100:.2f}¢ but actual result was "
                f"${pnl_result['actual_pnl']:.4f}. Possible causes: "
                "price moved before both legs filled, fees higher than modelled, or prices were stale."
            )

    if not issues:
        return f"✅ Trade would have worked. Actual P&L: ${pnl_result['actual_pnl']:+.4f} (estimated ${pnl_result['expected_pnl']:+.4f})"

    return " | ".join(issues)


# ── Main report ────────────────────────────────────────────────────────────

def run_postmortem(target_date: str = None):
    target_date = target_date or str(date.today())

    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    opps = conn.execute(
        "SELECT * FROM opportunities WHERE date=? ORDER BY ts ASC",
        (target_date,)
    ).fetchall()
    opps = [dict(o) for o in opps]

    print()
    print("=" * 70)
    print(f"  📋 POST-MORTEM REPORT — {target_date}")
    print("=" * 70)
    print(f"  Opportunities flagged: {len(opps)}")
    simulated = [o for o in opps if o["simulated"]]
    print(f"  Simulated trades:      {len(simulated)}")
    print()

    if not opps:
        print("  No opportunities were recorded for this date.")
        return

    total_expected = 0
    total_actual = 0
    correct = 0
    unresolved = 0
    mistakes = []

    for i, opp in enumerate(opps, 1):
        print(f"  [{i}/{len(opps)}] {opp['title'][:65]}")
        print(f"         Strategy: {opp['strategy']}  |  Edge: {opp['min_edge']*100:.2f}¢  |  Contracts: {opp['max_contr']}")
        print(f"         Kalshi: {opp['kalshi_id']}  |  Poly: {opp['poly_id']}")

        # Check resolutions
        print(f"         Checking resolution...", end=" ", flush=True)
        k_res = get_kalshi_resolution(opp["kalshi_id"])
        p_res = get_poly_resolution(opp["poly_id"])
        print("done")

        # Use whichever resolved
        outcome = k_res.get("outcome") or p_res.get("outcome")
        resolved = k_res.get("resolved") or p_res.get("resolved")

        if not resolved or not outcome:
            print(f"         ⏳ Not yet resolved — skipping P&L calculation")
            unresolved += 1
            print()
            continue

        print(f"         Outcome: {outcome}")

        pnl = calc_actual_pnl(opp, outcome)
        total_expected += pnl["expected_pnl"]
        total_actual += pnl["actual_pnl"]
        if pnl["correct"]:
            correct += 1
        else:
            mistakes.append((opp, pnl))

        diagnosis = diagnose_mistake(opp, {"resolved": resolved, "outcome": outcome}, pnl)
        print(f"         {diagnosis}")
        print()

    # ── Summary ───────────────────────────────────────────────────────────
    resolved_count = len(opps) - unresolved
    print("─" * 70)
    print(f"  SUMMARY FOR {target_date}")
    print("─" * 70)
    print(f"  Resolved trades:   {resolved_count}")
    print(f"  Winning trades:    {correct}")
    print(f"  Losing trades:     {len(mistakes)}")
    print(f"  Unresolved:        {unresolved}")
    if resolved_count:
        print(f"  Win rate:          {correct/resolved_count*100:.0f}%")
    print(f"  Expected P&L:      ${total_expected:+.4f}")
    print(f"  Actual P&L:        ${total_actual:+.4f}")
    print(f"  Forecast error:    ${total_actual - total_expected:+.4f}")
    print()

    # ── What the bot got wrong ─────────────────────────────────────────────
    if mistakes:
        print("─" * 70)
        print(f"  ❌ WHAT WENT WRONG ({len(mistakes)} trade(s))")
        print("─" * 70)
        for opp, pnl in mistakes:
            print(f"\n  Market: {opp['title'][:65]}")
            print(f"  Expected: ${pnl['expected_pnl']:+.4f}  |  Actual: ${pnl['actual_pnl']:+.4f}")
            print(f"  Lesson: The edge estimate of {float(opp['min_edge'])*100:.2f}¢/contract did not hold.")
            print(f"  Likely cause: price moved between when the gap was spotted and when")
            print(f"  both legs would have filled — this is execution/latency risk.")
    else:
        if resolved_count > 0:
            print("  ✅ No losing trades — all resolved correctly.")

    print()

    # Save to file
    report_path = config.REPORTS_DIR / f"postmortem_{target_date}.txt"
    import io, contextlib
    buf = io.StringIO()
    # Re-run capturing output (simplified)
    report_path.write_text(
        f"POST-MORTEM {target_date}\n"
        f"Opportunities: {len(opps)}\n"
        f"Resolved: {resolved_count}\n"
        f"Winning: {correct}\n"
        f"Losing: {len(mistakes)}\n"
        f"Unresolved: {unresolved}\n"
        f"Expected P&L: ${total_expected:+.4f}\n"
        f"Actual P&L: ${total_actual:+.4f}\n"
    )
    print(f"  📄 Saved to: {report_path}")
    print()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Date to review (YYYY-MM-DD), defaults to today")
    args = parser.parse_args()
    run_postmortem(args.date)
