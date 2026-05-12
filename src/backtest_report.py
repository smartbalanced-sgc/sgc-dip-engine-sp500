"""Render docs/backtest.html from data/backtest_results.json.

Outputs: calibration curves (predicted vs realised), composite quintile
hit rates, three-method convergence agreement table, honest verdict.

Run via:
    python3 src/backtest_report.py
"""

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from data_fetcher import CFG, log

DIP_LEVELS_PCT = ('-3%', '-5%', '-7%', '-10%')
DIP_LEVELS_FLOAT = (0.03, 0.05, 0.07, 0.10)
CONVICTION_TARGETS = (0.60, 0.70, 0.80)

PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.27.0.min.js"

CSS = """
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       margin: 0; padding: 0; background: #f5f5f7; color: #1d1d1f; }
.container { max-width: 1100px; margin: 0 auto; padding: 24px; }
header { background: #1d1d1f; color: #f5f5f7; padding: 24px;
         margin: -24px -24px 24px -24px; }
header h1 { margin: 0; font-size: 28px; font-weight: 600; }
header p { margin: 4px 0 0 0; opacity: 0.7; font-size: 14px; }
header a { color: #f5f5f7; text-decoration: underline; opacity: 0.8; }
section { background: #fff; border-radius: 12px; padding: 24px;
          margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
h2 { margin: 0 0 16px 0; font-size: 20px; font-weight: 600; }
.verdict { background: #fff; border-radius: 12px; padding: 24px;
           margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,.06);
           border-left: 6px solid #1d1d1f; }
.verdict .label { font-size: 28px; font-weight: 700; margin: 8px 0; }
.verdict .label.EDGE { color: #27ae60; }
.verdict .label.MARGINAL { color: #d68000; }
.verdict .label.NONE { color: #888; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 8px 12px;
         border-bottom: 1px solid #e5e5e7; font-size: 14px; }
th { font-weight: 600; color: #666; text-transform: uppercase; font-size: 11px; }
td.num { font-variant-numeric: tabular-nums; text-align: right; }
.chart { width: 100%; height: 380px; }
.note { color: #666; font-size: 13px; margin-top: 8px; }
footer { text-align: center; color: #999; padding: 24px; font-size: 12px; }
"""


def _load_results() -> dict:
    path = Path(CFG['paths']['data_dir']) / "backtest_results.json"
    if not path.exists():
        raise RuntimeError(f"{path} not found. Run python3 src/backtest.py first.")
    with open(path) as f:
        return json.load(f)


def _build_df(records: list) -> pd.DataFrame:
    rows = []
    for r in records:
        if r.get('realised_min_dd') is None:
            continue
        row = {
            'date': r['date'],
            'composite': r['composite_norm'],
            'realised': r['realised_min_dd'],
        }
        for level in DIP_LEVELS_PCT:
            row[f'mc_{level}'] = (r.get('mc_p') or {}).get(level)
            row[f'analog_{level}'] = (r.get('analog_p') or {}).get(level)
        rows.append(row)
    return pd.DataFrame(rows)


def _calibration(predicted: pd.Series, hit: pd.Series,
                 n_buckets: int = 10) -> Optional[pd.DataFrame]:
    df = pd.DataFrame({'p': predicted, 'hit': hit.astype(int)}).dropna()
    if len(df) < 20:
        return None
    try:
        df['bucket'] = pd.qcut(df['p'], q=min(n_buckets, df['p'].nunique()),
                               duplicates='drop')
    except ValueError:
        return None
    g = df.groupby('bucket', observed=True).agg(
        predicted=('p', 'mean'),
        realised=('hit', 'mean'),
        n=('hit', 'size'),
    ).reset_index(drop=True)
    return g


def _quintile_hits(df: pd.DataFrame) -> tuple:
    qd = df.dropna(subset=['composite']).copy()
    if len(qd) < 50:
        return None, {}
    qd['q'] = pd.qcut(qd['composite'], q=5, duplicates='drop',
                      labels=['Q1 (most dip-favourable)', 'Q2', 'Q3',
                              'Q4', 'Q5 (least dip-favourable)'])
    result = {}
    base_rates = {}
    for level, fl in zip(DIP_LEVELS_PCT, DIP_LEVELS_FLOAT):
        hit = (qd['realised'] <= -fl).astype(int)
        result[level] = qd.groupby('q', observed=True).apply(
            lambda g: hit.loc[g.index].mean()
        )
        base_rates[level] = float(hit.mean())
    return result, base_rates


def _convergence_table(df: pd.DataFrame) -> list:
    rows = []
    for thresh in CONVICTION_TARGETS:
        for level, fl in zip(DIP_LEVELS_PCT, DIP_LEVELS_FLOAT):
            mc = df[f'mc_{level}']
            an = df[f'analog_{level}']
            mask = (mc >= thresh) & (an >= thresh)
            n = int(mask.sum())
            base = float((df['realised'] <= -fl).mean())
            if n == 0:
                hit_rate = None
            else:
                hit_rate = float(((df['realised'] <= -fl) & mask).sum() / n)
            rows.append({
                'conviction': thresh,
                'dip': level,
                'n_signals': n,
                'hit_rate': hit_rate,
                'base_rate': base,
            })
    return rows


def _verdict(df: pd.DataFrame, base_rates: dict) -> tuple:
    q_neg = df[df['composite'] <= -25]
    q_pos = df[df['composite'] >= 25]
    fl = 0.05
    if len(q_neg) >= 10 and len(q_pos) >= 10 and base_rates.get('-5%', 0) > 0:
        hit_neg = float((q_neg['realised'] <= -fl).mean())
        hit_pos = float((q_pos['realised'] <= -fl).mean())
        base = base_rates['-5%']
        lift = hit_neg / base
        if lift > 1.3:
            label = "EDGE"
            text = (f"Composite below -25 (n={len(q_neg)}) saw -5% dip hit rate "
                    f"<b>{hit_neg:.1%}</b> vs base rate <b>{base:.1%}</b> "
                    f"(lift <b>{lift:.2f}x</b>). Above +25 (n={len(q_pos)}) saw "
                    f"{hit_pos:.1%}. Genuine edge present at the extremes.")
        elif lift > 1.1:
            label = "MARGINAL"
            text = (f"Composite below -25 (n={len(q_neg)}) saw -5% dip hit rate "
                    f"<b>{hit_neg:.1%}</b> vs base rate <b>{base:.1%}</b> "
                    f"(lift <b>{lift:.2f}x</b>). Marginal edge - within noise band "
                    f"of a 5y sample. Treat conviction signals with caution.")
        else:
            label = "NONE"
            text = (f"Composite below -25 (n={len(q_neg)}) saw -5% dip hit rate "
                    f"<b>{hit_neg:.1%}</b> vs base rate <b>{base:.1%}</b> "
                    f"(lift <b>{lift:.2f}x</b>). No edge above noise. "
                    f"Stick with vanilla monthly DCA.")
        return label, text, hit_neg, hit_pos, base, lift, len(q_neg), len(q_pos)
    return "NONE", "Insufficient sample at composite extremes for verdict.", \
        None, None, None, None, len(q_neg), len(q_pos)


def _calibration_plot(calib_mc: dict, calib_an: dict) -> str:
    traces = []
    # Diagonal reference
    traces.append({
        "x": [0, 1], "y": [0, 1], "name": "Perfect calibration",
        "type": "scatter", "mode": "lines",
        "line": {"dash": "dot", "width": 1, "color": "#999"},
    })
    for level in DIP_LEVELS_PCT:
        cm = calib_mc.get(level)
        if cm is not None and not cm.empty:
            traces.append({
                "x": cm['predicted'].tolist(),
                "y": cm['realised'].tolist(),
                "name": f"MC {level}", "type": "scatter",
                "mode": "lines+markers",
            })
        ca = calib_an.get(level)
        if ca is not None and not ca.empty:
            traces.append({
                "x": ca['predicted'].tolist(),
                "y": ca['realised'].tolist(),
                "name": f"Analog {level}", "type": "scatter",
                "mode": "lines+markers",
                "line": {"dash": "dash"},
            })
    layout = {
        "margin": {"l": 60, "r": 20, "t": 20, "b": 40},
        "xaxis": {"title": "Predicted P(touch)", "range": [0, 1], "tickformat": ".0%"},
        "yaxis": {"title": "Realised hit rate", "range": [0, 1], "tickformat": ".0%"},
        "hovermode": "closest",
        "legend": {"orientation": "h", "y": -0.2},
    }
    return (f"Plotly.newPlot('calib-chart', {json.dumps(traces)}, "
            f"{json.dumps(layout)}, {{responsive: true}});")


def _quintile_plot(quintile_hits: dict, base_rates: dict) -> str:
    if not quintile_hits:
        return ""
    traces = []
    for level in DIP_LEVELS_PCT:
        if level not in quintile_hits:
            continue
        s = quintile_hits[level]
        traces.append({
            "x": [str(q) for q in s.index],
            "y": s.values.tolist(),
            "name": f"Hit rate {level}",
            "type": "bar",
        })
    layout = {
        "margin": {"l": 60, "r": 20, "t": 20, "b": 80},
        "yaxis": {"title": "Forward-60d hit rate", "tickformat": ".0%"},
        "barmode": "group",
        "hovermode": "x unified",
        "legend": {"orientation": "h", "y": -0.3},
    }
    return (f"Plotly.newPlot('quintile-chart', {json.dumps(traces)}, "
            f"{json.dumps(layout)}, {{responsive: true}});")


def render_report() -> Path:
    raw = _load_results()
    records = raw['records']
    log.info(f"Backtest: {len(records)} records, "
             f"config={raw.get('config', {})}")
    df = _build_df(records)
    log.info(f"Usable rows after dropping NaN realised: {len(df)}")

    # Calibration per dip level per method
    calib_mc = {}
    calib_an = {}
    for level in DIP_LEVELS_PCT:
        fl = float(level.rstrip('%')) / 100
        hit = df['realised'] <= -fl
        calib_mc[level] = _calibration(df[f'mc_{level}'], hit)
        calib_an[level] = _calibration(df[f'analog_{level}'], hit)

    quintile_hits, base_rates = _quintile_hits(df)
    conv_rows = _convergence_table(df)
    v_label, v_text, hit_neg, hit_pos, base5, lift, n_neg, n_pos = _verdict(df, base_rates)

    # Render tables
    base_table_rows = "".join(
        f"<tr><td>{lvl}</td><td class='num'>{base_rates.get(lvl, 0):.1%}</td></tr>"
        for lvl in DIP_LEVELS_PCT
    )
    base_table = (
        "<table><thead><tr><th>Dip</th><th>Base rate (any 60d window)</th></tr></thead>"
        f"<tbody>{base_table_rows}</tbody></table>"
    )

    # Quintile table
    quintile_table = ""
    if quintile_hits:
        header_cells = "<th>Quintile</th>" + "".join(
            f"<th>{lvl}</th>" for lvl in DIP_LEVELS_PCT
        )
        rows_html = []
        index = list(next(iter(quintile_hits.values())).index)
        for q in index:
            cells = [f"<td>{q}</td>"]
            for lvl in DIP_LEVELS_PCT:
                v = quintile_hits[lvl].get(q)
                cells.append(f"<td class='num'>{v:.1%}</td>" if v is not None else "<td>-</td>")
            rows_html.append(f"<tr>{''.join(cells)}</tr>")
        base_row_cells = ["<td><strong>Base rate</strong></td>"]
        for lvl in DIP_LEVELS_PCT:
            base_row_cells.append(
                f"<td class='num'><strong>{base_rates.get(lvl, 0):.1%}</strong></td>"
            )
        rows_html.append(f"<tr>{''.join(base_row_cells)}</tr>")
        quintile_table = (
            f"<table><thead><tr>{header_cells}</tr></thead>"
            f"<tbody>{''.join(rows_html)}</tbody></table>"
        )

    # Convergence table
    conv_rows_html = []
    for r in conv_rows:
        hit_cell = (f"<td class='num'>{r['hit_rate']:.1%}</td>"
                    if r['hit_rate'] is not None else "<td>-</td>")
        lift_cell = "-"
        if r['hit_rate'] is not None and r['base_rate'] > 0:
            lift_cell = f"{r['hit_rate'] / r['base_rate']:.2f}x"
        conv_rows_html.append(
            f"<tr><td>{int(r['conviction'] * 100)}%</td>"
            f"<td>{r['dip']}</td>"
            f"<td class='num'>{r['n_signals']}</td>"
            f"{hit_cell}"
            f"<td class='num'>{r['base_rate']:.1%}</td>"
            f"<td class='num'>{lift_cell}</td></tr>"
        )
    conv_table = (
        "<table><thead><tr><th>Conviction</th><th>Dip</th><th>Signals</th>"
        "<th>Hit rate</th><th>Base rate</th><th>Lift</th></tr></thead>"
        f"<tbody>{''.join(conv_rows_html)}</tbody></table>"
    )

    plots = [_calibration_plot(calib_mc, calib_an)]
    if quintile_hits:
        plots.append(_quintile_plot(quintile_hits, base_rates))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SPY Dip Engine - Backtest</title>
<script src="{PLOTLY_CDN}"></script>
<style>{CSS}</style>
</head>
<body>
<header>
  <div class="container">
    <h1>SPY Dip Engine - Backtest</h1>
    <p>Walk-forward over {len(records)} aligned trading days
       ({raw.get('config', {}).get('n_paths_per_day', '?'):,} MC paths/day,
       k={raw.get('config', {}).get('k_analogs', '?')} analogs).
       &nbsp;&middot;&nbsp; <a href="index.html">&larr; Back to live dashboard</a>
    </p>
  </div>
</header>
<div class="container">

  <div class="verdict">
    <div style="color:#666;font-size:14px">Honest verdict</div>
    <div class="label {v_label}">{v_label}</div>
    <div>{v_text}</div>
  </div>

  <section>
    <h2>Base rates (sanity)</h2>
    {base_table}
    <p class="note">How often did SPY touch each dip threshold within any forward 60d window in the backtest sample? These are the "do nothing" baselines.</p>
  </section>

  <section>
    <h2>Composite score by quintile</h2>
    {quintile_table}
    <div id="quintile-chart" class="chart"></div>
    <p class="note">Days bucketed by composite score (Q1 = most dip-favourable, Q5 = most complacent). If the composite has edge, Q1 should show notably higher dip hit rates than Q5 and than the base rate.</p>
  </section>

  <section>
    <h2>Calibration (predicted vs realised)</h2>
    <div id="calib-chart" class="chart"></div>
    <p class="note">Each method outputs a probability P(touch dip in 60d). We bucket predictions into deciles and plot the bucket mean predicted vs the bucket realised hit rate. Points on the dotted diagonal = well calibrated. Above = under-predicts; below = over-predicts.</p>
  </section>

  <section>
    <h2>Three-method convergence agreement</h2>
    {conv_table}
    <p class="note">Rows show: when BOTH MC and analog gave a probability above the conviction threshold for a given dip level, how often did the dip actually occur? Lift &gt; 1.0 means signals were more likely to precede dips than the base rate.</p>
  </section>

  <section>
    <h2>Method caveats</h2>
    <ul>
      <li>Economic calendar component intentionally skipped (forward-event data
          only captured today; cannot reconstruct historical look-forward).</li>
      <li>Sample is ~5y of aligned data &mdash; ~2-3 distinct macro regimes only.
          Statistical power is modest. Phase 4b can extend via long FRED treasury history.</li>
      <li>MC backtest uses {raw.get('config', {}).get('n_paths_per_day', '?'):,} paths/day
          (vs 1M in production) for speed. Probability estimates noisier in tails.</li>
      <li>Analog matching excludes the forward 60d window to avoid look-ahead.</li>
    </ul>
  </section>

  <footer>
    Generated: {raw.get('generated_at_utc', '?')}<br>
    Source: github.com/smartbalanced-sgc/sgc-dip-engine-sp500
  </footer>

</div>
<script>
{chr(10).join(plots)}
</script>
</body>
</html>"""

    out_path = Path("docs/backtest.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    log.info(f"Backtest report: {out_path}")
    return out_path


if __name__ == "__main__":
    render_report()
