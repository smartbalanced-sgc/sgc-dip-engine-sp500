"""SPY Dip Engine - Phase 1 orchestration.

Fetches all signals, writes JSON + markdown summary, prints sanity table.
"""

import json
from pathlib import Path

from data_fetcher import fetch_all_signals, CFG, log, utcnow


def write_json(signals: dict) -> Path:
    data_dir = Path(CFG['paths']['data_dir'])
    data_dir.mkdir(parents=True, exist_ok=True)
    today = utcnow().date().strftime("%Y%m%d")
    filename = CFG['paths']['raw_signals_filename'].format(date=today)
    out_path = data_dir / filename
    with open(out_path, "w") as f:
        json.dump(signals, f, indent=2, default=str)
    return out_path


def write_latest_markdown(signals: dict, json_path: Path) -> Path:
    data_dir = Path(CFG['paths']['data_dir'])
    md_path = data_dir / CFG['paths']['latest_summary_filename']

    gspc = signals.get('gspc_quote')
    vix = signals.get('vix_quote')
    cs = signals.get('credit_spreads_hy') or []
    dx_block = signals.get('dollar_index') or {}
    dx = dx_block.get('data') or []
    dx_source = dx_block.get('source', 'unknown')
    vix_spot = signals.get('vix_spot_fred') or []
    vix_3m = signals.get('vix_3m_fred') or []

    gspc_px = gspc[0]['price'] if gspc else None
    vix_px = vix[0]['price'] if vix else None
    cs_latest = cs[-1]['value'] if cs else None
    vs_latest = vix_spot[-1]['value'] if vix_spot else None
    v3_latest = vix_3m[-1]['value'] if vix_3m else None
    ts_ratio = (v3_latest / vs_latest) if (vs_latest and v3_latest) else None
    dx_latest_row = dx[-1] if dx else None
    if isinstance(dx_latest_row, dict):
        dx_latest = dx_latest_row.get('value') or dx_latest_row.get('close')
        dx_latest_date = dx_latest_row.get('date')
    else:
        dx_latest = dx_latest_row
        dx_latest_date = None

    lines = [
        "# SPY Dip Engine - Latest Data Pull",
        "",
        f"**Fetched:** {signals.get('fetched_at_utc')}",
        "",
        "## Current spot levels",
        "",
        "| Signal | Value | Source |",
        "|---|---|---|",
        f"| ^GSPC | {gspc_px} | FMP |",
        f"| ^VIX  | {vix_px} | FMP |",
        (f"| VIX3M/VIX ratio | {ts_ratio:.3f} (>1=contango, <1=backwardation) | FRED |"
         if ts_ratio else "| VIX3M/VIX ratio | n/a | FRED |"),
        f"| HY credit spread (OAS %) | {cs_latest} | FRED BAMLH0A0HYM2 |",
        (f"| Dollar index | {dx_latest} (as of {dx_latest_date}) | {dx_source} |"
         if dx_latest_date else f"| Dollar index | {dx_latest} | {dx_source} |"),
        "",
        "## Row counts (data quality check)",
        "",
    ]
    for k, v in signals.items():
        if k in ('fetched_at_utc', 'config_version'):
            continue
        if isinstance(v, list):
            lines.append(f"- `{k}`: {len(v)} rows")
        elif isinstance(v, dict):
            if 'data' in v and isinstance(v['data'], list):
                lines.append(f"- `{k}`: {len(v['data'])} rows (source: {v.get('source')})")
            else:
                lines.append(f"- `{k}`: dict with {len(v)} keys")
        elif v is None:
            lines.append(f"- `{k}`: NULL (fetch failed)")
        else:
            lines.append(f"- `{k}`: {type(v).__name__}")

    lines += [
        "",
        "## Raw JSON",
        "",
        f"See `{json_path.name}` for the full signal dump.",
        "",
    ]
    md_path.write_text("\n".join(lines))
    return md_path


def print_summary(signals: dict, json_path: Path) -> None:
    print("\n" + "=" * 72)
    print("PHASE 1 DATA FETCH - SUMMARY")
    print("=" * 72)
    print(f"Written: {json_path}")
    print()
    print(f"{'Signal':<28} {'Rows / Status':<18} {'Notes'}")
    print("-" * 72)
    for k, v in signals.items():
        if k in ('fetched_at_utc', 'config_version'):
            continue
        if isinstance(v, list):
            status = f"{len(v):>6} rows"
            first = v[0].get('date') if v and isinstance(v[0], dict) else ''
            last = v[-1].get('date') if v and isinstance(v[-1], dict) else ''
            note = f"first={first}, last={last}" if first or last else ''
        elif isinstance(v, dict):
            if 'data' in v and isinstance(v['data'], list):
                status = f"{len(v['data']):>6} rows"
                note = f"source={v.get('source')}"
            else:
                status = f"dict ({len(v)} keys)"
                note = ''
        elif v is None:
            status = "NULL"
            note = "FETCH FAILED - investigate"
        else:
            status = type(v).__name__
            note = ''
        print(f"{k:<28} {status:<18} {note}")
    print("=" * 72)
    print("\nNext: inspect the JSON file and verify sanity before Phase 2.")


def main() -> None:
    log.info(f"SPY Dip Engine Phase 1 - {utcnow().isoformat()} UTC")
    signals = fetch_all_signals()
    json_path = write_json(signals)
    md_path = write_latest_markdown(signals, json_path)
    print_summary(signals, json_path)
    log.info(f"Markdown summary: {md_path}")


if __name__ == "__main__":
    main()
