# Phase 1 - Data Layer

## Goal

Single script fetches every available signal from FMP, FRED, and Tiingo,
dumps to JSON. No modelling yet - just verify data is reachable, fresh,
and sane before building anything on top.

## What gets fetched

| Signal | Source | Lookback | Rows expected |
|---|---|---|---|
| ^GSPC current quote | FMP | live | 1 |
| ^VIX current quote | FMP | live | 1 |
| ^GSPC OHLCV | FMP | 5 years daily | ~1260 |
| ^VIX OHLCV | FMP | 5 years daily | ~1260 |
| Treasury rates 1mo-30yr | FMP, paginated 90d chunks | 5 years daily | ~1260 |
| Economic calendar | FMP | 90 days forward | varies |
| Sector snapshot | FMP | today | 11 |
| Sector history | FMP | 90 days | varies |
| NYSE holidays | FMP | 90 days forward | ~2-3 |
| HY credit spreads | FRED BAMLH0A0HYM2 | 5 years daily | ~1260 |
| Dollar index | FRED DTWEXBGS (UUP fallback) | 5 years daily | ~1260 |
| VIX spot | FRED VIXCLS | 5 years daily | ~1260 |
| VIX 3M | FRED VXVCLS | 5 years daily | ~1260 |
| SPY long history | Tiingo | 1993-01-29 to today | ~8300 |

## How to run

    cd sgc-dip-engine-sp500
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env
    # Edit .env, fill in keys
    export $(grep -v '^#' .env | xargs)
    python3 src/main.py

Expected runtime: ~30-60 seconds first run (Tiingo long history pull,
cached after). Subsequent runs ~15 seconds.

## Output

- `data/raw_signals_YYYYMMDD.json` - full signal dump
- `data/latest.md` - markdown summary (renders on GitHub)
- `data/cache/spy_long_history.json` - cached SPY 1993+ (refreshed quarterly)

## Manual verification checklist

Before declaring Phase 1 successful and starting Phase 2:

1. Every signal in the summary table shows row count > 0
2. ^GSPC current price matches Trading 212 / Google Finance
3. ^VIX is in 10-50 range
4. Treasury 10y - 2y is computable and within historical range (-1% to +3%)
5. HY credit spread is in 2-10% range
6. SPY long history has >8000 rows (33+ years of daily data)
7. Most recent dates in each series are within 5 business days of today
8. No NULL entries in the summary table

## What's NEXT (Phase 2)

Build the modelling layer:
- VIX-blended Monte Carlo (Student-t df=4, 1M paths, spot+3M blend for 60d horizon)
- Historical analog matching against the 33-year SPY series
- Macro composite score from the signal stack, weights in config.yaml

Phase 2 will reuse `data_fetcher.fetch_all_signals()` with no changes to
Phase 1 required.
