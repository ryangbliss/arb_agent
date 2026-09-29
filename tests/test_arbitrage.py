"""Tests for arbitrage math and fee calculations."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
import time
from unittest.mock import patch
from exchanges.base import Quote
from arbitrage import analyse


def _q(exchange, market_id, ask, bid):
    return Quote(
        exchange=exchange,
        market_id=market_id,
        title="Test market",
        yes_ask=ask,
        yes_bid=bid,
        no_ask=round(1 - bid, 4),
        no_bid=round(1 - ask, 4),
        fetched_at=time.time(),
    )


# ── Basic edge detection ──────────────────────────────────────────────────────

def test_no_arb_when_prices_equal():
    k = _q("kalshi", "K1", 0.50, 0.49)
    p = _q("polymarket", "P1", 0.50, 0.49)
    with patch("config.MIN_NET_EDGE", 0.02):
        result = analyse(k, p, "Equal prices test")
    assert result is None


def test_detects_buy_yes_kalshi():
    # Kalshi YES ask = 0.40, Poly YES bid = 0.55 → big gap
    k = _q("kalshi", "K1", 0.40, 0.39)
    p = _q("polymarket", "P1", 0.56, 0.55)
    with patch("config.MIN_NET_EDGE", 0.01), \
         patch("config.MAX_POSITION_PER_MARKET", 100), \
         patch("config.KALSHI_FEE_RATE", 0.07), \
         patch("config.POLY_FEE_RATE", 0.02):
        opp = analyse(k, p, "Test event")
    assert opp is not None
    assert opp.strategy == "buy_yes_kalshi"
    assert opp.min_edge > 0


def test_detects_buy_yes_poly():
    # Poly cheaper: YES ask = 0.35, Kalshi YES bid = 0.55
    k = _q("kalshi", "K1", 0.56, 0.55)
    p = _q("polymarket", "P1", 0.35, 0.34)
    with patch("config.MIN_NET_EDGE", 0.01), \
         patch("config.MAX_POSITION_PER_MARKET", 100), \
         patch("config.KALSHI_FEE_RATE", 0.07), \
         patch("config.POLY_FEE_RATE", 0.02):
        opp = analyse(k, p, "Test event")
    assert opp is not None
    assert opp.strategy == "buy_yes_poly"
    assert opp.min_edge > 0


def test_fee_reduces_edge():
    """Fees should make edge smaller than raw price gap."""
    k = _q("kalshi", "K1", 0.40, 0.39)
    p = _q("polymarket", "P1", 0.56, 0.55)
    with patch("config.MIN_NET_EDGE", 0.001), \
         patch("config.MAX_POSITION_PER_MARKET", 100), \
         patch("config.KALSHI_FEE_RATE", 0.07), \
         patch("config.POLY_FEE_RATE", 0.02):
        opp = analyse(k, p, "Fee test")
    raw_gap = 0.55 - 0.40
    assert opp.min_edge < raw_gap


def test_edge_positive_in_both_scenarios():
    """Guaranteed arb must be positive in BOTH YES and NO scenarios."""
    k = _q("kalshi", "K1", 0.38, 0.37)
    p = _q("polymarket", "P1", 0.58, 0.57)
    with patch("config.MIN_NET_EDGE", 0.01), \
         patch("config.MAX_POSITION_PER_MARKET", 200), \
         patch("config.KALSHI_FEE_RATE", 0.07), \
         patch("config.POLY_FEE_RATE", 0.02):
        opp = analyse(k, p, "Both scenarios test")
    assert opp is not None
    assert opp.net_edge_yes > 0
    assert opp.net_edge_no > 0


def test_contracts_are_whole_numbers():
    k = _q("kalshi", "K1", 0.38, 0.37)
    p = _q("polymarket", "P1", 0.58, 0.57)
    with patch("config.MIN_NET_EDGE", 0.01), \
         patch("config.MAX_POSITION_PER_MARKET", 150), \
         patch("config.KALSHI_FEE_RATE", 0.07), \
         patch("config.POLY_FEE_RATE", 0.02):
        opp = analyse(k, p, "Whole number test")
    assert isinstance(opp.max_contracts, int)
    assert opp.max_contracts >= 1


def test_stale_quote_rejected():
    k = _q("kalshi", "K1", 0.38, 0.37)
    p = _q("polymarket", "P1", 0.58, 0.57)
    k.fetched_at = time.time() - 999  # make stale
    with patch("config.MIN_NET_EDGE", 0.01), \
         patch("config.STALE_QUOTE_SECONDS", 300), \
         patch("config.MAX_POSITION_PER_MARKET", 100):
        opp = analyse(k, p, "Stale test")
    assert opp is None


def test_returns_none_below_threshold():
    k = _q("kalshi", "K1", 0.49, 0.48)
    p = _q("polymarket", "P1", 0.51, 0.50)
    with patch("config.MIN_NET_EDGE", 0.05), \
         patch("config.MAX_POSITION_PER_MARKET", 100), \
         patch("config.KALSHI_FEE_RATE", 0.07), \
         patch("config.POLY_FEE_RATE", 0.02):
        opp = analyse(k, p, "Below threshold test")
    assert opp is None
