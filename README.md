# Kalshi × Polymarket Arbitrage Agent

A paper-trading bot that scans Kalshi and Polymarket for the same event priced differently on each platform, and flags trades that lock in a profit no matter how the event resolves.

> **Paper trading only.** No real orders are ever placed. The bot simulates what the trades would have made, for research and learning.

---

## What it does

1. **Pulls live markets** – fetches every open binary (YES/NO) market from Kalshi and Polymarket.
2. **Matches events across platforms** – pairs up markets that are about the same event, using deterministic text scoring plus optional LLM confirmation (Claude).
3. **Finds arbitrage** – checks whether buying YES on one platform and NO on the other costs less than the guaranteed payout, *after fees*, in both outcomes.
4. **Paper-trades it** – simulates fills, tracks positions and P&L, and enforces risk limits.
5. **Shows it live** – serves a dashboard at `http://localhost:8765`.

---

## How the arbitrage math works

Say Kalshi prices YES at **38¢** and Polymarket prices YES at **55¢** on the same event.

- Buy **YES on Kalshi** for 38¢
- Buy **NO on Polymarket** for 45¢ (100¢ − 55¢)
- **Total cost: 83¢**, and exactly one side pays out $1

| Outcome | Payout | Fee | Net payout | Profit |
|---|---|---|---|---|
| YES happens | Kalshi pays 100¢ | 7% × 62¢ profit = 4.3¢ | 95.7¢ | **+12.7¢** |
| NO happens | Polymarket pays 100¢ | 2% × 55¢ profit = 1.1¢ | 98.9¢ | **+15.9¢** |

Both outcomes are profitable, so the position is risk-free on paper. The bot's **edge** is the *smaller* of the two profits, and it only trades when that edge clears a minimum threshold (`MIN_NET_EDGE`, default 2%).

### Fee model

| Exchange | Fee |
|---|---|
| Kalshi | 7% of winnings |
| Polymarket | 2% of winnings |

---

## Example output

```
NEW   Will the Fed cut rates in June?
  ────────────────────────────────────────────────
  Strategy : BUY YES Kalshi + NO Poly
  Kalshi   : ask=38.0¢  bid=37.0¢
  Poly     : ask=56.0¢  bid=55.0¢
  Net edge : 4.20¢/contract  (YES scenario: 5.10¢  NO scenario: 4.20¢)
  Size     : 10 contracts × $0.830 = $0.42 potential profit
```

---

## Setup

**1. Install dependencies**
```bash
pip3 install -r requirements.txt
```

**2. Add your API keys**
```bash
cp .env.example .env
```
Then fill in `.env`:
```
KALSHI_KEY_ID=your-kalshi-key-uuid
KALSHI_PRIVATE_KEY_PATH=/path/to/kalshi_key.pem
ANTHROPIC_API_KEY=sk-ant-...   # optional, improves matching
```
Get a Kalshi key at kalshi.com → Account → API → create a key and download the `.pem` file. Secrets live only in `.env`, which is git-ignored.

**3. Run it**

| Command | What it does |
|---|---|
| `python3 main.py` | Continuous paper-trading mode + live dashboard (Ctrl+C to stop) |
| `python3 main.py --scan-once` | Single scan, print opportunities, exit |
| `python3 main.py --report` | Today's paper P&L summary and history |
| `python3 -m pytest tests/ -v` | Run the test suite (35 tests, no live API calls) |

---

## Project structure

```
arb_agent/
├── main.py              # entry point
├── config.py            # settings loaded from .env
├── exchanges/
│   ├── base.py          # Quote and MarketInfo dataclasses
│   ├── kalshi.py        # Kalshi API adapter (RSA-signed requests)
│   └── polymarket.py    # Polymarket API adapter
├── matching.py          # cross-platform market matching (deterministic + LLM)
├── arbitrage.py         # edge calculation with fees
├── paper_trader.py      # simulated fills and P&L tracking
├── risk.py              # pre-trade risk checks (daily loss, position limits, stale quotes)
├── storage.py           # SQLite + CSV persistence
├── reporting.py         # console output + dashboard state
├── dashboard_server.py  # local HTTP server for the dashboard
├── dashboard/index.html # live dashboard UI
├── postmortem.py        # post-run analysis of flagged opportunities
└── tests/               # unit tests
```

---

## Security

- All secrets live in `.env` and are never committed.
- No order-placement code exists anywhere in this project.
- Only read-only API endpoints are used.
