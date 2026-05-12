"""Static HTML dashboard generator. Renders docs/index.html.

Self-contained: Plotly loaded from CDN, no Python deps beyond stdlib.
Designed to be served by GitHub Pages from the docs/ folder.
"""

import json
from pathlib import Path
from typing import Optional

from data_fetcher import CFG, log
from output_formatter import dip_target_table

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
.headline { background: #fff; border-radius: 12px; padding: 24px;
            margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.headline .label { font-size: 36px; font-weight: 700; margin: 8px 0; }
.headline .label.NONE { color: #888; }
.headline .label.MODERATE { color: #d68000; }
.headline .label.STRONG { color: #d63031; }
.headline .label.EXTREME { color: #8e0000; }
.headline .sub { color: #666; font-size: 14px; }
section { background: #fff; border-radius: 12px; padding: 24px;
          margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
h2 { margin: 0 0 16px 0; font-size: 20px; font-weight: 600; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 8px 12px;
         border-bottom: 1px solid #e5e5e7; font-size: 14px; }
th { font-weight: 600; color: #666; text-transform: uppercase; font-size: 11px; }
td.num { font-variant-numeric: tabular-nums; text-align: right; }
.warn { background: #fff8e1; border-left: 4px solid #f5a623;
        padding: 12px 16px; margin-top: 12px; border-radius: 4px; font-size: 14px; }
.divergence { background: #ffe9e9; border-left: 4px solid #d63031; }
footer { text-align: center; color: #999; padding: 24px; font-size: 12px; }
.chart { width: 100%; height: 420px; }
"""


def _fmt_pct(p):
    if p is None:
        return "n/a"
    return f"{p:.1%}"


def _fmt_money(x, places=0):
    if x is None:
        return "n/a"
    return f"{x:,.{places}f}"


def _corridor_plot_data(daily_corridor: list, current_price: float) -> dict:
    days = [d['day'] for d in daily_corridor]
    p10 = [d['P10'] for d in daily_corridor]
    p30 = [d['P30'] for d in daily_corridor]
    p50 = [d['P50'] for d in daily_corridor]
    p70 = [d['P70'] for d in daily_corridor]
    p90 = [d['P90'] for d in daily_corridor]
    return {
        "data": [
            {"x": days, "y": p90, "name": "P90", "type": "scatter",
             "mode": "lines", "line": {"width": 0}, "showlegend": False},
            {"x": days, "y": p70, "name": "P70-P90", "type": "scatter",
             "mode": "lines", "fill": "tonexty",
             "fillcolor": "rgba(46,204,113,0.15)", "line": {"width": 0}},
            {"x": days, "y": p50, "name": "P50-P70", "type": "scatter",
             "mode": "lines", "fill": "tonexty",
             "fillcolor": "rgba(46,204,113,0.30)", "line": {"width": 1, "color": "#27ae60"}},
            {"x": days, "y": p30, "name": "P30-P50", "type": "scatter",
             "mode": "lines", "fill": "tonexty",
             "fillcolor": "rgba(231,76,60,0.30)", "line": {"width": 0}},
            {"x": days, "y": p10, "name": "P10-P30", "type": "scatter",
             "mode": "lines", "fill": "tonexty",
             "fillcolor": "rgba(231,76,60,0.15)", "line": {"width": 0}},
            {"x": [0, days[-1]], "y": [current_price, current_price],
             "name": f"Spot {current_price:.0f}",
             "type": "scatter", "mode": "lines",
             "line": {"dash": "dash", "width": 2, "color": "#1d1d1f"}},
        ],
        "layout": {
            "margin": {"l": 60, "r": 20, "t": 20, "b": 40},
            "xaxis": {"title": "Days forward"},
            "yaxis": {"title": "^GSPC price"},
            "hovermode": "x unified",
            "showlegend": True,
            "legend": {"orientation": "h", "y": -0.2},
        },
    }


def _history_plot_data(history: list) -> Optional[dict]:
    if not history:
        return None
    dates = [r.get('date') for r in history]
    composite = [r.get('composite_normalised') for r in history]
    mc5 = [r.get('p_touch_mc_5') for r in history]
    return {
        "data": [
            {"x": dates, "y": composite, "name": "Composite (-100..+100)",
             "yaxis": "y", "type": "scatter", "mode": "lines+markers",
             "line": {"color": "#1d1d1f"}},
            {"x": dates, "y": mc5, "name": "P(touch -5% in 60d)",
             "yaxis": "y2", "type": "scatter", "mode": "lines+markers",
             "line": {"color": "#d63031"}},
        ],
        "layout": {
            "margin": {"l": 60, "r": 60, "t": 20, "b": 40},
            "yaxis": {"title": "Composite", "side": "left"},
            "yaxis2": {"title": "P(-5% in 60d)", "side": "right",
                       "overlaying": "y", "tickformat": ".0%"},
            "hovermode": "x unified",
            "legend": {"orientation": "h", "y": -0.2},
        },
    }


def _spot_table(signals: dict) -> str:
    gspc = (signals.get('gspc_quote') or [{}])[0].get('price')
    vix = (signals.get('vix_quote') or [{}])[0].get('price')
    cs = signals.get('credit_spreads_hy') or []
    dx_block = signals.get('dollar_index') or {}
    dx = dx_block.get('data') or []
    vs = signals.get('vix_spot_fred') or []
    v3 = signals.get('vix_3m_fred') or []
    ratio = (v3[-1]['value'] / vs[-1]['value']) if (vs and v3) else None
    dx_latest = None
    if dx:
        last = dx[-1]
        dx_latest = last.get('value') if isinstance(last, dict) else last

    dx_date = None
    if dx and isinstance(dx[-1], dict):
        dx_date = dx[-1].get('date')
    dx_cell = _fmt_money(dx_latest, 2)
    if dx_date:
        dx_cell = f"{dx_cell} <span style='color:#999;font-size:12px'>({dx_date})</span>"

    rows = [
        ("^GSPC", _fmt_money(gspc, 2), "FMP"),
        ("^VIX", _fmt_money(vix, 2), "FMP"),
        ("VIX3M/VIX", f"{ratio:.3f}" if ratio else "n/a", "FRED"),
        ("HY OAS %", _fmt_money(cs[-1]['value'], 2) if cs else "n/a", "FRED"),
        ("Dollar index", dx_cell, dx_block.get('source', '')),
    ]
    body = "".join(f"<tr><td>{a}</td><td class='num'>{b}</td><td>{c}</td></tr>"
                   for a, b, c in rows)
    return ("<table><thead><tr><th>Signal</th><th>Value</th><th>Source</th>"
            f"</tr></thead><tbody>{body}</tbody></table>")


def _conviction_table(conv: dict) -> str:
    rows = (conv or {}).get('by_dip_level') or {}
    body_rows = []
    for level, e in rows.items():
        body_rows.append(
            f"<tr><td>{level}</td><td class='num'>{_fmt_pct(e.get('mc_p'))}</td>"
            f"<td class='num'>{_fmt_pct(e.get('analog_p'))}</td>"
            f"<td class='num'>{_fmt_pct(e.get('min_of_two'))}</td>"
            f"<td>{e.get('label')}</td></tr>"
        )
    body = "".join(body_rows) or "<tr><td colspan='5'>no data</td></tr>"
    return ("<table><thead><tr><th>Dip</th><th>MC</th><th>Analog</th>"
            f"<th>Min-of-two</th><th>Label</th></tr></thead><tbody>{body}</tbody></table>")


def _dip_targets_table(mc: dict, an: dict, current_price: float,
                       levels=(0.60, 0.70, 0.80)) -> str:
    rows = dip_target_table((mc or {}).get('p_touch'),
                            (an or {}).get('p_touch'),
                            current_price, levels)
    any_target = any(r['mc_dip'] or r['analog_dip'] for r in rows)
    if not any_target:
        return ("<div class='warn'>No dip threshold clears 60% conviction "
                "under either method today. Regime does not support a "
                "lean-in DCA signal &mdash; standard monthly cadence "
                "recommended.</div>")
    body_rows = []
    for r in rows:
        body_rows.append(
            f"<tr><td>{int(r['conviction'] * 100)}%</td>"
            f"<td>{r['mc_dip'] or '-'}</td>"
            f"<td class='num'>{_fmt_money(r['mc_price'])}</td>"
            f"<td>{r['analog_dip'] or '-'}</td>"
            f"<td class='num'>{_fmt_money(r['analog_price'])}</td></tr>"
        )
    body = "".join(body_rows)
    return ("<table><thead><tr><th>Conviction</th>"
            "<th>MC dip</th><th>MC price</th>"
            f"<th>Analog dip</th><th>Analog price</th></tr></thead><tbody>{body}</tbody></table>")


def _composite_table(composite: dict) -> str:
    components = (composite or {}).get('components') or {}
    rows = []
    for k, v in components.items():
        rows.append(
            f"<tr><td>{k}</td><td class='num'>{v['score']:+.1f}</td>"
            f"<td>{v['note']}</td></tr>"
        )
    if not rows:
        return "<p>no data</p>"
    rows.append(
        f"<tr><td><strong>TOTAL (normalised)</strong></td>"
        f"<td class='num'><strong>{composite.get('normalised_score'):+.1f}</strong></td>"
        f"<td>{composite.get('interpretation', '')}</td></tr>"
    )
    body = "".join(rows)
    return ("<table><thead><tr><th>Component</th><th>Score</th>"
            f"<th>Note</th></tr></thead><tbody>{body}</tbody></table>")


def _warnings_block(conv: dict) -> str:
    ws = (conv or {}).get('warnings') or []
    if not ws:
        return ""
    items = "".join(f"<div class='warn divergence'>{w}</div>" for w in ws)
    return items


def render_dashboard(signals: dict, models: dict, history: list,
                     out_path: Optional[Path] = None) -> Path:
    out_path = out_path or Path(CFG.get('dashboard', {}).get('html_path',
                                                             'docs/index.html'))
    out_path.parent.mkdir(parents=True, exist_ok=True)

    conv = (models or {}).get('conviction') or {}
    overall = conv.get('overall') or {}
    comp = (models or {}).get('composite') or {}
    mc = (models or {}).get('monte_carlo') or {}
    an = (models or {}).get('historical_analog') or {}
    current_price = (models or {}).get('current_price') or 0

    label = overall.get('label') or 'NONE'
    dip_level = overall.get('dip_level') or '-'
    composite_norm = overall.get('composite_normalised') or 0
    interp = overall.get('composite_interpretation') or comp.get('interpretation') or ''

    corridor_plot = (_corridor_plot_data(mc['daily_corridor'], current_price)
                     if mc.get('daily_corridor') and current_price else None)
    history_plot = _history_plot_data(history)

    fetched = signals.get('fetched_at_utc', '')

    plot_scripts = []
    if corridor_plot:
        plot_scripts.append(
            f"Plotly.newPlot('corridor-chart', {json.dumps(corridor_plot['data'])}, "
            f"{json.dumps(corridor_plot['layout'])}, {{responsive: true}});"
        )
    if history_plot:
        plot_scripts.append(
            f"Plotly.newPlot('history-chart', {json.dumps(history_plot['data'])}, "
            f"{json.dumps(history_plot['layout'])}, {{responsive: true}});"
        )

    history_section = ""
    if history_plot:
        history_section = (
            f"<section><h2>Conviction History ({len(history)} runs)</h2>"
            f"<div id='history-chart' class='chart'></div></section>"
        )

    corridor_section = ""
    if corridor_plot:
        corridor_section = (
            f"<section><h2>60-Day Forward Corridor (Monte Carlo)</h2>"
            f"<div id='corridor-chart' class='chart'></div></section>"
        )

    fingerprint = (an or {}).get('current_fingerprint') or {}
    fingerprint_text = ""
    if fingerprint:
        fingerprint_text = (
            f"<p style='color:#666;font-size:13px;margin-top:8px'>"
            f"Today's fingerprint: RSI={fingerprint.get('rsi'):.0f}, "
            f"DD52w={fingerprint.get('drawdown_52w'):.2%}, "
            f"VIX={fingerprint.get('vix'):.2f}, "
            f"2-10y={fingerprint.get('yc_spread'):.2f}. "
            f"Matched against {an.get('k_matches')} of "
            f"{an.get('sample_size_total')} aligned historical days.</p>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SPY Dip Engine</title>
<script src="{PLOTLY_CDN}"></script>
<style>{CSS}</style>
</head>
<body>
<header>
  <div class="container">
    <h1>SPY Dip Engine</h1>
    <p>S&amp;P 500 60-day dip prediction. NOT for active trading. Last update: {fetched}</p>
  </div>
</header>
<div class="container">

  <div class="headline">
    <div class="sub">Headline conviction</div>
    <div class="label {label}">{label}</div>
    <div class="sub">at dip level <strong>{dip_level}</strong> &middot;
      composite <strong>{composite_norm:+.1f}</strong>
      ({interp})</div>
    {_warnings_block(conv)}
  </div>

  <section>
    <h2>Current spot levels</h2>
    {_spot_table(signals)}
  </section>

  {corridor_section}

  <section>
    <h2>Dip targets by conviction</h2>
    {_dip_targets_table(mc, an, current_price)}
    <p style="color:#666;font-size:13px;margin-top:8px">
      Deepest dip threshold whose 60-day touch probability meets each conviction level.
      MC = stochastic Student-t Monte Carlo. Analog = empirical hit rate of k-nearest
      historical regime matches.
    </p>
  </section>

  <section>
    <h2>Three-method convergence</h2>
    {_conviction_table(conv)}
    {fingerprint_text}
  </section>

  <section>
    <h2>Macro composite breakdown</h2>
    {_composite_table(comp)}
  </section>

  {history_section}

  <footer>
    Built from FMP + FRED + Tiingo. Modelling vehicle ^GSPC, execution VUAA.L.
    Source: github.com/smartbalanced-sgc/sgc-dip-engine-sp500
  </footer>

</div>
<script>
{chr(10).join(plot_scripts)}
</script>
</body>
</html>"""

    out_path.write_text(html)
    log.info(f"Dashboard: {out_path}")
    return out_path
