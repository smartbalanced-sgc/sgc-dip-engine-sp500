"""Append-only daily run log. One JSON record per line.

Keeps the dashboard's "conviction history" chart fed without re-reading
all the raw_signals files.
"""

import json
from pathlib import Path
from typing import Optional

from data_fetcher import CFG, log, utcnow


def _history_path() -> Path:
    return Path(CFG['paths'].get('history_file', 'data/conviction_history.jsonl'))


def append_run(signals: dict, models: dict) -> Path:
    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    conv = (models or {}).get('conviction') or {}
    overall = conv.get('overall') or {}
    comp = (models or {}).get('composite') or {}
    mc = (models or {}).get('monte_carlo') or {}
    mc_inputs = (mc or {}).get('inputs') or {}

    gspc_quote = signals.get('gspc_quote') or []
    vix_quote = signals.get('vix_quote') or []

    record = {
        "date": utcnow().date().isoformat(),
        "fetched_at_utc": signals.get('fetched_at_utc'),
        "gspc": float(gspc_quote[0]['price']) if gspc_quote else None,
        "vix": float(vix_quote[0]['price']) if vix_quote else None,
        "composite_normalised": comp.get('normalised_score'),
        "conviction_label": overall.get('label'),
        "conviction_dip_level": overall.get('dip_level'),
        "p_touch_mc_5": (mc.get('p_touch') or {}).get('-5%'),
        "p_touch_mc_10": (mc.get('p_touch') or {}).get('-10%'),
        "forward_vol_ann": mc_inputs.get('forward_vol_ann'),
    }

    # Dedupe: if last line has same date, overwrite it (don't double-record same day)
    today_iso = record['date']
    existing = []
    if path.exists():
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    if r.get('date') != today_iso:
                        existing.append(r)
                except json.JSONDecodeError:
                    continue

    existing.append(record)
    with open(path, 'w') as f:
        for r in existing:
            f.write(json.dumps(r) + "\n")

    log.info(f"History: {len(existing)} total records, latest {today_iso}")
    return path


def read_history(n_days: Optional[int] = None) -> list:
    path = _history_path()
    if not path.exists():
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    out.sort(key=lambda r: r.get('date', ''))
    if n_days is not None and len(out) > n_days:
        out = out[-n_days:]
    return out
