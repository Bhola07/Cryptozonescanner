"""
Price-timeframe chart with cluster zones drawn on top of the candles.

Colour and line-style scheme (chosen so overlapping zones stay distinguishable):
- High clusters: red fill, solid outline.
- Low clusters:  blue fill, dashed outline.
- Where a High and a Low overlap, the fills blend (purple) and the two outlines
  remain visible as solid red and dashed blue.
- Candles are neutral grey so they don't compete with the zone colours.
"""

import pandas as pd
import plotly.graph_objects as go

HIGH_LINE = "#ef4444"
LOW_LINE = "#3b82f6"
HIGH_FILL = "rgba(239, 68, 68, 0.22)"
LOW_FILL = "rgba(59, 130, 246, 0.22)"
CANDLE_UP = "#d1d5db"
CANDLE_DOWN = "#6b7280"


def build_price_chart(candles: pd.DataFrame, zones: pd.DataFrame,
                      show_high: bool, show_low: bool, fmt) -> go.Figure:
    """
    candles: completed daily candles (timestamp, open, high, low, close).
    zones:   output of engine.scan(), already filtered for minimum occurrences.
    fmt:     price formatter, e.g. fmt_price from the app.
    """
    fig = go.Figure()
    times = pd.to_datetime(candles["timestamp"], unit="ms", utc=True)

    fig.add_trace(go.Candlestick(
        x=times, open=candles["open"], high=candles["high"],
        low=candles["low"], close=candles["close"],
        name="Price", showlegend=False,
        increasing_line_color=CANDLE_UP, increasing_fillcolor=CANDLE_UP,
        decreasing_line_color=CANDLE_DOWN, decreasing_fillcolor=CANDLE_DOWN,
    ))

    # Legend entries (dummy traces so the legend explains the colours).
    fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines",
                             line=dict(color=HIGH_LINE, width=2),
                             name="High cluster", visible=show_high or "legendonly"))
    fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines",
                             line=dict(color=LOW_LINE, width=2, dash="dash"),
                             name="Low cluster", visible=show_low or "legendonly"))

    if len(times) == 0:
        fig.update_layout(height=600)
        return fig

    last_time = times.iloc[-1]
    for zone_type, enabled in (("High", show_high), ("Low", show_low)):
        if not enabled:
            continue
        sub = zones[zones["zone_type"] == zone_type]
        is_high = zone_type == "High"

        # Boxes: from the reference candle to the end of the chart.
        for _, z in sub.iterrows():
            fig.add_shape(
                type="rect", xref="x", yref="y",
                x0=z["reference_time"], x1=last_time,
                y0=z["lower"], y1=z["upper"],
                fillcolor=HIGH_FILL if is_high else LOW_FILL,
                line=dict(color=HIGH_LINE if is_high else LOW_LINE,
                          width=1.5, dash="solid" if is_high else "dash"),
                layer="below",
            )

        # Invisible markers carry the hover details for each cluster.
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
            ))

    fig.update_layout(
        height=640,
        hovermode="closest",
        xaxis_rangeslider_visible=False,
        yaxis_title="Price",
        xaxis_title=None,
        legend=dict(orientation="h", y=1.08, x=0),
        margin=dict(l=10, r=10, t=40, b=10),
    )
    return fig
