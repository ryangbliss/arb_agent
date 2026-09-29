"""Tests for market matching logic."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from exchanges.base import MarketInfo
from matching import match_markets, _keyword_overlap, _normalize


def _k(title, market_id="K1", close="2025-07-04T00:00:00Z"):
    return MarketInfo(exchange="kalshi", market_id=market_id, title=title, close_time=close)


def _p(title, market_id="P1", close="2025-07-04T00:00:00Z"):
    return MarketInfo(exchange="polymarket", market_id=market_id, title=title, close_time=close)


# ── normalize ────────────────────────────────────────────────────────────────

def test_normalize_removes_stopwords():
    words = _normalize("Will the Fed cut rates?")
    assert "will" not in words
    assert "the" not in words
    assert "fed" in words


def test_normalize_lowercases():
    words = _normalize("Trump Biden 2024")
    assert "trump" in words
    assert "biden" in words


def test_keyword_overlap_identical():
    assert _keyword_overlap("Fed rate cut June 2025", "Fed rate cut June 2025") == 1.0


def test_keyword_overlap_no_overlap():
    score = _keyword_overlap("Bitcoin price", "Trump election win")
    assert score == 0.0


def test_keyword_overlap_partial():
    score = _keyword_overlap("Fed rate cut June 2025", "Will the Fed cut rates by June?")
    assert 0.3 < score < 1.0


# ── matching ─────────────────────────────────────────────────────────────────

def test_identical_title_matches():
    k = [_k("Will the Fed cut rates in June 2025?", "FED-JUNE")]
    p = [_p("Will the Fed cut rates in June 2025?", "fed-cut-june")]
    matched, rejected = match_markets(k, p, confidence_threshold=0.50)
    assert len(matched) == 1


def test_unrelated_titles_do_not_match():
    k = [_k("Will Bitcoin reach $100k by 2025?", "BTC-100K")]
    p = [_p("Will Trump win the 2024 election?", "trump-2024")]
    matched, rejected = match_markets(k, p, confidence_threshold=0.70)
    assert len(matched) == 0


def test_year_mismatch_penalises_score():
    k = [_k("Will the S&P 500 hit 6000 in 2024?", "SPX-2024")]
    p = [_p("Will the S&P 500 hit 6000 in 2025?", "spx-2025")]
    matched, _ = match_markets(k, p, confidence_threshold=0.75)
    # Year mismatch should prevent high confidence
    assert len(matched) == 0


def test_deduplication_one_poly_per_match():
    k1 = _k("Fed cuts rates June 2025", "FED-K1")
    k2 = _k("Fed rate cut June 2025", "FED-K2")
    p = _p("Will the Fed cut rates June 2025?", "fed-june")
    matched, _ = match_markets([k1, k2], [p], confidence_threshold=0.40)
    # Same poly market should only appear once
    poly_ids = [m.poly.market_id for m in matched]
    assert len(poly_ids) == len(set(poly_ids))


def test_close_time_mismatch_reduces_confidence():
    k = [_k("Will the NBA finals end before July?", "NBA-K", close="2025-06-15T00:00:00Z")]
    p = [_p("Will the NBA finals end before July?", "nba-p", close="2025-12-31T00:00:00Z")]
    matched, _ = match_markets(k, p, confidence_threshold=0.85)
    assert len(matched) == 0
