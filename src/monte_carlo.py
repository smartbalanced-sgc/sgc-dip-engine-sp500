"""VIX-blended Monte Carlo for 60-day forward S&P 500 paths.

Forward vol = w_spot * VIX + w_3m * VIX3M (defaults 0.5/0.5 to match 60d horizon).
Student-t df=4 for fat tails. Realised drift capped at +/-50% annual.
1M paths in 100k batches to bound memory.
"""

import math
import numpy as np
from scipy import stats

from data_fetcher import CFG, log

DIP_LEVELS = (0.03, 0.05, 0.07, 0.10, 0.15, 0.20)


def _annualised_realised_drift(closes: np.ndarray, lookback_days: int = 252) -> float:
    if len(closes) < 2:
        return 0.0
    lookback_days = min(lookback_days, len(closes) - 1)
    log_ret = np.log(closes[1:] / closes[:-1])
    return float(log_ret[-lookback_days:].mean() * 252)


def run_monte_carlo(current_price: float, vix_spot: float, vix_3m: float,
                    gspc_closes: np.ndarray) -> dict:
    mc = CFG['monte_carlo']
    h = mc['horizon_days']
    n = mc['n_paths']
    b = mc['batch_size']
    df = mc['student_t_df']
    drift_cap = mc['drift_cap_annual']
    w_spot = mc['vix_blend_weights']['vix_spot']
    w_3m = mc['vix_blend_weights']['vix_3m']

    forward_vol_ann = (w_spot * vix_spot + w_3m * vix_3m) / 100.0
    daily_vol = forward_vol_ann / math.sqrt(252)

    raw_drift_ann = _annualised_realised_drift(gspc_closes)
    capped_drift_ann = max(-drift_cap, min(drift_cap, raw_drift_ann))
    daily_drift = capped_drift_ann / 252

    log.info(
        f"MC: vol={forward_vol_ann:.3f}/yr ({daily_vol:.4f}/d), "
        f"drift={capped_drift_ann:+.3f}/yr (raw={raw_drift_ann:+.3f}), "
        f"{n:,} paths x {h}d, t-df={df}"
    )

    t_scale = math.sqrt((df - 2) / df)

    n_batches = max(1, n // b)
    eff_n = n_batches * b
    terminal = np.empty(eff_n, dtype=np.float64)
    min_price = np.empty(eff_n, dtype=np.float64)
    first_batch_paths = None  # Kept for per-day corridor (memory-bounded)

    for i in range(n_batches):
        z = stats.t.rvs(df, size=(b, h)) * t_scale
        log_ret = daily_drift + daily_vol * z
        paths = current_price * np.exp(np.cumsum(log_ret, axis=1))
        terminal[i * b:(i + 1) * b] = paths[:, -1]
        min_price[i * b:(i + 1) * b] = paths.min(axis=1)
        if i == 0:
            first_batch_paths = paths

    # Per-day corridor from first batch (100k paths is plenty for P10..P90)
    daily_pcts = np.percentile(first_batch_paths, [10, 30, 50, 70, 90], axis=0)
    daily_corridor = [
        {"day": int(d + 1),
         "P10": float(daily_pcts[0, d]), "P30": float(daily_pcts[1, d]),
         "P50": float(daily_pcts[2, d]), "P70": float(daily_pcts[3, d]),
         "P90": float(daily_pcts[4, d])}
        for d in range(h)
    ]

    max_drawdown = min_price / current_price - 1
    terminal_ret = terminal / current_price - 1

    return {
        "inputs": {
            "current_price": current_price,
            "vix_spot": vix_spot,
            "vix_3m": vix_3m,
            "forward_vol_ann": forward_vol_ann,
            "raw_drift_ann": raw_drift_ann,
            "capped_drift_ann": capped_drift_ann,
            "horizon_days": h,
            "n_paths": eff_n,
            "student_t_df": df,
        },
        "terminal_price": {
            f"P{p}": float(np.percentile(terminal, p)) for p in (10, 30, 50, 70, 90)
        },
        "terminal_return": {
            f"P{p}": float(np.percentile(terminal_ret, p)) for p in (10, 30, 50, 70, 90)
        },
        "min_price_corridor": {
            f"P{p}": float(np.percentile(min_price, p)) for p in (10, 30, 50, 70, 90)
        },
        "p_touch": {
            f"-{int(d * 100)}%": float(np.mean(max_drawdown <= -d)) for d in DIP_LEVELS
        },
        "daily_corridor": daily_corridor,
    }
