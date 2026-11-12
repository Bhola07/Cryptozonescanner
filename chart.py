"""
Zone chart: price on the vertical axis, time on the horizontal axis. No candles.

Readability rules:
- High clusters in the LEFT panel (green), Low clusters in the RIGHT panel (red).
  Both panels share one price scale.
- Only the top N zones per side (by occurrences) get a label. All other zones
  are faint outlines, so the chart is not buried in text.
- Labels are spaced automatically so they don't stack on top of each other.
- One zone can be highlighted: bold outline, stronger fill, its label, its tap dots.
- Tap dots are drawn only for labelled zones and the highlighted zone.
- Hovering anywhere inside any box shows that cluster's full details.
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HIGH_HEX = "#22c55e"  # green
LOW_HEX = "#ef4444"   # red
BG = "#0e1117"
TEXT = "#e5e7eb"
GRID = "rgba(255, 255, 255, 0.05)"
LABEL_BG = "rgba(15, 23, 42, 0.94)"
HOVER_LEVELS = 3


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def _place_labels(items, price_span: float, width_days: float) -> dict:
    """
    Greedy label spacing. Each item: {"key", "x", "y", "prio"}.
    Items are placed in priority order; a label that would overlap an
    already-placed label is moved down until it clears.
    """
    height = price_span * 0.06
    width = pd.Timedelta(days=width_days)
    placed, positions = [], {}
    for it in sorted(items, key=lambda d: d["prio"], reverse=True):
        y = it["y"]
        for _ in range(400):
            clash = any(abs(it["x"] - px) < width and abs(y - py) < height
                        for px, py in placed)
            if not clash:
                break
            y -= height
        placed.append((it["x"], y))
        positions[it["key"]] = y
    return positions


def build_zone_chart(candles: pd.DataFrame, zones: pd.DataFrame,
                     show_high: bool, show_low: bool, fmt,
                     taps: pd.DataFrame = None,
                     show_labels: bool = True, show_dots: bool = True,
                     top_n: int = 10, highlight_id: str = None):
    """
    candles:      completed daily candles (time range).
    zones:        scan() output with an 'occurrences' column.
    fmt:          price formatter (fmt_price from the app).
    taps:         tap records for labelled/highlighted zones (for dots).
    top_n:        how many zones per side get a label.
    highlight_id: zone_id to emphasise, or None.
    Returns a Plotly figure, or None if neither side is selected.
    """
    types = [t for t, on in (("High", show_high), ("Low", show_low)) if on]
    if not types:
        return None

    fig = make_subplots(
        rows=1, cols=len(types), shared_yaxes=True,
        subplot_titles=[f"{t} clusters · top {top_n} labelled" for t in types],
        horizontal_spacing=0.05,
    )

    times = pd.DatetimeIndex(pd.to_datetime(candles["timestamp"], unit="ms", utc=True))
    last_time = times.max()
    total_days = max((last_time - times.min()).days, 1)
    prices = pd.concat([zones["lower"], zones["upper"]]) if len(zones) else pd.Series([1.0])
    price_span = float(prices.max() - prices.min()) or 1.0
    width_days = max(4.0, 0.3 * total_days)

    for col, zone_type in enumerate(types, start=1):
        is_high = zone_type == "High"
        line_hex = HIGH_HEX if is_high else LOW_HEX
        sub = zones[zones["zone_type"] == zone_type]

        ranked = sub.sort_values(["occurrences", "reference_time"], ascending=[False, False])
        labelled = set(ranked["zone_id"].head(top_n))
        if highlight_id is not None and highlight_id in set(sub["zone_id"]):
            labelled.add(highlight_id)

        items = [
            {"key": z["zone_id"], "x": z["reference_time"], "y": z["upper"],
             "prio": (z["zone_id"] == highlight_id, int(z["occurrences"]))}
            for _, z in sub[sub["zone_id"].isin(labelled)].iterrows()
        ]
        label_y = _place_labels(items, price_span, width_days) if show_labels else {}

        hover_x, hover_y, hover_text = [], [], []
        for _, z in sub.iterrows():
            zid = z["zone_id"]
            ref = z["reference_time"]
            occ = int(z["occurrences"])
            n_taps = int(z["tap_count"])
            rng = f"{fmt(z['lower'])} – {fmt(z['upper'])}"
            focus = zid == highlight_id

            if focus:
                fill_a, line_a, line_w = 0.35, 1.0, 3
            elif zid in labelled:
                fill_a, line_a, line_w = 0.16, 0.9, 1.5
            else:
                fill_a, line_a, line_w = 0.03, 0.28, 1

            fig.add_shape(
                type="rect", x0=ref, x1=last_time, y0=z["lower"], y1=z["upper"],
                fillcolor=_rgba(line_hex, fill_a),
                line=dict(color=_rgba(line_hex, line_a), width=line_w),
                layer="below", row=1, col=col,
            )

            if show_labels and zid in label_y:
                fig.add_annotation(
                    x=ref, y=label_y[zid],
                    text=f"<b>{rng}</b><br>Occurrences: {occ}",
                    showarrow=False, xanchor="left", yanchor="top", align="left",
                    font=dict(size=12, color=TEXT),
                    bgcolor=LABEL_BG, bordercolor=line_hex,
                    borderwidth=3 if focus else 1.5, borderpad=4,
                    row=1, col=col,
                )

            detail = (
                f"<b>{zone_type} cluster</b><br>"
                f"Range: {rng}<br>"
                f"Daily {'high' if is_high else 'low'} (DH/DL): {fmt(z['reference_price'])}<br>"
                f"Reference date: {ref:%Y-%m-%d}<br>"
                f"Occurrences: {occ} (reference + {n_taps} taps)<br>"
                f"Taps: {n_taps}"
            )
            span = times[times >= ref]
            for i in range(HOVER_LEVELS):
                y = z["lower"] + (z["upper"] - z["lower"]) * i / (HOVER_LEVELS - 1)
                hover_x.extend(span)
                hover_y.extend([y] * len(span))
                hover_text.extend([detail] * len(span))

        if hover_x:
            fig.add_trace(go.Scatter(
                x=hover_x, y=hover_y, mode="markers",
                marker=dict(size=14, color="rgba(0,0,0,0)"),
                hovertext=hover_text, hoverinfo="text", showlegend=False,
            ), row=1, col=col)

        if show_dots and taps is not None and len(taps):
            tp = taps[(taps["zone_type"] == zone_type) & (taps["zone_id"].isin(labelled))]
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
                    marker=dict(size=7, color=line_hex,
                                line=dict(color="#ffffff", width=1)),
                    hovertext=tap_hover, hoverinfo="text", showlegend=False,
                ), row=1, col=col)

    fig.update_layout(
        height=640,
        hovermode="closest",
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font=dict(color=TEXT),
        margin=dict(l=10, r=10, t=60, b=10),
        showlegend=False,
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, title_text="Price")
    return fig
