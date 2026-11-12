"""
Zone chart: price on the vertical axis, time on the horizontal axis. No candles.

- High clusters in the LEFT panel (green), Low clusters in the RIGHT panel (red).
  Both share one price scale, so High and Low boxes never sit on each other.
- Each box is labelled with its cluster range and occurrence count.
- Hovering anywhere inside a box shows the full details of that cluster.
- Optional dots mark each day a cluster was tapped, at the tapped price.
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HIGH_LINE = "#22c55e"  # green
HIGH_FILL = "rgba(34, 197, 94, 0.20)"
LOW_LINE = "#ef4444"   # red
LOW_FILL = "rgba(239, 68, 68, 0.20)"
LABEL_BG = "rgba(17, 24, 39, 0.9)"
LABEL_FONT = 13
HOVER_LEVELS = 3  # hover points per box row, across its height


def _last_tap_map(taps):
    if taps is None or len(taps) == 0:
        return {}
    last = taps.groupby("zone_id")["tap_time"].max()
    return {zid: f"{t:%Y-%m-%d}" for zid, t in last.items()}


def build_zone_chart(candles: pd.DataFrame, zones: pd.DataFrame,
                     show_high: bool, show_low: bool, fmt,
                     taps: pd.DataFrame = None,
                     show_labels: bool = True, show_dots: bool = True):
    """
    candles: completed daily candles (used for the time range and hover dates).
    zones:   scan() output with an 'occurrences' column, already filtered.
    fmt:     price formatter, e.g. fmt_price from the app.
    taps:    tap records for these zones (optional; enables dots and last-tap details).
    Returns a Plotly figure, or None if neither side is selected.
    """
    types = [t for t, on in (("High", show_high), ("Low", show_low)) if on]
    if not types:
        return None

    fig = make_subplots(
        rows=1, cols=len(types), shared_yaxes=True,
        subplot_titles=[f"{t} clusters" for t in types],
        horizontal_spacing=0.04,
    )

    times = pd.DatetimeIndex(pd.to_datetime(candles["timestamp"], unit="ms", utc=True))
    last_time = times.max() if len(times) else None
    last_tap = _last_tap_map(taps)

    for col, zone_type in enumerate(types, start=1):
        is_high = zone_type == "High"
        line = HIGH_LINE if is_high else LOW_LINE
        fill = HIGH_FILL if is_high else LOW_FILL
        sub = zones[zones["zone_type"] == zone_type]

        hover_x, hover_y, hover_text = [], [], []

        for _, z in sub.iterrows():
            ref = z["reference_time"]
            occ = int(z["occurrences"])
            taps_n = int(z["tap_count"])
            rng = f"{fmt(z['lower'])} – {fmt(z['upper'])}"

            fig.add_shape(
                type="rect", x0=ref, x1=last_time, y0=z["lower"], y1=z["upper"],
                fillcolor=fill, line=dict(color=line, width=1.5), layer="below",
                row=1, col=col,
            )

            if show_labels:
                fig.add_annotation(
                    x=ref, y=z["upper"],
                    text=f"<b>{rng}</b><br>Occurrences: {occ}",
                    showarrow=False, xanchor="left", yanchor="top", align="left",
                    font=dict(size=LABEL_FONT, color="#ffffff"),
                    bgcolor=LABEL_BG, bordercolor=line, borderwidth=2, borderpad=4,
                    row=1, col=col,
                )

            # Full details for hovering anywhere inside this box.
            detail = (
                f"<b>{zone_type} cluster</b><br>"
                f"Range: {rng}<br>"
                f"Daily {'high' if is_high else 'low'} (DH/DL): {fmt(z['reference_price'])}<br>"
                f"Reference date: {ref:%Y-%m-%d}<br>"
                f"Occurrences: {occ} (reference + {taps_n} taps)<br>"
                f"Taps: {taps_n}<br>"
                f"Last tap: {last_tap.get(z['zone_id'], '—')}"
            )
            span = times[times >= ref]
            ys = [z["lower"] + (z["upper"] - z["lower"]) * i / (HOVER_LEVELS - 1)
                  for i in range(HOVER_LEVELS)]
            for y in ys:
                hover_x.extend(span)
                hover_y.extend([y] * len(span))
                hover_text.extend([detail] * len(span))

        if hover_x:
            fig.add_trace(go.Scatter(
                x=hover_x, y=hover_y, mode="markers",
                marker=dict(size=14, color="rgba(0,0,0,0)"),
                hovertext=hover_text, hoverinfo="text", showlegend=False,
            ), row=1, col=col)

        # Tap dots: one per candle that tapped this cluster, at the tapped price.
        if show_dots and taps is not None and len(taps):
            tp = taps[taps["zone_type"] == zone_type]
            if len(tp):
                tap_hover = [
                    f"<b>{zone_type} cluster tap</b><br>"
                    f"Cluster range: {fmt(r['lower'])} – {fmt(r['upper'])}<br>"
                    f"Reference: {r['reference_time']:%Y-%m-%d}<br>"
                    f"Tapped on: {r['tap_time']:%Y-%m-%d}<br>"
                    f"Candle high: {fmt(r['tap_high'])}<br>"
                    f"Candle low: {fmt(r['tap_low'])}<br>"
                    f"Tested price: {fmt(r['tested_price'])}"
                    for _, r in tp.iterrows()
                ]
                fig.add_trace(go.Scatter(
                    x=tp["tap_time"], y=tp["tested_price"], mode="markers",
                    marker=dict(size=8, color=line, line=dict(color="white", width=1)),
                    hovertext=tap_hover, hoverinfo="text", showlegend=False,
                ), row=1, col=col)

    fig.update_layout(
        height=680,
        hovermode="closest",
        yaxis_title="Price",
        margin=dict(l=10, r=10, t=50, b=10),
        showlegend=False,
    )
    return fig
