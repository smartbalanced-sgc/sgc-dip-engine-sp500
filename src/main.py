"""SPY Dip Engine - orchestration.

Phase 1: fetch all signals, write JSON + markdown summary.
Phase 2: run Monte Carlo, historical analog matching, composite score,
         and three-method convergence check. Emit conviction JSON + extended md.
"""

import json
from pathlib import Path

import numpy as np

from data_fetcher import fetch_all_signals, CFG, log, utcnow
from monte_carlo import run_monte_carlo
from historical_analog import find_analogs
from composite_score import compute_composite
from conviction import assess as assess_conviction


def write_json(obj: dict, filename: str) -> Path:
    data_dir = Path(CFG['paths']['data_dir'])
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / filename
    with open(out_path, "w") as f:
        json.dump(obj, f, indent=2, default=str)
    return out_path


def run_models(signals: dict) -> dict:
    gspc_quote = signals.get('gspc_quote') or []
    current_price = float(gspc_quote[0]['price']) if gspc_quote else None

    vix_quote = signals.get('vix_quote') or []
    vix_spot = float(vix_quote[0]['price']) if vix_quote else None

    vix_3m_fred = signals.get('vix_3m_fred') or []
    vix_3m = float(vix_3m_fred[-1]['value']) if vix_3m_fred else None

    gspc_hist = signals.get('gspc_history') or []
    closes = np.array(
        [float(r['close']) for r in sorted(gspc_hist, key=lambda r: r['date'])],
        dtype=np.float64,
    )

    mc = None
    if current_price and vix_spot and vix_3m and len(closes) > 1:
        log.info("Running Monte Carlo...")
        mc = run_monte_carlo(current_price, vix_spot, vix_3m, closes)
    else:
        log.warning("MC skipped: missing price/vix/closes")

    log.info("Computing historical analog matches...")
    analog = find_analogs(signals)

    log.info("Computing macro composite score...")
    composite = compute_composite(signals)

    log.info("Three-method convergence assessment...")
    conv = assess_conviction(mc, analog, composite)

    return {
        "current_price": current_price,
        "monte_carlo": mc,
        "historical_analog": analog,
        "composite": composite,
        "conviction": conv,
    }


def write_latest_markdown(signals: dict, models: dict,
                          raw_path: Path, models_path: Path) -> Path:
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
        "# SPY Dip Engine - Latest",
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
    ]

    conv = (models or {}).get('conviction') or {}
    overall = conv.get('overall') or {}
    comp = (models or {}).get('composite') or {}
    mc = (models or {}).get('monte_carlo') or {}
    an = (models or {}).get('historical_analog') or {}

    lines += [
        "## Phase 2 - Conviction",
        "",
        f"**Headline:** {overall.get('label')} "
        f"at dip level {overall.get('dip_level')} "
        f"(composite={overall.get('composite_normalised'):+.1f}, "
        f"{overall.get('composite_interpretation')})",
        "",
        "### Probability of touching dip within 60d",
        "",
        "| Dip | Monte Carlo | Historical analog | Min-of-two | Label |",
        "|---|---|---|---|---|",
    ]
    for level, e in (conv.get('by_dip_level') or {}).items():
        mc_p = f"{e['mc_p']:.1%}" if e.get('mc_p') is not None else "n/a"
        an_p = f"{e['analog_p']:.1%}" if e.get('analog_p') is not None else "n/a"
        mn = f"{e['min_of_two']:.1%}"
        lines.append(f"| {level} | {mc_p} | {an_p} | {mn} | {e['label']} |")

    if conv.get('warnings'):
        lines += ["", "### Warnings", ""]
        for w in conv['warnings']:
            lines.append(f"- {w}")

    if comp.get('components'):
        lines += ["", "## Composite score breakdown", "",
                  "| Component | Score | Note |", "|---|---|---|"]
        for k, v in comp['components'].items():
            lines.append(f"| {k} | {v['score']:+.1f} | {v['note']} |")
        lines.append(f"| **TOTAL (raw)** | **{comp.get('raw_total'):+.1f}** | "
                     f"normalised={comp.get('normalised_score'):+.1f} |")

    if mc.get('terminal_price'):
        tp = mc['terminal_price']
        mn = mc.get('min_price_corridor', {})
        lines += [
            "", "## Monte Carlo corridor (60d, terminal price)", "",
            f"P10={tp.get('P10'):.0f} | P30={tp.get('P30'):.0f} | "
            f"P50={tp.get('P50'):.0f} | P70={tp.get('P70'):.0f} | "
            f"P90={tp.get('P90'):.0f}",
            "",
            "## Monte Carlo min-price corridor (worst touch over 60d)",
            "",
            f"P10={mn.get('P10'):.0f} | P30={mn.get('P30'):.0f} | "
            f"P50={mn.get('P50'):.0f} | P70={mn.get('P70'):.0f} | "
            f"P90={mn.get('P90'):.0f}",
        ]

    if an and an.get('k_matches'):
        cf = an.get('current_fingerprint') or {}
        lines += [
            "",
            f"## Historical analog (k={an['k_matches']} of "
            f"{an['sample_size_total']} aligned days)",
            "",
            f"Fingerprint: RSI={cf.get('rsi'):.0f}, "
            f"DD52w={cf.get('drawdown_52w'):.2%}, "
            f"VIX={cf.get('vix'):.2f}, "
            f"2-10y spread={cf.get('yc_spread'):.2f}",
        ]

    lines += [
        "",
        "## Raw data",
        "",
        f"- Signals: `{raw_path.name}`",
        f"- Models:  `{models_path.name}`",
        "",
    ]
    md_path.write_text("\n".join(lines))
    return md_path


def print_summary(signals: dict, models: dict, raw_path: Path,
                  models_path: Path) -> None:
    print("\n" + "=" * 72)
    print("PHASE 1+2 RUN - SUMMARY")
    print("=" * 72)
    print(f"Raw signals: {raw_path}")
    print(f"Models:      {models_path}")
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

    print("\n" + "=" * 72)
    print("PHASE 2 - CONVICTION")
    print("=" * 72)
    conv = (models or {}).get('conviction') or {}
    overall = conv.get('overall') or {}
    comp = (models or {}).get('composite') or {}
    print(f"Headline: {overall.get('label')} "
          f"@ dip {overall.get('dip_level')}")
    print(f"Composite normalised: {overall.get('composite_normalised'):+.1f} "
          f"({comp.get('interpretation')})")
    print()
    print(f"{'Dip':<6} {'MC':<8} {'Analog':<8} {'Min':<8} {'Label'}")
    print("-" * 50)
    for level, e in (conv.get('by_dip_level') or {}).items():
        mc_p = f"{e['mc_p']:.1%}" if e.get('mc_p') is not None else "n/a"
        an_p = f"{e['analog_p']:.1%}" if e.get('analog_p') is not None else "n/a"
        mn = f"{e['min_of_two']:.1%}"
        print(f"{level:<6} {mc_p:<8} {an_p:<8} {mn:<8} {e['label']}")
    if conv.get('warnings'):
        print()
        for w in conv['warnings']:
            print(f"  ! {w}")
    print("=" * 72)


def main() -> None:
    log.info(f"SPY Dip Engine - {utcnow().isoformat()} UTC")
    signals = fetch_all_signals()
    today = utcnow().date().strftime("%Y%m%d")
    raw_path = write_json(
        signals,
        CFG['paths']['raw_signals_filename'].format(date=today),
    )
    models = run_models(signals)
    models_path = write_json(models, f"models_{today}.json")
    md_path = write_latest_markdown(signals, models, raw_path, models_path)
    print_summary(signals, models, raw_path, models_path)
    log.info(f"Markdown summary: {md_path}")


if __name__ == "__main__":
    main()
