# sgc-dip-engine-sp500

SPY 60-day dip prediction system. Spinoff from sgc-dip-engine.

## What it does

Predicts S&P 500 dip prices and probabilities over a 60-day forward window using three convergent methods:

1. **Monte Carlo** — VIX-calibrated forward vol (spot+3M blend), Student-t df=4 fat tails, 1M+ paths
2. **Historical analog matching** — 33 years of SPY daily data (1993+), regime fingerprint
3. **Macro composite score** — VIX regime, term structure, yield curve, credit spreads, sector rotation, dollar, RSI/drawdown, economic calendar overlay

Used to inform "lean-in" DCA decisions: front-load monthly contributions on high-conviction dip signals, otherwise standard monthly cadence.

## NOT for active trading

22-year buy-and-hold strategy. This is an entry-point optimiser, not a market-timer.

## Build status

- Phase 1: Data layer — done (v0.1-phase1-data)
- Phase 2: Modelling layer — done (v0.2-phase2-modelling)
- Phase 3a: Dashboard rendering — done (v0.3-phase3a-dashboard)
- **Phase 3b: GitHub Actions daily cron + Pages publishing — in progress**
- Phase 4: Backtest — pending

## Live dashboard

Once Pages is configured (see below): https://smartbalanced-sgc.github.io/sgc-dip-engine-sp500/

## Deployment setup (one-time, in the GitHub UI)

1. **Secrets** — at `Settings -> Secrets and variables -> Actions`, add three repository secrets:
   - `FMP_API_KEY` — FMP Starter
   - `FRED_API_KEY` — free, https://fred.stlouisfed.org/docs/api/api_key.html
   - `TIINGO_API_KEY` — free, https://www.tiingo.com/

2. **Pages** — at `Settings -> Pages`, set Source to "Deploy from a branch",
   Branch to `main`, Folder to `/docs`. Save.

3. **First run** — `Actions` tab -> `Daily SPY Dip Engine` -> `Run workflow`.
   Wait ~3 min. The workflow runs `python3 src/main.py`, commits
   `docs/index.html` + `data/conviction_history.jsonl` + `data/latest.md`
   back to main, and Pages auto-publishes.

4. **Cron** — afterwards, the workflow runs itself at 22:30 UTC Mon-Fri
   (after US market close). No manual action needed.

## Setup

    git clone https://github.com/smartbalanced-sgc/sgc-dip-engine-sp500
    cd sgc-dip-engine-sp500
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env
    # Edit .env with your keys
    export $(grep -v '^#' .env | xargs)

## Run

    python3 src/main.py

Writes `data/raw_signals_YYYYMMDD.json` plus `data/latest.md` summary.

## Data sources

| Signal | Source |
|---|---|
| ^GSPC OHLCV (5y daily) | FMP |
| ^VIX OHLCV (5y daily) | FMP |
| SPY daily 1993+ | Tiingo |
| Treasury rates (5y daily) | FMP (paginated 90d) |
| Economic calendar (90d fwd) | FMP |
| Sector performance | FMP |
| NYSE holidays | FMP |
| HY credit spreads | FRED BAMLH0A0HYM2 |
| Dollar index | FRED DTWEXBGS (UUP fallback) |
| VIX spot / VIX 3M | FRED VIXCLS / VXVCLS |
