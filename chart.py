"""
Lane charts: one horizontal row per zone. Rows are stacked, so zones never overlap.

- Each row shows the zone's bar from its reference day to the last candle.
- A diamond marks the reference candle (occurrence 1).
- A dot marks each tap, on the day it happened.
- Hover a bar for the zone's details. Hover a dot for that tap's details.

Two views:
- build_lane_chart(): High and Low drawn separately (one chart per side).
- build_ranked_chart(): every zone in one list, most taps first, like the ranked table.
"""

import pandas as pd
import plotly.graph_objects as go

HIGH_HEX = "#22c55e"  # green
LOW_HEX = "#ef4444"   # red
BG = "#0e1117"
TEXT = "#e5e7eb"
GRID = "rgba(255, 255, 255, 0.05)"
HOVER_BG = "#111827"
ROW_HEIGHT_PX = 34
MIN_HEIGHT_PX = 360


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def _add_row(fig, z: dict, y: float, row_index: int, label: str, fmt,
             first_time, last_time, times, zone_taps):
    """Draw one zone row at height y. Returns the tick label for it."""
    is_high = z["zone_type"] == "High"
    hex_c = HIGH_HEX if is_high else LOW_HEX
    kind = "High" if is_high else "Low"
    ref = pd.Timestamp(z["reference_time"])
    occ = int(z["occurrences"])
    n_taps = int(z["tap_count"])
    rng = f"{fmt(z['lower'])} – {fmt(z['upper'])}"

    # Alternating row band for readability.
    if row_index % 2 == 0:
        fig.add_shape(type="rect", x0=first_time, x1=last_time, y0=y - 0.5, y1=y + 0.5,
                      fillcolor="rgba(255, 255, 255, 0.03)", line=dict(width=0),
                      layer="below")

    # The zone bar, from its reference day to the last candle.
    fig.add_shape(type="rect", x0=ref, x1=last_time, y0=y - 0.3, y1=y + 0.3,
                  fillcolor=_rgba(hex_c, 0.25), line=dict(color=hex_c, width=1.5),
                  layer="below")

    zone_detail = (
        f"<b>{kind} cluster</b><br>"
        f"Range: {rng}<br>"
        f"Daily {'high' if is_high else 'low'} (DH/DL): {fmt(z['reference_price'])}<br>"
        f"Reference date: {ref:%Y-%m-%d}<br>"
        f"Occurrences: {occ} (reference + {n_taps} taps)<br>"
        f"Taps: {n_taps}"
    )
    span = times[times >= ref]
    fig.add_trace(go.Scatter(
        x=span, y=[y] * len(span), mode="markers",
        marker=dict(size=24, color="rgba(0,0,0,0)"),
        hovertext=[zone_detail] * len(span), hoverinfo="text", showlegend=False,
    ))

    # Reference candle = occurrence 1.
    fig.add_trace(go.Scatter(
        x=[ref], y=[y], mode="markers",
        marker=dict(size=12, symbol="diamond", color=hex_c,
                    line=dict(color="#ffffff", width=1)),
        hovertext=[
            f"<b>Occurrence 1 · reference candle</b><br>"
            f"Date: {ref:%Y-%m-%d}<br>"
            f"Daily {'high' if is_high else 'low'} (DH/DL): {fmt(z['reference_price'])}<br>"
            f"Cluster range: {rng}"
        ],
        hoverinfo="text", showlegend=False,
    ))

    # Taps on this row.
    if zone_taps is not None and len(zone_taps):
        tp = zone_taps.sort_values("tap_time")
        tap_hover = [
            f"<b>Occurrence {k + 2} · tap</b><br>"
            f"Tapped on: {r['tap_time']:%Y-%m-%d}<br>"
            f"Cluster range: {rng}<br>"
            f"Candle high: {fmt(r['tap_high'])}<br>"
            f"Candle low: {fmt(r['tap_low'])}<br>"
            f"Tested price: {fmt(r['tested_price'])}"
            for k, (_, r) in enumerate(tp.iterrows())
        ]
        fig.add_trace(go.Scatter(
            x=tp["tap_time"], y=[y] * len(tp), mode="markers",
            marker=dict(size=10, color=hex_c, line=dict(color="#ffffff", width=1)),
            hovertext=tap_hover, hoverinfo="text", showlegend=False,
        ))
    return label


def _finish(fig, n: int):
    height = max(MIN_HEIGHT_PX, 90 + n * ROW_HEIGHT_PX)
    fig.update_layout(
        height=height,
        autosize=True,
        hovermode="closest",
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font=dict(color=TEXT, size=12),
        hoverlabel=dict(bgcolor=HOVER_BG, font=dict(color=TEXT, size=13)),
        margin=dict(l=10, r=20, t=20, b=10),
        showlegend=False,
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, showline=False)


def _rows_chart(candles, zones, taps, selected, fmt, tick_labels, separator_after=None):
    """Shared drawing for both views. selected: list of zone dicts, top row first."""
    n = len(selected)
    times = pd.DatetimeIndex(pd.to_datetime(candles["timestamp"], unit="ms", utc=True))
    first_time, last_time = times.min(), times.max()
    fig = go.Figure()
    tick_vals = []

    for i, z in enumerate(selected):
        y = n - 1 - i  # first row at the top
        zone_taps = None
        if taps is not None and len(taps):
            zone_taps = taps[taps["zone_id"] == z["zone_id"]]
        _add_row(fig, z, y, i, tick_labels[i], fmt, first_time, last_time, times, zone_taps)
        tick_vals.append(y)

    if separator_after is not None and 0 < separator_after < n:
        sep_y = n - 1 - separator_after + 0.5
        fig.add_shape(type="line", x0=first_time, x1=last_time, y0=sep_y, y1=sep_y,
                      line=dict(color="rgba(255,255,255,0.35)", width=1, dash="dot"))

    _finish(fig, n)
    fig.update_yaxes(tickvals=tick_vals, ticktext=tick_labels, showgrid=False,
                     zeroline=False, range=[-0.6, n - 0.4], fixedrange=True,
                     automargin=True)
    return fig, n


def build_lane_chart(candles: pd.DataFrame, zones: pd.DataFrame, taps: pd.DataFrame,
                     show_high: bool, show_low: bool, fmt, min_occ: int):
    """
    One side or both. High rows first, then Low rows, each ranked by occurrences.
    Returns (figure, number_of_rows), or (None, 0) if nothing is selected.
    """
    selected = []
    for zone_type, on in (("High", show_high), ("Low", show_low)):
        if not on:
            continue
        sub = zones[(zones["zone_type"] == zone_type) & (zones["occurrences"] >= min_occ)]
        sub = sub.sort_values(["occurrences", "reference_time"], ascending=[False, False])
        selected.extend(sub.to_dict("records"))
    if not selected:
        return None, 0

    high_rows = sum(1 for z in selected if z["zone_type"] == "High")
    labels = [f"{z['zone_type']} {fmt(z['lower'])} – {fmt(z['upper'])} ({int(z['occurrences'])})"
              for z in selected]
    return _rows_chart(candles, zones, taps, selected, fmt, labels, separator_after=high_rows)


def build_ranked_chart(candles: pd.DataFrame, zones: pd.DataFrame, taps: pd.DataFrame,
                       fmt, min_occ: int):
    """
    Every zone in one list, most taps first, matching the ranked table.
    Returns (figure, number_of_rows), or (None, 0) if no zone qualifies.
    """
    sub = zones[zones["occurrences"] >= min_occ]
    sub = sub.sort_values(["tap_count", "reference_time"], ascending=[False, False])
    selected = sub.to_dict("records")
    if not selected:
        return None, 0

    labels = [f"#{i + 1} {z['zone_type']} {fmt(z['lower'])} – {fmt(z['upper'])} "
              f"({int(z['tap_count'])} taps)" for i, z in enumerate(selected)]
    return _rows_chart(candles, zones, taps, selected, fmt, labels)
