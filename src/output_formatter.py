"""Dip target lookup utilities.

Given a p_touch dict { '-3%': prob, '-5%': prob, ... }, find the deepest
dip threshold whose probability clears each conviction level.
"""

from typing import Optional

DIP_PCT_BY_LABEL = {
    "-3%": 0.03, "-5%": 0.05, "-7%": 0.07,
    "-10%": 0.10, "-15%": 0.15, "-20%": 0.20,
}
DEEPEST_FIRST = ("-20%", "-15%", "-10%", "-7%", "-5%", "-3%")


def deepest_dip_at(p_touch: dict, conviction: float) -> Optional[str]:
    """Return the deepest dip label whose touch-probability >= conviction.
    None if even -3% doesn't clear.
    """
    if not p_touch:
        return None
    for label in DEEPEST_FIRST:
        p = p_touch.get(label)
        if p is not None and p >= conviction:
            return label
    return None


def dip_target_table(p_touch_mc: dict, p_touch_analog: dict,
                     current_price: float, conviction_levels=(0.60, 0.70, 0.80)) -> list:
    """For each conviction level, return MC and analog dip targets + prices."""
    rows = []
    for c in conviction_levels:
        mc_label = deepest_dip_at(p_touch_mc or {}, c)
        an_label = deepest_dip_at(p_touch_analog or {}, c)
        rows.append({
            "conviction": c,
            "mc_dip": mc_label,
            "mc_price": (current_price * (1 - DIP_PCT_BY_LABEL[mc_label])
                         if mc_label else None),
            "analog_dip": an_label,
            "analog_price": (current_price * (1 - DIP_PCT_BY_LABEL[an_label])
                             if an_label else None),
        })
    return rows
