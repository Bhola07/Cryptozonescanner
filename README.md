# Crypto Zone Scanner (MVP)

Finds historical daily high and low price levels on **spot markets**, creates
independent ±1% zones around each one, and counts how many later completed daily
candles tapped each zone.
This is an analysis tool, not a trading bot.

## Cost

Everything here is free:
- Python, Streamlit, CCXT, Pandas, NumPy, Plotly, openpyxl are open source.
- Exchange data comes from **public** endpoints. No API keys, no accounts.
- Hosting on Streamlit Community Cloud is free for public repos.

## Setup (about 5 minutes)

```bash
cd crypto_zone_scanner
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run the app

```bash
streamlit run app.py
```

Your browser opens at http://localhost:8501. In the sidebar, choose an exchange,
a spot pair (for example BTC/USDT), a date range, and a zone width, then press
**Run scan**. Candles are always daily (1d).

## Run the tests

```bash
python -m unittest discover -s tests -v
```

The tests use the worked examples from the specification. For example, a High of
100,000 gives the zone 99,000–101,000, and the candle High values 98,000 / 99,500 /
100,000 / 100,800 / 101,500 produce exactly 3 taps. Run these before trusting any
result.

## Project layout

| File | Responsibility |
|------|----------------|
| `engine.py` | Zone creation, tap counting, completed-candle filter (no network) |
| `data.py` | CCXT spot daily fetching with pagination, rate limiting, gap report |
| `exporter.py` | Summary CSV, tap-detail CSV, Excel (two sheets) |
| `app.py` | Streamlit interface |
| `tests/test_engine.py` | Specification-based tests |

## Rules implemented

- Each candle gets an independent High zone and Low zone (±1% by default).
- High zones are tested only against candle Highs. Low zones only against Lows.
- Open and Close are never used.
- Spot markets and daily (1d) candles only. Futures and other timeframes are out of scope for now.
- Boundaries are inclusive.
- Each candle taps a given zone at most once.
- A reference candle cannot tap its own zone.
- All-against-all: every other completed candle is tested, including earlier ones.
- The forming (unfinished) candle is excluded.
- Zones are never merged.

## Known limits (be aware of these)

- **Exchange coverage varies.** All ten exchanges from the spec are in CCXT 4.x, with
  Gate.io listed as `gate`. Not every exchange lists every pair, and the app shows a
  clear error when a pair is not listed as spot on the chosen exchange.
- **Exchange data limits.** Exchanges return a limited number of candles per request,
  so the app paginates. Some newer listings have short histories. The "Data quality"
  panel reports any missing candles.
- **Size limits.** A scan covers at most 5,000 daily candles (about 13 years).
  Export is offered when the scan has 500,000 taps or fewer.
- **Width setting.** The spec's mockup shows ±0.9% in one place and ±1% everywhere
  else. The app defaults to 1%, and the slider lets you change it.

## Put it online for free (optional)

1. Create a GitHub repository and push this folder to it.
2. Go to https://share.streamlit.io, sign in with GitHub, and pick the repo.
3. Set the main file to `app.py`. Deploy.
