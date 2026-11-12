"""
Lane chart: one horizontal row per zone. Rows are stacked, so zones never overlap.

- Rows are ordered by occurrences (most first). High zones come first (green),
  then Low zones (red), separated by a line.
- Each row shows the zone's bar from its reference day to the last candle.
- A diamond marks the reference candle (occurrence 1).
- A dot marks each tap, on the day it happened.
- Hover a bar for the zone's details. Hover a dot for that tap's details.
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


def build_lane_chart(candles: pd.DataFrame, zones: pd.DataFrame, taps: pd.DataFrame,
                     show_high: bool, show_low: bool, fmt, top_n: int):
    """
    candles: completed daily candles (used for the time range).
    zones:   scan() output with an 'occurrences' column.
    taps:    tap records for the zones shown (may be None to skip dots).
    fmt:     price formatter (fmt_price from the app).
    top_n:   zones per side to show, ranked by occurrences.
    Returns (figure, number_of_rows), or (None, 0) if nothing is selected.
    """
    selected = []
    for zone_type, on in (("High", show_high), ("Low", show_low)):
        if not on:
            continue
        sub = zones[zones["zone_type"] == zone_type].sort_values(
            ["occurrences", "reference_time"], ascending=[False, False]).head(top_n)
        selected.extend(sub.to_dict("records"))
    if not selected:
        return None, 0

    high_rows = sum(1 for z in selected if z["zone_type"] == "High")
    n = len(selected)
    times = pd.DatetimeIndex(pd.to_datetime(candles["timestamp"], unit="ms", utc=True))
    first_time, last_time = times.min(), times.max()

    fig = go.Figure()
    tick_vals, tick_text = [], []

    for i, z in enumerate(selected):
        is_high = z["zone_type"] == "High"
        hex_c = HIGH_HEX if is_high else LOW_HEX
        kind = "High" if is_high else "Low"
        y = n - 1 - i  # first row at the top
        zid = z["zone_id"]
        ref = pd.Timestamp(z["reference_time"])
        occ = int(z["occurrences"])
        n_taps = int(z["tap_count"])
        rng = f"{fmt(z['lower'])} – {fmt(z['upper'])}"
        tick_vals.append(y)
        tick_text.append(f"{kind}  {rng}  ·  {occ} occ")

        # Alternating row band for readability.
        if i % 2 == 0:
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
        if taps is not None and len(taps):
            tp = taps[taps["zone_id"] == zid].sort_values("tap_time")
            if len(tp):
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

    # Separator between High rows and Low rows.
    if 0 < high_rows < n:
        sep_y = n - 1 - high_rows + 0.5
        fig.add_shape(type="line", x0=first_time, x1=last_time, y0=sep_y, y1=sep_y,
                      line=dict(color="rgba(255,255,255,0.35)", width=1, dash="dot"))

    height = max(MIN_HEIGHT_PX, 90 + n * ROW_HEIGHT_PX)
    fig.update_layout(
        height=height,
        hovermode="closest",
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font=dict(color=TEXT, size=12),
        hoverlabel=dict(bgcolor=HOVER_BG, font=dict(color=TEXT, size=13)),
        margin=dict(l=10, r=20, t=20, b=10),
        showlegend=False,
    )
    fig.update_yaxes(
        tickvals=tick_vals, ticktext=tick_text, showgrid=False, zeroline=False,
        range=[-0.6, n - 0.4], fixedrange=True, automargin=True,
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, showline=False)
    return fig, n
