"""Crypto Zone Scanner MVP - spot markets, daily candles, High/Low zones.
Run with: streamlit run app.py
"""

import math
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from chart import build_lane_chart
from data import SUPPORTED_EXCHANGES, TIMEFRAME, fetch_daily_ohlcv, gap_report
from db import list_scans, load_scan, save_scan
from engine import filter_completed, scan, taps_for_zones
from exporter import build_detail, build_summary, to_csv_bytes, to_excel_bytes
from hotspots import find_hotspots

MARKET = "spot"
DEFAULT_EXCHANGE = "gate"
DEFAULT_PAIR = "BTC/USDT"
DEFAULT_DAYS = 90
DEFAULT_WIDTH = 1.0
HIGH_TINT = "rgba(34, 197, 94, 0.15)"   # green, matches High clusters
LOW_TINT = "rgba(239, 68, 68, 0.15)"    # red, matches Low clusters
EXPORT_TAP_LIMIT = 500_000
MAX_CHART_TAPS = 50_000

st.set_page_config(page_title="Crypto Zone Scanner", layout="wide",
                   initial_sidebar_state="auto")  # auto = closed on phones, open on desktop
st.title("Crypto Zone Scanner — MVP")
st.caption("Historical daily high/low zone tap counter · spot markets · "
           "analysis only, not a trading tool.")


@st.cache_data(ttl=900, show_spinner="Fetching daily candles from exchange...")
def load(exchange, pair, since_ms, end_ms):
    return fetch_daily_ohlcv(exchange, pair, since_ms, end_ms)


COLLAPSE_SIDEBAR_JS = """
<script>
// nonce %f
(function () {
  const doc = window.parent.document;
  function collapse() {
    const sidebar = doc.querySelector('[data-testid="stSidebar"]');
    const btn = doc.querySelector('[data-testid="stSidebarCollapseButton"] button');
    if (sidebar && btn && sidebar.getBoundingClientRect().width > 50) {
      btn.click();  // Streamlit's own button, so the close animation is the built-in one
    }
  }
  setTimeout(collapse, 200);
})();
</script>
"""


def render_side_table(zones, kind: str):
    """One table per side (High or Low). Each table sorts independently."""
    sub = zones[zones["zone_type"] == kind].sort_values("reference_time", ascending=False)
    price_col = "DH" if kind == "High" else "DL"
    table = pd.DataFrame({
        "Date": sub["reference_time"].dt.strftime("%Y-%m-%d").to_numpy(),
        price_col: sub["reference_price"].map(fmt_price).to_numpy(),
        "Cluster range": [f"{fmt_price(a)} – {fmt_price(b)}"
                          for a, b in zip(sub["lower"], sub["upper"])],
        "Occurrences": sub["occurrences"].to_numpy(),
    })
    tint = HIGH_TINT if kind == "High" else LOW_TINT
    styler = (table.style.hide(axis="index")
              .set_properties(subset=[price_col, "Cluster range", "Occurrences"],
                              **{"background-color": tint}))
    st.markdown(f"**{kind} clusters**")
    st.dataframe(styler, width="stretch", column_config={
        "Date": st.column_config.TextColumn("Date", width="small"),
        price_col: st.column_config.TextColumn(price_col, width="small"),
        "Cluster range": st.column_config.TextColumn("Cluster range", width="medium"),
        "Occurrences": st.column_config.NumberColumn("Occurrences", width="small"),
    })


def utc_ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def fmt_price(x: float) -> str:
    """Show enough decimals for small prices: 100000 -> '100,000.00', 0.0004 -> '0.00040000'."""
    if x == 0 or not math.isfinite(x):
        return f"{x:,.2f}"
    decimals = min(12, max(2, 4 - math.floor(math.log10(abs(x)))))
    return f"{x:,.{decimals}f}"


def build_result(candles, width_pct, meta, forming_dropped):
    zones = scan(candles, width=width_pct / 100)
    zones["occurrences"] = zones["tap_count"] + 1  # reference candle = first occurrence
    return {
        "zones": zones,
        "candles": candles,
        "meta": meta,
        "gaps": gap_report(candles),
        "forming_dropped": forming_dropped,
        "width_pct": width_pct,
    }


def open_saved(scan_id):
    """Reopen a saved search instantly, without fetching from the exchange."""
    row = load_scan(scan_id)
    if row is None:
        return
    st.session_state["exchange"] = row["exchange"]
    st.session_state["pair"] = row["pair"]
    st.session_state["start"] = datetime.fromtimestamp(row["start_ms"] / 1000, timezone.utc).date()
    st.session_state["end"] = (datetime.fromtimestamp(row["end_ms"] / 1000, timezone.utc)
                               - timedelta(days=1)).date()
    st.session_state["width_pct"] = float(row["width_pct"])
    meta = {"exchange": row["exchange"], "market": MARKET,
            "symbol": row["pair"], "timeframe": TIMEFRAME}
    st.session_state["res"] = build_result(row["candles"], row["width_pct"], meta,
                                           row["forming_dropped"])
    st.session_state["res_saved_at"] = row["saved_at"]
    st.session_state["res_restored"] = True
    st.session_state["collapse_sidebar"] = True


# ---------- Defaults and restore the last search ----------
st.session_state.setdefault("exchange", DEFAULT_EXCHANGE)
st.session_state.setdefault("pair", DEFAULT_PAIR)
st.session_state.setdefault("start", date.today() - timedelta(days=DEFAULT_DAYS))
st.session_state.setdefault("end", date.today())
st.session_state.setdefault("width_pct", DEFAULT_WIDTH)

if "res" not in st.session_state:
    recent = list_scans(1)
    if recent:
        open_saved(recent[0]["id"])

# ---------- Sidebar: New scan and saved searches ----------
with st.sidebar:
    st.header("New scan")
    exchange = st.selectbox("Exchange", SUPPORTED_EXCHANGES, key="exchange")
    pair = st.text_input("Trading pair (spot)", key="pair")
    st.caption(f"Market: {MARKET} · Timeframe: daily ({TIMEFRAME})")
    start = st.date_input("Start date", key="start")
    end = st.date_input("End date", key="end")
    width_pct = st.slider("Zone width (±%)", 0.1, 5.0, step=0.1, key="width_pct")
    run = st.button("Run scan", type="primary", width="stretch")

    st.divider()
    st.subheader("Saved searches (all users)")
    saved = list_scans(50)
    if saved:
        saved_labels = {
            r["id"]: (f"{r['exchange']} · {r['pair']} · "
                      f"{datetime.fromtimestamp(r['start_ms'] / 1000, timezone.utc):%Y-%m-%d} → "
                      f"{datetime.fromtimestamp(r['end_ms'] / 1000, timezone.utc):%Y-%m-%d} · "
                      f"±{r['width_pct']}% · saved {r['saved_at']}")
            for r in saved
        }
        pick = st.selectbox("Pick a saved search", list(saved_labels),
                            format_func=lambda i: saved_labels[i], key="recent_pick")
        st.button("Open selected search", width="stretch",
                  on_click=open_saved, args=(pick,))
    else:
        st.caption("No saved searches yet. Run a scan and it will appear here.")

# ---------- Run a new scan ----------
if run:
    pair_clean = pair.strip().upper()
    if start >= end:
        st.error("Start date must be before end date.")
    else:
        since_ms, end_ms = utc_ms(start), utc_ms(end + timedelta(days=1))
        try:
            raw, tf_ms = load(exchange, pair_clean, since_ms, end_ms)
        except Exception as e:  # network, rate limit, unlisted pair, etc.
            st.error(f"Could not fetch data: {e}")
        else:
            completed = filter_completed(raw, tf_ms, int(time.time() * 1000))
            dropped = len(raw) - len(completed)
            meta = {"exchange": exchange, "market": MARKET,
                    "symbol": pair_clean, "timeframe": TIMEFRAME}
            try:
                st.session_state["res"] = build_result(completed, width_pct, meta, dropped)
            except ValueError as e:
                st.error(str(e))
            else:
                save_scan(exchange, pair_clean, since_ms, end_ms, width_pct, completed, dropped)
                st.session_state["res_saved_at"] = "just now"
                st.session_state["res_restored"] = False
                st.session_state["collapse_sidebar"] = True

res = st.session_state.get("res")
if not res:
    st.info("Configure a scan in the sidebar and press Run scan.")
    st.stop()

# Slide the sidebar closed after a search, so the results have the full screen.
if st.session_state.pop("collapse_sidebar", False):
    st.iframe(COLLAPSE_SIDEBAR_JS % time.time(), height=1)

zones, candles, meta = res["zones"], res["candles"], res["meta"]
width = res["width_pct"] / 100
labels = {
    r["zone_id"]: (f"{r['zone_type']} {fmt_price(r['lower'])}–{fmt_price(r['upper'])} "
                   f"({r['occurrences']} occurrences)")
    for _, r in zones.iterrows()
}

# ---------- Scan summary ----------
st.subheader(f"{meta['symbol']} · {meta['exchange']} · {meta['market']} · daily")
if st.session_state.get("res_restored"):
    st.info(f"Showing your last saved search (saved {st.session_state.get('res_saved_at')}). "
            "Use Run scan for fresh data.")
st.caption(f"Zone width ±{res['width_pct']:.1f}% · completed candles only · "
           f"{res['forming_dropped']} forming candle(s) excluded")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Reference candles", len(zones) // 2)
c2.metric("Total zones", len(zones))
c3.metric("Total taps", int(zones["tap_count"].sum()))
c4.metric("Highest occurrences", int(zones["occurrences"].max()) if len(zones) else 0)

# ---------- Cluster tables: High and Low, separate and side by side ----------
st.subheader("Clusters by day")
h_box, l_box = st.columns(2)
show_high_tbl = h_box.checkbox("High", value=True, key="table_high")
show_low_tbl = l_box.checkbox("Low", value=True, key="table_low")

sides = [k for k, on in (("High", show_high_tbl), ("Low", show_low_tbl)) if on]
if not sides:
    st.info("Tick High, Low, or both to show clusters.")
    shown = zones.iloc[0:0]
else:
    for col, kind in zip(st.columns(len(sides)), sides):
        with col:
            render_side_table(zones, kind)
    shown = zones[zones["zone_type"].isin(sides)]

# ---------- Zone lanes charts: High and Low side by side ----------
st.subheader("Zone chart")
max_occ = max(int(zones["occurrences"].max()) if len(zones) else 1, 1)
if st.session_state.get("min_occ", 1) > max_occ:
    st.session_state["min_occ"] = max_occ

r1 = st.columns([1, 1, 2])
chart_high = r1[0].checkbox("Show High zones", value=True, key="chart_high")
chart_low = r1[1].checkbox("Show Low zones", value=True, key="chart_low")
min_occ = r1[2].slider("Minimum occurrences to show", 1, max_occ, 1, key="min_occ",
                       help="Hides zones with fewer occurrences than this.")

shown_zones = zones[zones["occurrences"] >= min_occ]
lane_taps = None
if int(shown_zones["tap_count"].sum()) <= MAX_CHART_TAPS:
    lane_taps = taps_for_zones(candles, shown_zones[shown_zones["tap_count"] > 0], width)
else:
    st.caption("Too many taps to draw dots. Raise the minimum occurrences.")

chart_sides = [k for k, on in (("High", chart_high), ("Low", chart_low)) if on]
if not chart_sides:
    st.info("Tick Show High zones, Show Low zones, or both.")
else:
    for col, kind in zip(st.columns(len(chart_sides)), chart_sides):
        with col:
            fig, rows = build_lane_chart(candles, zones, lane_taps,
                                         kind == "High", kind == "Low", fmt_price, min_occ)
            st.markdown(f"**{kind} zones**")
            if fig is None or rows == 0:
                st.info(f"No {kind} zones have {min_occ} or more occurrences.")
            else:
                st.plotly_chart(fig, width="stretch",
                                config={"displaylogo": False, "responsive": True})
                st.caption(f"{rows} rows · ◆ reference candle (occurrence 1) · dots = taps · "
                           "hover a bar or dot for details.")
                if rows > 60:
                    st.warning(f"{rows} rows is tall on a phone. Raise the minimum occurrences.")

# ---------- Hotspots: where High and Low zones were tapped most, combined ----------
st.subheader("Hotspots · where High and Low zones were tapped most")
st.caption("Each row is a price band. It counts every tap from High and Low zones whose "
           "tested price falls inside that band, using the same width as the zones. "
           "Bands don't overlap.")
all_tap_total = int(zones["tap_count"].sum())
if all_tap_total > EXPORT_TAP_LIMIT:
    st.info("Too many taps to compute hotspots. Use a shorter date range.")
elif all_tap_total == 0:
    st.info("No taps in this range yet, so there are no hotspots.")
else:
    all_taps = taps_for_zones(candles, zones[zones["tap_count"] > 0], width)
    hot = find_hotspots(all_taps, width, top_k=5)
    hot_table = pd.DataFrame({
        "Rank": hot["rank"].to_numpy(),
        "Price band": [f"{fmt_price(a)} – {fmt_price(b)}"
                       for a, b in zip(hot["low"], hot["high"])],
        "Total taps": hot["total_taps"].to_numpy(),
        "From High zones": hot["high_taps"].to_numpy(),
        "From Low zones": hot["low_taps"].to_numpy(),
        "Zones involved": hot["zones_involved"].to_numpy(),
        "First tap": pd.to_datetime(hot["first_tap"]).dt.strftime("%Y-%m-%d").to_numpy(),
        "Last tap": pd.to_datetime(hot["last_tap"]).dt.strftime("%Y-%m-%d").to_numpy(),
    })
    st.dataframe(hot_table.style.hide(axis="index"), width="stretch", column_config={
        "Rank": st.column_config.NumberColumn("Rank", width="small"),
        "Price band": st.column_config.TextColumn("Price band", width="medium"),
        "Total taps": st.column_config.NumberColumn("Total taps", width="small"),
        "From High zones": st.column_config.NumberColumn("From High", width="small"),
        "From Low zones": st.column_config.NumberColumn("From Low", width="small"),
        "Zones involved": st.column_config.NumberColumn("Zones", width="small"),
        "First tap": st.column_config.TextColumn("First tap", width="small"),
        "Last tap": st.column_config.TextColumn("Last tap", width="small"),
    })

# ---------- Zone details ----------
st.subheader("Zone details")
if len(shown):
    sel = st.selectbox("Select a zone", shown["zone_id"].tolist(),
                       format_func=lambda z: labels[z])
    z = zones[zones["zone_id"] == sel].iloc[0]
    d1, d2, d3, d4, d5 = st.columns(5)
    d1.metric("Reference date", z["reference_time"].strftime("%Y-%m-%d"))
    d2.metric("Reference " + z["zone_type"].lower(), fmt_price(z["reference_price"]))
    d3.metric("Zone", f"{fmt_price(z['lower'])} – {fmt_price(z['upper'])}")
    d4.metric("Occurrences", int(z["occurrences"]))
    d5.metric("Taps", int(z["tap_count"]))

    zt = taps_for_zones(candles, zones[zones["zone_id"] == sel], width)[
        ["tap_time", "tap_high", "tap_low", "tested_price"]]
    if len(zt):
        zt = zt.assign(tap_time=zt["tap_time"].dt.strftime("%Y-%m-%d"))
        for col in ["tap_high", "tap_low", "tested_price"]:
            zt[col] = zt[col].map(fmt_price)
        st.dataframe(zt, hide_index=True, width="stretch")
    else:
        st.write("No taps for this zone yet (occurrence = the reference candle only).")
else:
    st.write("No zones to show for this selection.")

# ---------- Export ----------
st.subheader("Export")
total_taps = int(zones["tap_count"].sum())
if total_taps > EXPORT_TAP_LIMIT:
    st.info(f"This scan has {total_taps:,} taps, above the export limit of "
            f"{EXPORT_TAP_LIMIT:,}. Use a shorter date range to export.")
else:
    taps = taps_for_zones(candles, zones[zones["tap_count"] > 0], width)
    summary = build_summary(zones, taps, meta)
    detail = build_detail(taps, meta)
    base = f"{meta['exchange']}_spot_{meta['symbol'].replace('/', '-')}_1d"
    e1, e2, e3 = st.columns(3)
    e1.download_button("Summary CSV", to_csv_bytes(summary),
                       f"{base}_summary.csv", "text/csv")
    e2.download_button("Tap detail CSV", to_csv_bytes(detail),
                       f"{base}_taps.csv", "text/csv")
    e3.download_button("Excel (both sheets)", to_excel_bytes(summary, detail),
                       f"{base}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with st.expander("Data quality"):
    g = res["gaps"]
    st.write(f"Expected candles in range: {g['expected']} · Received: {g['actual']} · "
             f"Missing: {g['missing']}")
    if g["missing"] > 0:
        st.warning("Some daily candles are missing from the exchange history. "
                   "Results only reflect the candles that were returned.")
