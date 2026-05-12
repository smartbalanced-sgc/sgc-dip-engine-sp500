"""Historical regime fingerprint + k-nearest analog matching.

Fingerprint per day = (RSI14, drawdown from 52w high, VIX level, 2-10y spread).
Standardise, find k nearest historical days to today, look at their forward
60-day return + min drawdown distribution.

Limited to ~5y of aligned data (FMP treasury history cap). For Phase 2b we
can extend by pulling longer FRED treasury series.
"""

import numpy as np
import pandas as pd

from data_fetcher import log

DIP_LEVELS = (0.03, 0.05, 0.07, 0.10, 0.15, 0.20)
K_DEFAULT = 30
HORIZON_DEFAULT = 60


def _to_dated_series(rows: list, date_key: str, value_key: str) -> pd.Series:
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows)
    df[date_key] = pd.to_datetime(df[date_key]).dt.tz_localize(None)
    s = pd.Series(
        pd.to_numeric(df[value_key], errors='coerce').values,
        index=df[date_key],
    )
    return s.dropna().sort_index()


def _rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _drawdown_52w(closes: pd.Series) -> pd.Series:
    rolling_high = closes.rolling(252, min_periods=20).max()
    return closes / rolling_high - 1


def find_analogs(signals: dict, k: int = K_DEFAULT,
                 horizon_days: int = HORIZON_DEFAULT) -> dict:
    gspc_hist = signals.get('gspc_history')
    vix_hist = signals.get('vix_history')
    treasury = signals.get('treasury_rates')
    if not gspc_hist or not vix_hist or not treasury:
        log.warning("Analog: missing inputs, skipping")
        return None

    closes = _to_dated_series(gspc_hist, 'date', 'close')
    vix = _to_dated_series(vix_hist, 'date', 'close')

    tdf = pd.DataFrame(treasury)
    tdf['date'] = pd.to_datetime(tdf['date']).dt.tz_localize(None)
    tdf = tdf.set_index('date').sort_index()
    yc_spread = (pd.to_numeric(tdf['year10'], errors='coerce')
                 - pd.to_numeric(tdf['year2'], errors='coerce'))

    df = pd.DataFrame({
        'close': closes,
        'rsi': _rsi(closes),
        'dd': _drawdown_52w(closes),
        'vix': vix,
        'yc': yc_spread,
    }).dropna()

    if len(df) < horizon_days + 30:
        log.warning(f"Analog: only {len(df)} aligned rows, too few for matching")
        return None

    feat_cols = ['rsi', 'dd', 'vix', 'yc']
    means = df[feat_cols].mean()
    stds = df[feat_cols].std().replace(0, 1.0)
    z = (df[feat_cols] - means) / stds

    current_z = z.iloc[-1].values
    candidates = z.iloc[:-horizon_days]
    dists = np.linalg.norm(candidates.values - current_z, axis=1)
    nearest_idx = np.argsort(dists)[:k]
    analog_dates = candidates.index[nearest_idx]

    closes_arr = df['close']
    forward_terminal = []
    forward_min_dd = []
    for d in analog_dates:
        pos = df.index.get_loc(d)
        start_px = closes_arr.iloc[pos]
        window = closes_arr.iloc[pos + 1:pos + 1 + horizon_days]
        if len(window) < horizon_days:
            continue
        forward_terminal.append(window.iloc[-1] / start_px - 1)
        forward_min_dd.append(window.min() / start_px - 1)

    if not forward_terminal:
        return None

    ft = np.array(forward_terminal)
    fm = np.array(forward_min_dd)

    return {
        "k_matches": int(len(ft)),
        "sample_size_total": int(len(df)),
        "analog_dates": [str(d.date()) for d in analog_dates[:len(ft)]],
        "current_fingerprint": {
            "rsi": float(df['rsi'].iloc[-1]),
            "drawdown_52w": float(df['dd'].iloc[-1]),
            "vix": float(df['vix'].iloc[-1]),
            "yc_spread": float(df['yc'].iloc[-1]),
        },
        "terminal_return": {
            f"P{p}": float(np.percentile(ft, p)) for p in (10, 30, 50, 70, 90)
        },
        "min_drawdown": {
            f"P{p}": float(np.percentile(fm, p)) for p in (10, 30, 50, 70, 90)
        },
        "p_touch": {
            f"-{int(d * 100)}%": float(np.mean(fm <= -d)) for d in DIP_LEVELS
        },
    }
