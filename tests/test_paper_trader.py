"""Tests for paper trader accounting."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
import time
from unittest.mock import patch, MagicMock
from exchanges.base import Quote
from arbitrage import ArbOpportunity


def _make_opp(strategy="buy_yes_kalshi", k_ask=0.38, p_bid=0.55):
    return ArbOpportunity(
        kalshi_ticker="TEST-K",
        poly_slug="test-poly-slug",
        event_title="Test event: Will X happen?",
        strategy=strategy,
        k_yes_ask=k_ask,
        k_yes_bid=k_ask - 0.01,
        p_yes_ask=p_bid + 0.01,
        p_yes_bid=p_bid,
        cost_per_contract=round(k_ask + (1 - p_bid), 4),
        net_edge_yes=0.05,
        net_edge_no=0.04,
        min_edge=0.04,
        max_contracts=10,
        gross_profit_potential=0.40,
        k_quote_age_s=1.0,
        p_quote_age_s=1.0,
        rationale="Test rationale",
    )


def _make_trader():
    with patch("config.PAPER_CASH_KALSHI", 10000), \
         patch("config.PAPER_CASH_POLY", 10000), \
         patch("config.KALSHI_FEE_RATE", 0.07), \
         patch("config.POLY_FEE_RATE", 0.02):
        from paper_trader import PaperTrader
        return PaperTrader()


def test_cash_deducted_on_execute():
    trader = _make_trader()
    opp = _make_opp()
    k_before = trader.cash["kalshi"]
    p_before = trader.cash["polymarket"]
    with patch("config.KALSHI_FEE_RATE", 0.07), patch("config.POLY_FEE_RATE", 0.02):
        opp_id = trader.execute(opp)
    assert trader.cash["kalshi"] < k_before
    assert trader.cash["polymarket"] < p_before


def test_execute_returns_opp_id():
    trader = _make_trader()
    with patch("config.KALSHI_FEE_RATE", 0.07), patch("config.POLY_FEE_RATE", 0.02):
        opp_id = trader.execute(_make_opp())
    assert opp_id is not None
    assert len(opp_id) == 8


def test_two_fills_created_per_trade():
    trader = _make_trader()
    with patch("config.KALSHI_FEE_RATE", 0.07), patch("config.POLY_FEE_RATE", 0.02):
        trader.execute(_make_opp())
    assert len(trader.fills) == 2


def test_resolve_yes_increases_kalshi_cash():
    trader = _make_trader()
    with patch("config.KALSHI_FEE_RATE", 0.07), patch("config.POLY_FEE_RATE", 0.02):
        opp_id = trader.execute(_make_opp(strategy="buy_yes_kalshi"))
    k_after_entry = trader.cash["kalshi"]
    with patch("config.KALSHI_FEE_RATE", 0.07), patch("config.POLY_FEE_RATE", 0.02):
        trader.resolve(opp_id, "YES")
    assert trader.cash["kalshi"] > k_after_entry


def test_position_marked_closed_after_resolve():
    trader = _make_trader()
    with patch("config.KALSHI_FEE_RATE", 0.07), patch("config.POLY_FEE_RATE", 0.02):
        opp_id = trader.execute(_make_opp())
        trader.resolve(opp_id, "YES")
    assert trader.positions[opp_id].closed is True


def test_realized_pnl_tracked():
    trader = _make_trader()
    with patch("config.KALSHI_FEE_RATE", 0.07), patch("config.POLY_FEE_RATE", 0.02):
        opp_id = trader.execute(_make_opp())
        pnl = trader.resolve(opp_id, "YES")
    assert isinstance(pnl, float)
    assert trader.daily_realized_pnl == pnl


def test_snapshot_structure():
    trader = _make_trader()
    snap = trader.snapshot()
    assert "cash_kalshi" in snap
    assert "cash_poly" in snap
    assert "daily_realized_pnl" in snap
    assert "positions" in snap


def test_insufficient_cash_returns_none():
    trader = _make_trader()
    trader.cash["kalshi"] = 0.01  # not enough
    with patch("config.KALSHI_FEE_RATE", 0.07), patch("config.POLY_FEE_RATE", 0.02):
        opp_id = trader.execute(_make_opp())
    assert opp_id is None
