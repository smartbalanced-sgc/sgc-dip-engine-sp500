"""SPY Dip Engine - Phase 1 data layer.

Pulls all signals from FMP, FRED, and Tiingo. No yfinance dependency
(everything runs from cloud or local with same behavior).
"""

import os
import time
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Any

import requests
import yaml


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.yaml"

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

CFG = load_config()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("spy-dip")


def _require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(
            f"Missing env var {name}. Copy .env.example to .env, fill keys, "
            f"and run: export $(grep -v '^#' .env | xargs)"
        )
    return v


def _request_with_retry(url, params=None, timeout=10, max_attempts=3,
                        backoff=(2, 4, 8), label=""):
    last_err = None
    for attempt in range(max_attempts):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 500, 502, 503, 504):
                log.warning(f"{label} HTTP {r.status_code} attempt {attempt+1}/{max_attempts}")
                if attempt < max_attempts - 1:
                    time.sleep(backoff[min(attempt, len(backoff)-1)])
                    continue
            log.error(f"{label} HTTP {r.status_code}: {r.text[:200]}")
            return r
        except Exception as e:
            last_err = e
            log.warning(f"{label} error attempt {attempt+1}/{max_attempts}: {e}")
            if attempt < max_attempts - 1:
                time.sleep(backoff[min(attempt, len(backoff)-1)])
    log.error(f"{label} failed after {max_attempts} attempts: {last_err}")
    return None


def fmp_get(endpoint: str, params: dict = None) -> Optional[Any]:
    api_key = _require_env("FMP_API_KEY")
    url = f"{CFG['fmp']['base_url']}/{endpoint}"
    full_params = {"apikey": api_key}
    if params:
        full_params.update(params)
    time.sleep(CFG['fmp']['delay_between_calls_sec'])
    r = _request_with_retry(
        url, full_params,
        timeout=CFG['fmp']['timeout_sec'],
        max_attempts=CFG['fmp']['retry_max_attempts'],
        backoff=CFG['fmp']['retry_backoff_sec'],
        label=f"FMP {endpoint}",
    )
    if r is None or r.status_code != 200:
        return None
    try:
        data = r.json()
    except Exception as e:
        log.error(f"FMP {endpoint} JSON parse error: {e}")
        return None
    if isinstance(data, list) and len(data) == 0:
        log.warning(f"FMP {endpoint} returned empty list (params={params})")
        return None
    if isinstance(data, dict) and data.get('Error Message'):
        log.error(f"FMP {endpoint} error: {data['Error Message']}")
        return None
    return data


def fred_get_series(series_id: str, start_date: str = None,
                    end_date: str = None) -> Optional[list]:
    api_key = _require_env("FRED_API_KEY")
    params = {"series_id": series_id, "api_key": api_key, "file_type": "json"}
    if start_date:
        params["observation_start"] = start_date
    if end_date:
        params["observation_end"] = end_date
    r = _request_with_retry(
        CFG['fred']['base_url'], params,
        timeout=CFG['fred']['timeout_sec'],
        max_attempts=CFG['fred']['retry_max_attempts'],
        backoff=CFG['fred']['retry_backoff_sec'],
        label=f"FRED {series_id}",
    )
    if r is None or r.status_code != 200:
        return None
    try:
        obs = r.json().get('observations', [])
    except Exception as e:
        log.error(f"FRED {series_id} JSON parse error: {e}")
        return None
    out = []
    for o in obs:
        v = o.get('value')
        if v and v != '.':
            try:
                out.append({'date': o['date'], 'value': float(v)})
            except ValueError:
                pass
    return out if out else None


def tiingo_daily(symbol: str, start_date: str,
                 end_date: str = None) -> Optional[list]:
    api_key = _require_env("TIINGO_API_KEY")
    url = f"{CFG['tiingo']['base_url']}/{symbol}/prices"
    params = {"token": api_key, "startDate": start_date}
    if end_date:
        params["endDate"] = end_date
    r = _request_with_retry(
        url, params,
        timeout=CFG['tiingo']['timeout_sec'],
        max_attempts=CFG['tiingo']['retry_max_attempts'],
        backoff=CFG['tiingo']['retry_backoff_sec'],
        label=f"Tiingo {symbol}",
    )
    if r is None or r.status_code != 200:
        return None
    try:
        return r.json()
    except Exception as e:
        log.error(f"Tiingo {symbol} JSON parse error: {e}")
        return None


def fetch_treasury_rates_paginated(years: int = 5) -> list:
    today = utcnow().date()
    start = today - timedelta(days=years * 365)
    window_days = CFG['date_ranges']['treasury_window_days']
    all_rows = []
    cursor = start
    while cursor < today:
        chunk_end = min(cursor + timedelta(days=window_days), today)
        chunk = fmp_get("treasury-rates", {
            "from": cursor.strftime("%Y-%m-%d"),
            "to": chunk_end.strftime("%Y-%m-%d"),
        })
        if chunk:
            all_rows.extend(chunk)
        cursor = chunk_end + timedelta(days=1)
    seen = set()
    out = []
    for row in all_rows:
        d = row.get('date')
        if d and d not in seen:
            seen.add(d)
            out.append(row)
    return sorted(out, key=lambda r: r['date'])


def fetch_spy_long_history(force_refresh: bool = False) -> Optional[list]:
    cache_path = Path(CFG['paths']['long_history_cache'])
    refresh_days = CFG['paths']['long_history_refresh_days']
    if not force_refresh and cache_path.exists():
        age_days = (utcnow().timestamp() - cache_path.stat().st_mtime) / 86400
        if age_days < refresh_days:
            log.info(f"Using cached SPY long history ({age_days:.0f}d old)")
            with open(cache_path) as f:
                return json.load(f)
    log.info("Pulling SPY long history from Tiingo (1993+)...")
    start = CFG['date_ranges']['tiingo_history_start']
    end = utcnow().date().strftime("%Y-%m-%d")
    data = tiingo_daily(CFG['tickers']['spy_long_history'], start, end)
    if data:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(data, f)
        log.info(f"Cached {len(data)} rows to {cache_path}")
    return data


def fetch_sector_history(sectors: list, start: str, end: str) -> Optional[list]:
    """FMP historical-sector-performance requires sector= param per call.
    Iterate the 11 sectors from the snapshot and flatten into one list,
    tagging each row with its sector name.
    """
    if not sectors:
        return None
    all_rows = []
    for s in sectors:
        chunk = fmp_get("historical-sector-performance", {
            "sector": s, "from": start, "to": end,
        })
        if chunk:
            for row in chunk:
                row.setdefault("sector", s)
            all_rows.extend(chunk)
    return all_rows if all_rows else None


def fetch_dollar_index(years: int = 5) -> dict:
    today = utcnow().date()
    start = (today - timedelta(days=years * 365)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")
    primary = fred_get_series(CFG['fred']['series']['dollar_index'], start, end)
    if primary:
        return {"source": "fred:DTWEXBGS", "data": primary}
    log.warning("FRED DTWEXBGS failed, falling back to FMP UUP")
    fallback = fmp_get("historical-price-eod/full", {
        "symbol": "UUP", "from": start, "to": end,
    })
    if fallback:
        return {"source": "fmp:UUP", "data": fallback}
    return {"source": None, "data": None}


def fetch_all_signals() -> dict:
    today = utcnow().date()
    fmp_years = CFG['date_ranges']['fmp_history_years']
    fred_years = CFG['date_ranges']['fred_history_years']
    start_5y = (today - timedelta(days=fmp_years * 365)).strftime("%Y-%m-%d")
    start_fred = (today - timedelta(days=fred_years * 365)).strftime("%Y-%m-%d")
    end_today = today.strftime("%Y-%m-%d")
    horizon_90d = (today + timedelta(days=CFG['date_ranges']['econ_calendar_days_forward'])).strftime("%Y-%m-%d")
    start_90d_back = (today - timedelta(days=CFG['date_ranges']['sector_perf_days_back'])).strftime("%Y-%m-%d")
    holiday_end = (today + timedelta(days=CFG['date_ranges']['holidays_days_forward'])).strftime("%Y-%m-%d")

    signals = {
        "fetched_at_utc": utcnow().isoformat(),
        "config_version": CFG['project']['version'],
    }

    log.info("Fetching ^GSPC current quote...")
    signals['gspc_quote'] = fmp_get("quote", {"symbol": CFG['tickers']['modelling']})
    log.info("Fetching ^VIX current quote...")
    signals['vix_quote'] = fmp_get("quote", {"symbol": CFG['tickers']['vix']})
    log.info(f"Fetching ^GSPC {fmp_years}y historical...")
    signals['gspc_history'] = fmp_get("historical-price-eod/full", {
        "symbol": CFG['tickers']['modelling'], "from": start_5y, "to": end_today,
    })
    log.info(f"Fetching ^VIX {fmp_years}y historical...")
    signals['vix_history'] = fmp_get("historical-price-eod/full", {
        "symbol": CFG['tickers']['vix'], "from": start_5y, "to": end_today,
    })
    log.info(f"Fetching treasury rates {fmp_years}y (paginated)...")
    signals['treasury_rates'] = fetch_treasury_rates_paginated(fmp_years)
    log.info("Fetching economic calendar (90d forward)...")
    signals['economic_calendar'] = fmp_get("economic-calendar", {
        "from": end_today, "to": horizon_90d,
    })
    log.info("Fetching sector performance snapshot...")
    signals['sector_snapshot'] = fmp_get("sector-performance-snapshot", {"date": end_today})
    log.info("Fetching sector performance 90d history (per-sector)...")
    sector_names = [
        r.get('sector') for r in (signals.get('sector_snapshot') or [])
        if r.get('sector')
    ]
    signals['sector_history'] = fetch_sector_history(
        sector_names, start_90d_back, end_today,
    )
    log.info("Fetching NYSE holidays (90d forward)...")
    signals['nyse_holidays'] = fmp_get("holidays-by-exchange", {
        "exchange": "NYSE", "from": end_today, "to": holiday_end,
    })
    log.info("Fetching FRED HY credit spreads (BAMLH0A0HYM2)...")
    signals['credit_spreads_hy'] = fred_get_series(
        CFG['fred']['series']['credit_spreads_hy'], start_fred, end_today,
    )
    log.info("Fetching FRED dollar index (DTWEXBGS w/ UUP fallback)...")
    signals['dollar_index'] = fetch_dollar_index(fred_years)
    log.info("Fetching FRED VIX spot (VIXCLS)...")
    signals['vix_spot_fred'] = fred_get_series(
        CFG['fred']['series']['vix_spot'], start_fred, end_today,
    )
    log.info("Fetching FRED VIX 3M (VXVCLS)...")
    signals['vix_3m_fred'] = fred_get_series(
        CFG['fred']['series']['vix_3m'], start_fred, end_today,
    )
    log.info("Fetching SPY long history (cached, refreshed quarterly)...")
    signals['spy_long_history'] = fetch_spy_long_history()

    return signals
