"""
Heatmap of zone taps: days on the horizontal axis, price bands on the vertical axis.

- Price bands are geometric: each band is a fixed percentage of the price, so one
  band is the same size as one zone (ratio = (1 + width) / (1 - width)). This keeps
  both 0.0004 and 80,000 readable.
- Each cell counts the taps that landed in that band on that day.
- Colour is a single dark-to-bright scale (Inferno), kept separate from the
  green and red used for High and Low zones.
- Hotspot bands from the table are outlined, using exact prices.
"""

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go

COLORSCALE = "Inferno"
BG = "#0e1117"
TEXT = "#e5e7eb"
OUTLINE = "rgba(255, 255, 255, 0.9)"
MAX_TICKS = 25


def build_heatmap(candles: pd.DataFrame, taps: pd.DataFrame, width: float,
                  show_high: bool, show_low: bool, fmt, hotspots: pd.DataFrame = None):
    """
    candles:  completed daily candles (define the day axis and the price range).
    taps:     tap records (tested_price, tap_time, zone_type).
    width:    zone width as a fraction (0.01 = 1%).
    fmt:      price formatter (fmt_price from the app).
    hotspots: output of find_hotspots(), outlined on the chart.
    Returns a Plotly figure, or None if neither side is selected.
    """
    types = [t for t, on in (("High", show_high), ("Low", show_low)) if on]
    if not types:
        return None

    ratio = (1 + width) / (1 - width)
    origin = float(candles["low"].min())
    top = float(candles["high"].max())
    n_bins = max(1, int(math.ceil(math.log(top / origin) / math.log(ratio))) + 1)

    days = pd.DatetimeIndex(pd.to_datetime(candles["timestamp"], unit="ms", utc=True)
                            .dt.normalize().unique()).sort_values()
    day_pos = {d: i for i, d in enumerate(days)}

    matrix = np.zeros((n_bins, len(days)))
    t = taps[taps["zone_type"].isin(types)] if taps is not None and len(taps) else None
    if t is not None and len(t):
        bin_idx = np.floor(np.log(t["tested_price"].to_numpy(np.float64) / origin)
                           / math.log(ratio)).astype(int)
        bin_idx = np.clip(bin_idx, 0, n_bins - 1)
        tap_days = pd.DatetimeIndex(t["tap_time"]).normalize()
        day_idx = np.array([day_pos.get(d, -1) for d in tap_days])
        keep = day_idx >= 0
        np.add.at(matrix, (bin_idx[keep], day_idx[keep]), 1)

    def band_price(i):
        lo = origin * ratio ** i
        hi = origin * ratio ** (i + 1)
        return lo, hi

    hover = []
    for i in range(n_bins):
        lo, hi = band_price(i)
        band = f"{fmt(lo)} – {fmt(hi)}"
        row = []
        for j, d in enumerate(days):
            row.append(f"<b>{d:%Y-%m-%d}</b><br>Band: {band}<br>Taps: {int(matrix[i, j])}")
        hover.append(row)

    fig = go.Figure(go.Heatmap(
        z=matrix, x=days, y=list(range(n_bins)),
        colorscale=COLORSCALE, zmin=0,
        colorbar=dict(title=dict(text="Taps", font=dict(color=TEXT)),
                      tickfont=dict(color=TEXT)),
        text=hover, hoverinfo="text",
        hoverongaps=False,
    ))

    # Price-axis labels at band centres, thinned if there are many bands.
    step = max(1, math.ceil(n_bins / MAX_TICKS))
    tick_vals = list(range(0, n_bins, step))
    tick_text = [fmt(origin * ratio ** (i + 0.5)) for i in tick_vals]
    fig.update_yaxes(tickvals=tick_vals, ticktext=tick_text, title_text="Price band",
                     showgrid=False, zeroline=False, range=[-0.5, n_bins - 0.5])

    # Hotspot outlines. A price p sits at y = log(p / origin) / log(ratio) - 0.5,
    # which places band centres on whole numbers, matching the heatmap cells.
    if hotspots is not None and len(hotspots):
        x0 = days[0] - pd.Timedelta(hours=12)
        x1 = days[-1] + pd.Timedelta(hours=12)
        for _, h in hotspots.iterrows():
            y0 = math.log(h["low"] / origin) / math.log(ratio) - 0.5
            y1 = math.log(h["high"] / origin) / math.log(ratio) - 0.5
            fig.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1,
                          line=dict(color=OUTLINE, width=1.5, dash="dot"),
                          fillcolor="rgba(0,0,0,0)", layer="above")
            fig.add_annotation(x=x1, y=y1, text=f"#{int(h['rank'])}", showarrow=False,
                               xanchor="left", font=dict(color=TEXT, size=12))

    fig.update_xaxes(showgrid=False, zeroline=False, title_text="Day")
    height = max(360, 110 + n_bins * 22)
    fig.update_layout(
        height=height,
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font=dict(color=TEXT),
        margin=dict(l=10, r=40, t=20, b=10),
        hovermode="closest",
    )
    return fig
