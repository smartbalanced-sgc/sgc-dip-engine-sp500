# SPY Dip Engine - Latest

**Fetched:** 2026-05-12T01:00:31.469966+00:00

## Current spot levels

| Signal | Value | Source |
|---|---|---|
| ^GSPC | 7412.95 | FMP |
| ^VIX  | 18.38 | FMP |
| VIX3M/VIX ratio | n/a | FRED |
| HY credit spread (OAS %) | None | FRED BAMLH0A0HYM2 |
| Dollar index | 24.39 (as of 2021-05-13) | fmp:UUP |

## Phase 2 - Conviction

**Headline:** NONE at dip level None (composite=-10.3, Neutral / mixed)

### Probability of touching dip within 60d

| Dip | Monte Carlo | Historical analog | Min-of-two | Label |
|---|---|---|---|---|
| -3% | n/a | 6.7% | 6.7% | NONE |
| -5% | n/a | 0.0% | 0.0% | NONE |
| -7% | n/a | 0.0% | 0.0% | NONE |
| -10% | n/a | 0.0% | 0.0% | NONE |
| -15% | n/a | 0.0% | 0.0% | NONE |
| -20% | n/a | 0.0% | 0.0% | NONE |

## Composite score breakdown

| Component | Score | Note |
|---|---|---|
| vix_regime | -0.1 | neutral (vix=18.38) |
| vix_term_structure | +0.0 | no data |
| yield_curve | +0.9 | normal positive (cur=0.47) |
| credit_spreads | +0.0 | no data |
| sector_rotation | +4.2 | cyc-def=+0.32 (cyc=+0.27, def=-0.04) |
| dollar_trend | +0.5 | 30d=-0.11% (cur=27.35) |
| rsi_drawdown | -10.0 | overbought (rsi=79, dd=0.00%) |
| economic_calendar | -10.0 | FOMC in 14d; CPI in 0d |
| **TOTAL (raw)** | **-14.4** | normalised=-10.3 |

## Historical analog (k=30 of 1226 aligned days)

Fingerprint: RSI=79, DD52w=0.00%, VIX=18.38, 2-10y spread=0.47

## Raw data

- Signals: `raw_signals_20260512.json`
- Models:  `models_20260512.json`
