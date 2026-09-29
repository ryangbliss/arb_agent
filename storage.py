"""
storage.py — SQLite + CSV persistence.
"""
from __future__ import annotations

import csv
import json
import sqlite3
import time
from datetime import datetime, date
from pathlib import Path
from typing import Any, Optional

from arbitrage import ArbOpportunity
from paper_trader import SimFill
import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    id          TEXT PRIMARY KEY,
    ts          REAL,
    date        TEXT,
    kalshi_id   TEXT,
    poly_id     TEXT,
    title       TEXT,
    strategy    TEXT,
    k_ask       REAL,
    p_bid       REAL,
    min_edge    REAL,
    max_contr   INTEGER,
    simulated   INTEGER,
    rationale   TEXT
);

CREATE TABLE IF NOT EXISTS fills (
    fill_id     TEXT PRIMARY KEY,
    opp_id      TEXT,
    ts          REAL,
    venue       TEXT,
    side        TEXT,
    action      TEXT,
    contracts   INTEGER,
    price       REAL,
    fee         REAL
);

CREATE TABLE IF NOT EXISTS positions (
    opp_id          TEXT PRIMARY KEY,
    kalshi_id       TEXT,
    poly_id         TEXT,
    title           TEXT,
    k_side          TEXT,
    k_contracts     INTEGER,
    k_avg_price     REAL,
    p_side          TEXT,
    p_contracts     INTEGER,
    p_avg_price     REAL,
    entry_time      REAL,
    closed          INTEGER DEFAULT 0,
    resolved_outcome TEXT,
    realized_pnl    REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily_summary (
    date            TEXT PRIMARY KEY,
    opportunities   INTEGER,
    trades          INTEGER,
    realized_pnl    REAL,
    fees_paid       REAL,
    ending_cash     REAL
);
"""


class Storage:
    def __init__(self, db_path: Path = None) -> None:
        self._db_path = db_path or config.DB_PATH
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # ── Opportunities ─────────────────────────────────────────────────────────

    def save_opportunity(self, opp: ArbOpportunity, opp_id: str, simulated: bool) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO opportunities
               (id, ts, date, kalshi_id, poly_id, title, strategy,
                k_ask, p_bid, min_edge, max_contr, simulated, rationale)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                opp_id, time.time(), str(date.today()),
                opp.kalshi_ticker, opp.poly_slug, opp.event_title,
                opp.strategy, opp.k_yes_ask, opp.p_yes_bid,
                opp.min_edge, opp.max_contracts, int(simulated), opp.rationale,
            ),
        )
        self._conn.commit()

    def today_opportunities(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM opportunities WHERE date=? ORDER BY ts DESC",
            (str(date.today()),),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Fills ─────────────────────────────────────────────────────────────────

    def save_fill(self, fill: SimFill) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO fills
               (fill_id, opp_id, ts, venue, side, action, contracts, price, fee)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (fill.fill_id, fill.opp_id, fill.timestamp,
             fill.venue, fill.side, fill.action,
             fill.contracts, fill.price, fill.fee),
        )
        self._conn.commit()

    # ── Positions ─────────────────────────────────────────────────────────────

    def save_position(self, pos) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO positions
               (opp_id, kalshi_id, poly_id, title, k_side, k_contracts, k_avg_price,
                p_side, p_contracts, p_avg_price, entry_time, closed)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pos.opp_id, pos.kalshi_ticker, pos.poly_slug, pos.event_title,
             pos.k_side, pos.k_contracts, pos.k_avg_price,
             pos.p_side, pos.p_contracts, pos.p_avg_price,
             pos.entry_time, int(pos.closed)),
        )
        self._conn.commit()

    def update_position_resolved(self, opp_id: str, outcome: str, realized_pnl: float) -> None:
        self._conn.execute(
            "UPDATE positions SET closed=1, resolved_outcome=?, realized_pnl=? WHERE opp_id=?",
            (outcome, realized_pnl, opp_id),
        )
        self._conn.commit()

    # ── Daily summary ─────────────────────────────────────────────────────────

    def save_daily_summary(self, opps: int, trades: int, pnl: float,
                           fees: float, cash: float) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO daily_summary
               (date, opportunities, trades, realized_pnl, fees_paid, ending_cash)
               VALUES (?,?,?,?,?,?)""",
            (str(date.today()), opps, trades, pnl, fees, cash),
        )
        self._conn.commit()

    def history(self, days: int = 30) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM daily_summary ORDER BY date DESC LIMIT ?", (days,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── CSV export ────────────────────────────────────────────────────────────

    def export_today_csv(self) -> Path:
        today = str(date.today())
        path = config.REPORTS_DIR / f"report_{today}.csv"
        opps = self.today_opportunities()
        if not opps:
            return path
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=opps[0].keys())
            writer.writeheader()
            writer.writerows(opps)
        return path
