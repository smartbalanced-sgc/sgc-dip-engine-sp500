"""Three-method convergence test.

Takes Monte Carlo + historical analog + composite score outputs. Returns
conviction label per dip threshold + divergence warnings when methods
disagree by more than the configured threshold.
"""

from data_fetcher import CFG

DIP_LEVELS = ('-3%', '-5%', '-7%', '-10%', '-15%', '-20%')
DEEPEST_FIRST = tuple(reversed(DIP_LEVELS))


def _label_from_prob(p, thresholds):
    if p is None:
        return "UNKNOWN"
    if p >= thresholds['extreme']:
        return "EXTREME"
    if p >= thresholds['strong']:
        return "STRONG"
    if p >= thresholds['moderate']:
        return "MODERATE"
    return "NONE"


def assess(mc: dict, analog: dict, composite: dict) -> dict:
    thresholds = CFG['conviction']['thresholds']
    div_warn = CFG['conviction']['divergence_warn_threshold']

    mc_p = (mc or {}).get('p_touch') or {}
    an_p = (analog or {}).get('p_touch') or {}

    by_level = {}
    warnings = []
    for level in DIP_LEVELS:
        mc_v = mc_p.get(level)
        an_v = an_p.get(level)
        if mc_v is None and an_v is None:
            continue
        present = [v for v in (mc_v, an_v) if v is not None]
        min_of_two = min(present)
        max_of_two = max(present)
        by_level[level] = {
            "mc_p": mc_v,
            "analog_p": an_v,
            "min_of_two": min_of_two,
            "max_of_two": max_of_two,
            "label": _label_from_prob(min_of_two, thresholds),
        }
        if mc_v is not None and an_v is not None and abs(mc_v - an_v) > div_warn:
            warnings.append(
                f"DIVERGENCE at {level}: MC={mc_v:.1%}, analog={an_v:.1%} "
                f"(spread {abs(mc_v - an_v):.1%} > {div_warn:.0%})"
            )

    # Headline: deepest dip level whose min_of_two clears the strong threshold,
    # falling back to moderate.
    headline_label = "NONE"
    headline_level = None
    for level in DEEPEST_FIRST:
        if level not in by_level:
            continue
        v = by_level[level]['min_of_two']
        if v >= thresholds['extreme']:
            headline_label, headline_level = "EXTREME", level
            break
        if v >= thresholds['strong']:
            headline_label, headline_level = "STRONG", level
            break
    if headline_level is None:
        for level in DEEPEST_FIRST:
            if level not in by_level:
                continue
            if by_level[level]['min_of_two'] >= thresholds['moderate']:
                headline_label, headline_level = "MODERATE", level
                break

    # Composite overlay
    comp_norm = (composite or {}).get('normalised_score', 0.0)
    if comp_norm <= -25 and headline_label == "MODERATE":
        headline_label = "STRONG"
        warnings.append("Composite upgraded MODERATE -> STRONG (dip-favourable macro)")
    elif comp_norm >= 25 and headline_label in ("STRONG", "EXTREME"):
        headline_label = "MODERATE"
        warnings.append("Composite downgraded -> MODERATE (complacent macro overlay)")

    return {
        "by_dip_level": by_level,
        "overall": {
            "label": headline_label,
            "dip_level": headline_level,
            "composite_normalised": comp_norm,
            "composite_interpretation": (composite or {}).get('interpretation'),
        },
        "warnings": warnings,
    }
