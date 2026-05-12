"""Macro composite score (-100 to +100). Brief weights from config.yaml.

Negative score = dip-favourable regime. Positive = complacency / risk-on.
Eight components, each contributing within its own [-w, +w] range.
"""

from datetime import datetime, timezone
import numpy as np
import pandas as pd

from data_fetcher import log

CYCLICAL_SECTORS = {
    'Consumer Cyclical', 'Technology', 'Communication Services',
    'Industrials', 'Financial Services', 'Basic Materials', 'Energy',
}
DEFENSIVE_SECTORS = {
    'Consumer Defensive', 'Healthcare', 'Utilities', 'Real Estate',
}


def _linmap(x: float, lo: float, hi: float, out_lo: float, out_hi: float) -> float:
    if hi == lo:
        return (out_lo + out_hi) / 2
    t = (x - lo) / (hi - lo)
    t = max(0.0, min(1.0, t))
    return out_lo + t * (out_hi - out_lo)


def _series(rows, date_key, value_key):
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows)
    df[date_key] = pd.to_datetime(df[date_key]).dt.tz_localize(None)
    return pd.Series(
        pd.to_numeric(df[value_key], errors='coerce').values,
        index=df[date_key],
    ).dropna().sort_index()


def _score_vix_regime(vix_now, vix_series):
    if vix_now is None or vix_series.empty:
        return 0.0, "no data"
    ma20 = vix_series.tail(20).mean()
    rising = vix_now > ma20
    if vix_now > 25 and rising:
        return -30.0, f"high+rising (vix={vix_now:.2f}, ma20={ma20:.2f})"
    if vix_now > 25:
        return -15.0, f"high but stable (vix={vix_now:.2f})"
    if vix_now < 15:
        return _linmap(vix_now, 10, 15, 20, 5), f"complacent (vix={vix_now:.2f})"
    return _linmap(vix_now, 15, 25, 5, -10), f"neutral (vix={vix_now:.2f})"


def _score_vix_term_structure(vix_spot, vix_3m):
    if not vix_spot or not vix_3m:
        return 0.0, "no data"
    ratio = vix_3m / vix_spot
    if ratio < 1.0:
        return _linmap(ratio, 0.85, 1.0, -15, -3), f"backwardation ({ratio:.3f})"
    if ratio > 1.15:
        return 5.0, f"steep contango ({ratio:.3f})"
    return _linmap(ratio, 1.0, 1.15, -2, 5), f"normal contango ({ratio:.3f})"


def _score_yield_curve(treasury_rows):
    if not treasury_rows:
        return 0.0, "no data"
    df = pd.DataFrame(treasury_rows).sort_values('date')
    spread = (pd.to_numeric(df['year10'], errors='coerce')
              - pd.to_numeric(df['year2'], errors='coerce')).dropna()
    if spread.empty:
        return 0.0, "no spread"
    current = spread.iloc[-1]
    ago = spread.iloc[-21] if len(spread) > 21 else spread.iloc[0]
    trend = current - ago
    if current < 0 and trend > 0:
        return -20.0, f"inverted+steepening (cur={current:.2f}, dlt={trend:+.2f})"
    if current < 0:
        return -10.0, f"inverted+flat/flatten (cur={current:.2f})"
    if current > 0 and ago < 0 and trend > 0:
        return 10.0, f"normalising from inversion (cur={current:.2f})"
    return _linmap(current, 0, 2.5, 0, 5), f"normal positive (cur={current:.2f})"


def _score_credit_spreads(hy_rows):
    if not hy_rows:
        return 0.0, "no data"
    df = pd.DataFrame(hy_rows).sort_values('date')
    v = pd.to_numeric(df['value'], errors='coerce').dropna()
    if v.empty:
        return 0.0, "no values"
    current = v.iloc[-1]
    ago = v.iloc[-21] if len(v) > 21 else v.iloc[0]
    trend = current - ago
    if trend > 0.5:
        return -15.0, f"widening fast (cur={current:.2f}, +{trend:.2f})"
    if trend < -0.3:
        return 10.0, f"compressing (cur={current:.2f}, {trend:+.2f})"
    return _linmap(trend, -0.3, 0.5, 10, -15), f"stable (cur={current:.2f}, dlt={trend:+.2f})"


def _score_sector_rotation(sector_history):
    if not sector_history:
        return 0.0, "no data"
    df = pd.DataFrame(sector_history)
    if df.empty:
        return 0.0, "empty"
    df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
    pct_col = 'changesPercentage' if 'changesPercentage' in df.columns else 'averageChange'
    df['pct'] = pd.to_numeric(df[pct_col], errors='coerce')
    df = df.dropna(subset=['pct'])
    if df.empty:
        return 0.0, "no pct values"
    recent_cutoff = df['date'].max() - pd.Timedelta(days=30)
    recent = df[df['date'] >= recent_cutoff]
    by_sector = recent.groupby('sector')['pct'].mean()
    cyc = by_sector[by_sector.index.isin(CYCLICAL_SECTORS)].mean()
    dfn = by_sector[by_sector.index.isin(DEFENSIVE_SECTORS)].mean()
    if pd.isna(cyc) or pd.isna(dfn):
        return 0.0, f"sector taxonomy mismatch (got {list(by_sector.index)})"
    diff = cyc - dfn
    return _linmap(diff, -1.5, 1.5, -20, 20), \
        f"cyc-def={diff:+.2f} (cyc={cyc:+.2f}, def={dfn:+.2f})"


def _score_dollar(dx_block):
    if not dx_block or not dx_block.get('data'):
        return 0.0, "no data"
    data = dx_block['data']
    df = pd.DataFrame(data)
    if 'value' in df.columns:
        df['v'] = pd.to_numeric(df['value'], errors='coerce')
    elif 'close' in df.columns:
        df['v'] = pd.to_numeric(df['close'], errors='coerce')
    else:
        return 0.0, "unknown schema"
    df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
    df = df.dropna(subset=['v']).sort_values('date')
    if len(df) < 2:
        return 0.0, "too few"
    current = df['v'].iloc[-1]
    ago = df['v'].iloc[-21] if len(df) > 21 else df['v'].iloc[0]
    pct = (current - ago) / ago * 100
    # Weakening dollar (negative pct change) = +15
    return _linmap(pct, -3.0, 3.0, 15, -15), f"30d={pct:+.2f}% (cur={current:.2f})"


def _score_rsi_drawdown(gspc_history):
    if not gspc_history:
        return 0.0, "no data"
    df = pd.DataFrame(gspc_history).sort_values('date')
    closes = pd.to_numeric(df['close'], errors='coerce').dropna()
    if len(closes) < 30:
        return 0.0, "too few closes"
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = (100 - 100 / (1 + rs)).iloc[-1]
    rolling_high = closes.rolling(252, min_periods=20).max().iloc[-1]
    dd = closes.iloc[-1] / rolling_high - 1
    if pd.isna(rsi):
        return 0.0, "rsi na"
    if rsi < 30 and dd < -0.05:
        return 15.0, f"oversold+drawdown (rsi={rsi:.0f}, dd={dd:.2%})"
    if rsi > 70:
        return -10.0, f"overbought (rsi={rsi:.0f}, dd={dd:.2%})"
    return _linmap(rsi, 30, 70, 10, -10), f"rsi={rsi:.0f}, dd={dd:.2%}"


def _score_economic_calendar(events, today=None):
    if not events:
        return 0.0, "no data"
    today = today or datetime.now(timezone.utc).date()
    score = 0.0
    notes = []
    fomc_found = False
    cpi_found = False
    for e in events:
        if e.get('country') != 'US':
            continue
        if e.get('impact') not in ('High', 'Medium'):
            continue
        ds = (e.get('date') or '')[:10]
        try:
            d = datetime.strptime(ds, '%Y-%m-%d').date()
        except ValueError:
            continue
        delta = (d - today).days
        if delta < 0:
            continue
        ev = (e.get('event') or '').lower()
        if not fomc_found and delta <= 14 and (
            'fed' in ev or 'fomc' in ev or 'interest rate' in ev
        ):
            score -= 10
            notes.append(f"FOMC in {delta}d")
            fomc_found = True
        if not cpi_found and delta <= 7 and ('cpi' in ev or 'inflation' in ev):
            score -= 5
            notes.append(f"CPI in {delta}d")
            cpi_found = True
        if fomc_found and cpi_found:
            break
    score = max(score, -10)
    return score, "; ".join(notes) if notes else "no near-term high-impact events"


def _interpret(s: float) -> str:
    if s <= -50:
        return "Strong dip setup (multi-factor stress)"
    if s <= -25:
        return "Moderate dip lean"
    if s <= 10:
        return "Neutral / mixed"
    if s <= 30:
        return "Risk-on, dip unlikely near-term"
    return "Complacent / late-cycle ceiling"


def compute_composite(signals: dict) -> dict:
    vix_quote = signals.get('vix_quote') or []
    vix_now = float(vix_quote[0]['price']) if vix_quote else None
    vix_series = _series(signals.get('vix_history'), 'date', 'close')

    vix_spot_fred = signals.get('vix_spot_fred') or []
    vix_3m_fred = signals.get('vix_3m_fred') or []
    vix_spot_latest = vix_spot_fred[-1]['value'] if vix_spot_fred else vix_now
    vix_3m_latest = vix_3m_fred[-1]['value'] if vix_3m_fred else None

    components = {
        'vix_regime': _score_vix_regime(vix_now or vix_spot_latest, vix_series),
        'vix_term_structure': _score_vix_term_structure(vix_spot_latest, vix_3m_latest),
        'yield_curve': _score_yield_curve(signals.get('treasury_rates')),
        'credit_spreads': _score_credit_spreads(signals.get('credit_spreads_hy')),
        'sector_rotation': _score_sector_rotation(signals.get('sector_history')),
        'dollar_trend': _score_dollar(signals.get('dollar_index')),
        'rsi_drawdown': _score_rsi_drawdown(signals.get('gspc_history')),
        'economic_calendar': _score_economic_calendar(signals.get('economic_calendar')),
    }

    raw_sum = float(sum(s for s, _ in components.values()))
    # Theoretical bounds: |-30|+|-15|+|-20|+|-15|+|-20|+|-15|+|-15|+|-10| = 140
    normalised = raw_sum / 1.4

    log.info(f"Composite: raw={raw_sum:+.1f}, normalised={normalised:+.1f}")

    return {
        "components": {k: {"score": s, "note": n} for k, (s, n) in components.items()},
        "raw_total": raw_sum,
        "normalised_score": normalised,
        "interpretation": _interpret(normalised),
    }
