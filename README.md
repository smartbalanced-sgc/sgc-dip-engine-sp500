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

- **Phase 1: Data layer** — in progress
- Phase 2: Modelling layer — pending
- Phase 3: Output layer (GitHub Pages dashboard) — pending
- Phase 4: Backtest — pending

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
