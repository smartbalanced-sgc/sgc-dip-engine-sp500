# SPY Dip Engine - Latest

**Fetched:** 2026-05-12T01:21:59.548096+00:00

## Current spot levels

| Signal | Value | Source |
|---|---|---|
| ^GSPC | 7412.95 | FMP |
| ^VIX  | 18.38 | FMP |
| VIX3M/VIX ratio | 1.193 (>1=contango, <1=backwardation) | FRED |
| HY credit spread (OAS %) | 2.81 | FRED BAMLH0A0HYM2 |
| Dollar index | 118.0392 (as of 2026-05-08) | fred:DTWEXBGS |

## Phase 2 - Conviction

**Headline:** NONE at dip level None (composite=-1.3, Neutral / mixed)

### Probability of touching dip within 60d

| Dip | Monte Carlo | Historical analog | Min-of-two | Label |
|---|---|---|---|---|
| -3% | 47.1% | 6.7% | 6.7% | NONE |
| -5% | 30.5% | 0.0% | 0.0% | NONE |
| -7% | 19.1% | 0.0% | 0.0% | NONE |
| -10% | 8.8% | 0.0% | 0.0% | NONE |
| -15% | 2.0% | 0.0% | 0.0% | NONE |
| -20% | 0.4% | 0.0% | 0.0% | NONE |

### Warnings

- DIVERGENCE at -3%: MC=47.1%, analog=6.7% (spread 40.4% > 20%)
- DIVERGENCE at -5%: MC=30.5%, analog=0.0% (spread 30.5% > 20%)

## Composite score breakdown

| Component | Score | Note |
|---|---|---|
| vix_regime | -0.1 | neutral (vix=18.38) |
| vix_term_structure | +5.0 | steep contango (1.193) |
| yield_curve | +0.9 | normal positive (cur=0.47) |
| credit_spreads | +4.7 | stable (cur=2.81, dlt=-0.13) |
| sector_rotation | +4.2 | cyc-def=+0.32 (cyc=+0.27, def=-0.04) |
| dollar_trend | +3.4 | 30d=-0.69% (cur=118.04) |
| rsi_drawdown | -10.0 | overbought (rsi=79, dd=0.00%) |
| economic_calendar | -10.0 | FOMC in 14d; CPI in 0d |
| **TOTAL (raw)** | **-1.8** | normalised=-1.3 |

## Monte Carlo corridor (60d, terminal price)

P10=7009 | P30=7527 | P50=7904 | P70=8298 | P90=8914

## Monte Carlo min-price corridor (worst touch over 60d)

P10=6706 | P30=7037 | P50=7212 | P70=7336 | P90=7441

## Historical analog (k=30 of 1226 aligned days)

Fingerprint: RSI=79, DD52w=0.00%, VIX=18.38, 2-10y spread=0.47

## Raw data

- Signals: `raw_signals_20260512.json`
- Models:  `models_20260512.json`
