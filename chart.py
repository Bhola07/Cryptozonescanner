"""
Zone chart: price on the vertical axis, time on the horizontal axis.
No candles are drawn. Only the cluster boxes appear.

Layout:
- High clusters are drawn in the LEFT panel, Low clusters in the RIGHT panel.
  Both panels share the same price scale, so their boxes never overlap.
- Colours follow trading-chart convention: green = High, red = Low.
- Each box is labelled with its cluster range.
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HIGH_LINE = "#22c55e"  # green
HIGH_FILL = "rgba(34, 197, 94, 0.20)"
LOW_LINE = "#ef4444"   # red
LOW_FILL = "rgba(239, 68, 68, 0.20)"


def build_zone_chart(candles: pd.DataFrame, zones: pd.DataFrame,
                     show_high: bool, show_low: bool, fmt, taps: pd.DataFrame = None):
    """
    candles: completed daily candles (used only for the chart's time range).
    zones:   output of engine.scan(), already filtered for minimum occurrences.
    fmt:     price formatter, e.g. fmt_price from the app.
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

    times = pd.to_datetime(candles["timestamp"], unit="ms", utc=True)
    last_time = times.max() if len(times) else None

    for col, zone_type in enumerate(types, start=1):
        is_high = zone_type == "High"
        line = HIGH_LINE if is_high else LOW_LINE
        fill = HIGH_FILL if is_high else LOW_FILL
        sub = zones[zones["zone_type"] == zone_type]

        for _, z in sub.iterrows():
            # Box runs from the reference candle to the end of the data.
            fig.add_shape(
                type="rect",
                x0=z["reference_time"], x1=last_time,
                y0=z["lower"], y1=z["upper"],
                fillcolor=fill,
                line=dict(color=line, width=1.5),
                layer="below",
                row=1, col=col,
            )
            # Cluster range label at the top-left inside the box.
            fig.add_annotation(
                x=z["reference_time"], y=z["upper"],
                text=f"{fmt(z['lower'])} – {fmt(z['upper'])}",
                showarrow=False, xanchor="left", yanchor="top",
                font=dict(size=10, color=line),
                row=1, col=col,
            )

        # Invisible markers carry hover details (range, reference date, occurrences).
        if len(sub):
            hover = [
                f"<b>{zone_type} cluster</b><br>"
                f"Range: {fmt(z['lower'])} – {fmt(z['upper'])}<br>"
                f"Reference: {z['reference_time']:%Y-%m-%d}<br>"
                f"Occurrences: {int(z['tap_count'])}"
                for _, z in sub.iterrows()
            ]
            fig.add_trace(go.Scatter(
                x=sub["reference_time"],
                y=(sub["lower"] + sub["upper"]) / 2,
                mode="markers",
                marker=dict(size=10, color="rgba(0,0,0,0)"),
                hovertext=hover, hoverinfo="text",
                showlegend=False,
            ), row=1, col=col)

        # Tap dots: one dot per candle that tapped this cluster, placed on the
        # day of the tap at the price that touched the zone.
        if taps is not None and len(taps):
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
        height=640,
        hovermode="closest",
        yaxis_title="Price",
        margin=dict(l=10, r=10, t=50, b=10),
        showlegend=False,
    )
    return fig
