"""Walk-forward backtest over the 5y aligned window.

For each historical day t in [start+252, end-60]:
- Compute composite score using only data up to t (no look-ahead).
- Run abridged Monte Carlo (20k paths) with that day's VIX/VIX3M/closes.
- Find k=30 nearest analogs in [0, t-60], compute their forward 60d hit rates.
- Record realised forward 60d min-drawdown.

Output: data/backtest_results.json. Run via:
    python3 src/backtest.py
"""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from data_fetcher import CFG, log, utcnow

DIP_LEVELS = (0.03, 0.05, 0.07, 0.10)
N_PATHS_BACKTEST = 20_000
T_DF = 4
T_SCALE = math.sqrt((T_DF - 2) / T_DF)
HORIZON = 60
K_ANALOGS = 30
LOOKBACK_DAYS = 252  # min history needed before backtest can start

CYCLICAL_SECTORS = {
    'Consumer Cyclical', 'Technology', 'Communication Services',
    'Industrials', 'Financial Services', 'Basic Materials', 'Energy',
}
DEFENSIVE_SECTORS = {
    'Consumer Defensive', 'Healthcare', 'Utilities', 'Real Estate',
}


def _load_latest_signals() -> dict:
    data_dir = Path(CFG['paths']['data_dir'])
    candidates = sorted(data_dir.glob('raw_signals_*.json'))
    if not candidates:
        raise RuntimeError(
            "No raw_signals_*.json found. Run python3 src/main.py first."
        )
    log.info(f"Using signals: {candidates[-1].name}")
    with open(candidates[-1]) as f:
        return json.load(f)


def _series_from_rows(rows, date_key, value_key) -> pd.Series:
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows)
    df[date_key] = pd.to_datetime(df[date_key]).dt.tz_localize(None)
    s = pd.Series(
        pd.to_numeric(df[value_key], errors='coerce').values,
        index=df[date_key],
    )
    return s.dropna().sort_index()


def build_aligned_df(signals: dict) -> pd.DataFrame:
    """Date-indexed dataframe with every feature used in the backtest."""
    closes = _series_from_rows(signals.get('gspc_history') or [], 'date', 'close')
    vix = _series_from_rows(signals.get('vix_history') or [], 'date', 'close')
    vix3m = _series_from_rows(signals.get('vix_3m_fred') or [], 'date', 'value')
    hy = _series_from_rows(signals.get('credit_spreads_hy') or [], 'date', 'value')

    # Treasury 2-10
    tres = pd.DataFrame(signals.get('treasury_rates') or [])
    if not tres.empty:
        tres['date'] = pd.to_datetime(tres['date']).dt.tz_localize(None)
        tres = tres.set_index('date').sort_index()
        yc = (pd.to_numeric(tres['year10'], errors='coerce')
              - pd.to_numeric(tres['year2'], errors='coerce'))
    else:
        yc = pd.Series(dtype=float)

    # Dollar index (FRED format: {date, value})
    dx_block = signals.get('dollar_index') or {}
    dx_rows = dx_block.get('data') or []
    if dx_rows and isinstance(dx_rows[0], dict) and 'value' in dx_rows[0]:
        dxy = _series_from_rows(dx_rows, 'date', 'value')
    else:
        dxy = pd.Series(dtype=float)

    # Sector rotation: cyc-def daily, smoothed 30d
    sh = pd.DataFrame(signals.get('sector_history') or [])
    if not sh.empty:
        sh['date'] = pd.to_datetime(sh['date']).dt.tz_localize(None)
        pct_col = 'changesPercentage' if 'changesPercentage' in sh.columns else 'averageChange'
        sh['pct'] = pd.to_numeric(sh[pct_col], errors='coerce')
        sh = sh.dropna(subset=['pct'])
        cyc = sh[sh['sector'].isin(CYCLICAL_SECTORS)].groupby('date')['pct'].mean()
        dfn = sh[sh['sector'].isin(DEFENSIVE_SECTORS)].groupby('date')['pct'].mean()
        sector_rot = (cyc - dfn).rolling(30, min_periods=10).mean()
    else:
        sector_rot = pd.Series(dtype=float)

    # Derived
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    dd = closes / closes.rolling(252, min_periods=20).max() - 1

    df = pd.DataFrame({
        'close': closes,
        'rsi': rsi,
        'dd': dd,
        'vix': vix,
        'vix3m': vix3m,
        'yc': yc,
        'hy': hy,
        'dxy': dxy,
        'sector_rot': sector_rot,
    }).ffill(limit=5).dropna()
    return df


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def _linmap(x, lo, hi, out_lo, out_hi):
    if hi == lo:
        return (out_lo + out_hi) / 2
    t = _clip((x - lo) / (hi - lo), 0.0, 1.0)
    return out_lo + t * (out_hi - out_lo)


def composite_at(row: pd.Series, history: pd.DataFrame) -> tuple:
    scores = {}

    vix = row['vix']
    ma20 = history['vix'].tail(20).mean()
    if vix > 25 and vix > ma20:
        scores['vix_regime'] = -30.0
    elif vix > 25:
        scores['vix_regime'] = -15.0
    elif vix < 15:
        scores['vix_regime'] = _linmap(vix, 10, 15, 20, 5)
    else:
        scores['vix_regime'] = _linmap(vix, 15, 25, 5, -10)

    ratio = row['vix3m'] / vix if vix else 1.0
    if ratio < 1.0:
        scores['vix_ts'] = _linmap(ratio, 0.85, 1.0, -15, -3)
    elif ratio > 1.15:
        scores['vix_ts'] = 5.0
    else:
        scores['vix_ts'] = _linmap(ratio, 1.0, 1.15, -2, 5)

    cur_yc = row['yc']
    yc_30d_ago = history['yc'].iloc[-21] if len(history) > 21 else history['yc'].iloc[0]
    yc_trend = cur_yc - yc_30d_ago
    if cur_yc < 0 and yc_trend > 0:
        scores['yc'] = -20.0
    elif cur_yc < 0:
        scores['yc'] = -10.0
    elif yc_30d_ago < 0 and yc_trend > 0:
        scores['yc'] = 10.0
    else:
        scores['yc'] = _linmap(cur_yc, 0, 2.5, 0, 5)

    hy_now = row.get('hy')
    if not pd.isna(hy_now):
        hy_30d = history['hy'].iloc[-21] if len(history) > 21 else history['hy'].iloc[0]
        trend = hy_now - hy_30d
        if trend > 0.5:
            scores['credit'] = -15.0
        elif trend < -0.3:
            scores['credit'] = 10.0
        else:
            scores['credit'] = _linmap(trend, -0.3, 0.5, 10, -15)
    else:
        scores['credit'] = 0.0

    sec = row.get('sector_rot')
    scores['sector'] = _linmap(sec, -1.5, 1.5, -20, 20) if not pd.isna(sec) else 0.0

    dxy_now = row.get('dxy')
    if not pd.isna(dxy_now):
        dxy_30d = history['dxy'].iloc[-21] if len(history) > 21 else history['dxy'].iloc[0]
        pct = (dxy_now - dxy_30d) / dxy_30d * 100 if dxy_30d else 0
        scores['dxy'] = _linmap(pct, -3.0, 3.0, 15, -15)
    else:
        scores['dxy'] = 0.0

    rsi = row['rsi']
    dd = row['dd']
    if rsi < 30 and dd < -0.05:
        scores['rsi_dd'] = 15.0
    elif rsi > 70:
        scores['rsi_dd'] = -10.0
    else:
        scores['rsi_dd'] = _linmap(rsi, 30, 70, 10, -10)

    # Economic calendar - intentionally skipped in backtest (the forward-event
    # data was only captured today; we can't reconstruct what events were
    # scheduled at past dates t looking forward 14d). Set to 0.
    scores['econ'] = 0.0

    raw = sum(scores.values())
    normalised = raw / 1.4
    return raw, normalised, scores


def mc_at(current_price: float, vix_spot: float, vix_3m: float,
          closes_array: np.ndarray) -> dict:
    forward_vol_ann = (0.5 * vix_spot + 0.5 * vix_3m) / 100.0
    daily_vol = forward_vol_ann / math.sqrt(252)

    lookback = min(252, len(closes_array) - 1)
    log_ret = np.log(closes_array[1:] / closes_array[:-1])
    raw_drift_ann = float(log_ret[-lookback:].mean() * 252)
    drift_ann = _clip(raw_drift_ann, -0.5, 0.5)
    daily_drift = drift_ann / 252

    z = stats.t.rvs(T_DF, size=(N_PATHS_BACKTEST, HORIZON)) * T_SCALE
    log_rets = daily_drift + daily_vol * z
    paths = current_price * np.exp(np.cumsum(log_rets, axis=1))
    min_price = paths.min(axis=1)
    max_dd = min_price / current_price - 1

    return {f"-{int(d * 100)}%": float(np.mean(max_dd <= -d)) for d in DIP_LEVELS}


def analog_at(df: pd.DataFrame, t_idx: int) -> dict:
    feat_cols = ['rsi', 'dd', 'vix', 'yc']
    avail_end = t_idx - HORIZON
    if avail_end < K_ANALOGS + 10:
        return None
    avail = df[feat_cols].iloc[:avail_end]
    means = avail.mean()
    stds = avail.std().replace(0, 1.0)
    z_avail = ((avail - means) / stds).values
    current = ((df[feat_cols].iloc[t_idx] - means) / stds).values
    dists = np.linalg.norm(z_avail - current, axis=1)
    nearest = np.argsort(dists)[:K_ANALOGS]

    closes = df['close'].values
    fm = []
    for idx in nearest:
        start = closes[idx]
        window = closes[idx + 1:idx + 1 + HORIZON]
        if len(window) < HORIZON:
            continue
        fm.append(window.min() / start - 1)
    if not fm:
        return None
    fm = np.array(fm)
    return {f"-{int(d * 100)}%": float(np.mean(fm <= -d)) for d in DIP_LEVELS}


def realised_dip(df: pd.DataFrame, t_idx: int) -> float:
    closes = df['close'].values
    if t_idx + HORIZON >= len(closes):
        return None
    start = closes[t_idx]
    window = closes[t_idx + 1:t_idx + 1 + HORIZON]
    return float(window.min() / start - 1)


def run_backtest() -> Path:
    log.info("Backtest: loading signals + building aligned df...")
    signals = _load_latest_signals()
    df = build_aligned_df(signals)
    log.info(f"Aligned df: {len(df)} rows, {df.index[0].date()} -> {df.index[-1].date()}")

    start_idx = LOOKBACK_DAYS
    end_idx = len(df) - HORIZON
    n_pred = end_idx - start_idx
    if n_pred <= 0:
        raise RuntimeError(f"Not enough data: only {len(df)} rows")
    log.info(f"Backtest range: {n_pred} predictions, {N_PATHS_BACKTEST:,} MC paths/day")

    closes_array = df['close'].values
    records = []
    progress_every = max(1, n_pred // 20)

    for t_idx in range(start_idx, end_idx):
        row = df.iloc[t_idx]
        history = df.iloc[:t_idx + 1]

        raw, norm, components = composite_at(row, history)
        mc_p = mc_at(row['close'], row['vix'], row['vix3m'],
                     closes_array[:t_idx + 1])
        an_p = analog_at(df, t_idx)
        real = realised_dip(df, t_idx)

        records.append({
            "date": str(df.index[t_idx].date()),
            "composite_raw": raw,
            "composite_norm": norm,
            "components": components,
            "mc_p": mc_p,
            "analog_p": an_p,
            "realised_min_dd": real,
        })

        if (t_idx - start_idx) % progress_every == 0:
            pct = (t_idx - start_idx) / n_pred * 100
            log.info(f"  {t_idx - start_idx}/{n_pred} ({pct:.0f}%) done")

    out_path = Path(CFG['paths']['data_dir']) / "backtest_results.json"
    with open(out_path, 'w') as f:
        json.dump({
            "generated_at_utc": utcnow().isoformat(),
            "n_records": len(records),
            "config": {
                "n_paths_per_day": N_PATHS_BACKTEST,
                "k_analogs": K_ANALOGS,
                "horizon_days": HORIZON,
                "lookback_days": LOOKBACK_DAYS,
                "dip_levels": list(DIP_LEVELS),
                "econ_calendar": "skipped_in_backtest",
            },
            "records": records,
        }, f, indent=2)
    log.info(f"Saved: {out_path}")
    return out_path


if __name__ == "__main__":
    run_backtest()
