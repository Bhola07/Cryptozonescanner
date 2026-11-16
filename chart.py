"""
Lane charts: one horizontal row per zone. Rows are stacked, so zones never overlap.

- Each row shows the zone's bar from its reference day to the last candle.
- A diamond marks the reference candle (occurrence 1).
- A dot marks each tap, on the day it happened.
- Hover a bar for the zone's details. Hover a dot for that tap's details.

Two views:
- build_lane_chart(): High and Low drawn separately (one chart per side).
- build_joint_chart(): High and Low zones merged where they overlap in price.
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


JOINT_HEX = "#f59e0b"  # amber: distinct from green (High) and red (Low)
LABEL_BG = "rgba(15, 23, 42, 0.94)"
HOVER_LEVELS = 3


def merge_joint_zones(zones: pd.DataFrame) -> list:
    """
    Group High and Low zones that overlap in price into joint bands.
    Display view only: the scan itself never merges zones.

    To stop overlaps from chaining into one huge band, grouping is seeded:
    the strongest unused zone (most occurrences) starts a band, and it collects only
    the unused zones that overlap its own range. Each zone joins at most one band.
    Each band: lower, upper, member zone_ids, High and Low counts, first reference date.
    """
    if len(zones) == 0:
        return []
    order = zones.sort_values(["occurrences", "reference_time"], ascending=[False, False])
    rows = order.to_dict("records")
    used = set()
    bands = []
    for seed in rows:
        if seed["zone_id"] in used:
            continue
        s_lo, s_hi = seed["lower"], seed["upper"]
        members = [r for r in rows
                   if r["zone_id"] not in used
                   and r["lower"] <= s_hi and s_lo <= r["upper"]]
        for m in members:
            used.add(m["zone_id"])
        bands.append({
            "lower": min(m["lower"] for m in members),
            "upper": max(m["upper"] for m in members),
            "ids": [m["zone_id"] for m in members],
            "high": sum(m["zone_type"] == "High" for m in members),
            "low": sum(m["zone_type"] == "Low" for m in members),
            "first_ref": min(m["reference_time"] for m in members),
        })
    bands.sort(key=lambda b: b["lower"], reverse=True)
    return bands


def build_joint_chart(candles: pd.DataFrame, zones: pd.DataFrame, taps: pd.DataFrame,
                      fmt, min_occ: int):
    """
    Price on the vertical axis, time on the horizontal axis.
    Each joint band is drawn from its first reference date to the last candle,
    labelled with its range and tap count, with a dot for every tap inside it.
    Returns (figure, number_of_bands), or (None, 0) if no zone qualifies.
    """
    sub = zones[zones["occurrences"] >= min_occ]
    bands = merge_joint_zones(sub)
    if not bands:
        return None, 0

    times = pd.DatetimeIndex(pd.to_datetime(candles["timestamp"], unit="ms", utc=True))
    last_time = times.max()
    fig = go.Figure()

    for b in bands:
        first_ref = pd.Timestamp(b["first_ref"])
        rng = f"{fmt(b['lower'])} – {fmt(b['upper'])}"
        band_taps = None
        if taps is not None and len(taps):
            band_taps = taps[taps["zone_id"].isin(set(b["ids"]))]
        n_taps = 0 if band_taps is None else len(band_taps)

        fig.add_shape(
            type="rect", x0=first_ref, x1=last_time, y0=b["lower"], y1=b["upper"],
            fillcolor=_rgba(JOINT_HEX, 0.22), line=dict(color=JOINT_HEX, width=1.5),
            layer="below",
        )
        fig.add_annotation(
            x=first_ref, y=b["upper"],
            text=f"<b>{rng}</b><br>Taps: {n_taps} · High {b['high']} · Low {b['low']}",
            showarrow=False, xanchor="left", yanchor="top", align="left",
            font=dict(size=11, color=TEXT), bgcolor=LABEL_BG,
            bordercolor=JOINT_HEX, borderwidth=1, borderpad=3,
        )

        detail = (
            f"<b>Joint zone</b><br>"
            f"Range: {rng}<br>"
            f"Zones merged: {len(b['ids'])} (High {b['high']} · Low {b['low']})<br>"
            f"Taps in this zone: {n_taps}<br>"
            f"First reference: {first_ref:%Y-%m-%d}"
        )
        span = times[times >= first_ref]
        for i in range(HOVER_LEVELS):
            y = b["lower"] + (b["upper"] - b["lower"]) * i / (HOVER_LEVELS - 1)
            fig.add_trace(go.Scatter(
                x=span, y=[y] * len(span), mode="markers",
                marker=dict(size=14, color="rgba(0,0,0,0)"),
                hovertext=[detail] * len(span), hoverinfo="text", showlegend=False,
            ))

        if band_taps is not None and len(band_taps):
            tap_hover = [
                f"<b>Tap · {r['zone_type']} zone</b><br>"
                f"Tapped on: {r['tap_time']:%Y-%m-%d}<br>"
                f"Joint zone: {rng}<br>"
                f"Candle high: {fmt(r['tap_high'])}<br>"
                f"Candle low: {fmt(r['tap_low'])}<br>"
                f"Tested price: {fmt(r['tested_price'])}"
                for _, r in band_taps.iterrows()
            ]
            fig.add_trace(go.Scatter(
                x=band_taps["tap_time"], y=band_taps["tested_price"], mode="markers",
                marker=dict(size=8, color=JOINT_HEX, line=dict(color="#ffffff", width=1)),
                hovertext=tap_hover, hoverinfo="text", showlegend=False,
            ))

    height = max(420, 120 + len(bands) * 12)
    fig.update_layout(
        height=height, autosize=True, hovermode="closest",
        paper_bgcolor=BG, plot_bgcolor=BG, font=dict(color=TEXT, size=12),
        hoverlabel=dict(bgcolor=HOVER_BG, font=dict(color=TEXT, size=13)),
        margin=dict(l=10, r=20, t=20, b=10), showlegend=False,
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, showline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, title_text="Price")
    return fig, len(bands)
