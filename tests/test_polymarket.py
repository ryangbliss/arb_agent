"""Tests for Polymarket market parsing and binary filtering."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import json
from unittest.mock import patch, MagicMock

import pytest


BINARY_MARKET = {
    "question": "Will the Fed cut rates in June 2025?",
    "slug": "fed-cut-june-2025",
    "outcomes": '["Yes","No"]',
    "outcomePrices": '["0.65","0.35"]',
    "active": True,
    "closed": False,
    "endDate": "2025-06-30T00:00:00Z",
    "category": "Finance",
}

MULTI_OUTCOME_MARKET = {
    "question": "Who wins the championship?",
    "slug": "championship-winner",
    "outcomes": '["Team A","Team B","Team C"]',
    "outcomePrices": '["0.40","0.35","0.25"]',
    "active": True,
    "closed": False,
}


def _make_poly():
    with patch.dict(os.environ, {
        "KALSHI_KEY_ID": "x", "KALSHI_PRIVATE_KEY_PATH": "/dev/null",
    }):
        from exchanges.polymarket import PolymarketExchange
        return PolymarketExchange()


def test_binary_market_parsed(monkeypatch):
    poly = _make_poly()
    mock_resp = MagicMock()
    mock_resp.json.return_value = [BINARY_MARKET]
    mock_resp.raise_for_status = lambda: None

    monkeypatch.setattr("requests.Session.get", lambda *a, **kw: mock_resp)
    markets = poly.fetch_markets()
    assert len(markets) == 1
    assert markets[0].market_id == "fed-cut-june-2025"
    assert markets[0].title == "Will the Fed cut rates in June 2025?"


def test_multi_outcome_excluded(monkeypatch):
    poly = _make_poly()
    mock_resp = MagicMock()
    mock_resp.json.return_value = [MULTI_OUTCOME_MARKET]
    mock_resp.raise_for_status = lambda: None

    monkeypatch.setattr("requests.Session.get", lambda *a, **kw: mock_resp)
    markets = poly.fetch_markets()
    assert len(markets) == 0


def test_quote_extracts_yes_price(monkeypatch):
    poly = _make_poly()
    mock_resp = MagicMock()
    mock_resp.json.return_value = [BINARY_MARKET]
    mock_resp.raise_for_status = lambda: None

    monkeypatch.setattr("requests.Session.get", lambda *a, **kw: mock_resp)
    quote = poly.fetch_quote("fed-cut-june-2025")
    assert quote is not None
    assert abs(quote.mid - 0.65) < 0.01


def test_quote_returns_none_for_settled(monkeypatch):
    settled = dict(BINARY_MARKET)
    settled["outcomePrices"] = '["1.0","0.0"]'
    poly = _make_poly()
    mock_resp = MagicMock()
    mock_resp.json.return_value = [settled]
    mock_resp.raise_for_status = lambda: None

    monkeypatch.setattr("requests.Session.get", lambda *a, **kw: mock_resp)
    quote = poly.fetch_quote("fed-cut-june-2025")
    assert quote is None


def test_spread_is_symmetric(monkeypatch):
    poly = _make_poly()
    mock_resp = MagicMock()
    mock_resp.json.return_value = [BINARY_MARKET]
    mock_resp.raise_for_status = lambda: None

    monkeypatch.setattr("requests.Session.get", lambda *a, **kw: mock_resp)
    q = poly.fetch_quote("fed-cut-june-2025")
    assert q.yes_bid < q.mid < q.yes_ask
    assert abs(q.spread - 0.01) < 0.001
