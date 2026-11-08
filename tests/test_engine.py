"""
Tests built from the worked examples in the MVP specification.
Run with:  python -m unittest discover -s tests -v
"""

import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from engine import filter_completed, scan, taps_for_zones  # noqa: E402

TF_MS = 86_400_000  # daily candles
BASE = 1_700_000_000_000 // TF_MS * TF_MS


def make_candles(highs, lows):
    """Build a candle frame. open/close are unused by the engine, so set them to the midpoint."""
    rows = []
    for i, (h, l) in enumerate(zip(highs, lows)):
        rows.append({"timestamp": BASE + i * TF_MS, "open": (h + l) / 2,
                     "high": h, "low": l, "close": (h + l) / 2, "volume": 1.0})
    return pd.DataFrame(rows)


def ts(ms):
    return pd.Timestamp(ms, unit="ms", tz="UTC")


def zone_row(zones, zone_id):
    return zones.loc[zones["zone_id"] == zone_id].iloc[0]


class TestZoneBounds(unittest.TestCase):
    def test_spec_example_high_and_low_zones(self):
        # Spec: High 100,000 -> 99,000-101,000 ; Low 95,000 -> 94,050-95,950
        df = make_candles(highs=[100_000], lows=[95_000])
        zones = scan(df)
        high = zone_row(zones, "High-0")
        low = zone_row(zones, "Low-0")
        self.assertAlmostEqual(high["lower"], 99_000, places=6)
        self.assertAlmostEqual(high["upper"], 101_000, places=6)
        self.assertAlmostEqual(low["lower"], 94_050, places=6)
        self.assertAlmostEqual(low["upper"], 95_950, places=6)

    def test_every_candle_gets_two_independent_zones(self):
        df = make_candles(highs=[10, 11, 12], lows=[9, 9.5, 10])
        zones = scan(df)
        self.assertEqual(len(zones), 6)  # 3 candles x 2 zone types
        self.assertEqual(set(zones["zone_type"]), {"High", "Low"})


class TestTapRules(unittest.TestCase):
    def setUp(self):
        # Reference candle 0: High 100,000 / Low 95,000.
        # Candles 1-5 carry the spec's test values in their High and Low.
        highs = [100_000, 98_000, 99_500, 100_000, 100_800, 101_500]
        lows = [95_000, 93_000, 94_500, 95_000, 95_800, 96_500]
        self.df = make_candles(highs, lows)
        self.zones = scan(self.df); self.taps = taps_for_zones(self.df, self.zones)

    def test_high_zone_taps_match_spec(self):
        # Highs 98,000 (no), 99,500 (yes), 100,000 (yes), 100,800 (yes), 101,500 (no).
        # The reference candle's own high (100,000) must NOT count.
        self.assertEqual(zone_row(self.zones, "High-0")["tap_count"], 3)

    def test_low_zone_taps_match_spec(self):
        # Lows 93,000 (no), 94,500 (yes), 95,000 (yes), 95,800 (yes), 96,500 (no).
        # The reference candle's own low (95,000) must NOT count.
        self.assertEqual(zone_row(self.zones, "Low-0")["tap_count"], 3)

    def test_high_zone_only_uses_highs(self):
        # Candle 2 has low 94,500 (inside the low zone) but high 99,500.
        # It should tap the high zone via its HIGH, and the low zone via its LOW.
        taps = self.taps[(self.taps.zone_id == "High-0")]
        self.assertTrue((taps["tested_price"] == taps["tap_high"]).all())
        taps_low = self.taps[(self.taps.zone_id == "Low-0")]
        self.assertTrue((taps_low["tested_price"] == taps_low["tap_low"]).all())

    def test_no_self_tap(self):
        high_taps = self.taps[self.taps.zone_id == "High-0"]
        self.assertNotIn(ts(BASE), set(high_taps["tap_time"]))
        # Sanity check that the self-tap test is meaningful: the reference
        # candle's high really is inside its own zone.
        self.assertTrue(99_000 <= 100_000 <= 101_000)

    def test_one_tap_per_candle_per_zone(self):
        dupes = self.taps.duplicated(subset=["zone_id", "tap_time"]).sum()
        self.assertEqual(dupes, 0)

    def test_tap_count_equals_tap_rows(self):
        for zid, count in zip(self.zones["zone_id"], self.zones["tap_count"]):
            rows = (self.taps["zone_id"] == zid).sum()
            self.assertEqual(rows, count, msg=zid)

    def test_boundaries_are_inclusive(self):
        # A candle high exactly at the zone edge (101,000) should tap.
        df = make_candles(highs=[100_000, 101_000], lows=[95_000, 95_000])
        zones = scan(df)
        self.assertEqual(zone_row(zones, "High-0")["tap_count"], 1)

    def test_all_against_all_counts_earlier_candles(self):
        # Candle 0 is an EARLIER candle whose high falls in the zone of a LATER reference (candle 2).
        df = make_candles(highs=[100_500, 90_000, 100_000], lows=[99_000, 89_000, 99_000])
        zones = scan(df); taps = taps_for_zones(df, zones)
        self.assertEqual(zone_row(zones, "High-2")["tap_count"], 1)
        self.assertIn(ts(BASE), set(taps.loc[taps.zone_id == "High-2", "tap_time"]))

    def test_ranking_is_by_tap_count_desc(self):
        counts = self.zones["tap_count"].tolist()
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertEqual(self.zones["rank"].tolist(), list(range(1, len(self.zones) + 1)))


class TestCompletedCandles(unittest.TestCase):
    def test_forming_candle_is_excluded(self):
        df = make_candles(highs=[10, 11], lows=[9, 10])
        # now is in the middle of candle 1, so candle 1 has not closed yet.
        now = BASE + TF_MS + TF_MS // 2
        completed = filter_completed(df, TF_MS, now)
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed.iloc[0]["timestamp"], BASE)

    def test_candle_closing_exactly_now_is_completed(self):
        df = make_candles(highs=[10], lows=[9])
        completed = filter_completed(df, TF_MS, BASE + TF_MS)
        self.assertEqual(len(completed), 1)


class TestGuards(unittest.TestCase):
    def test_empty_input(self):
        empty = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        zones = scan(empty)
        self.assertEqual(len(zones), 0)
        self.assertEqual(len(taps_for_zones(empty, zones)), 0)

    def test_single_candle_has_zero_taps(self):
        df = make_candles(highs=[100], lows=[90])
        zones = scan(df)
        self.assertEqual(int(zones["tap_count"].sum()), 0)
        self.assertEqual(len(taps_for_zones(df, zones)), 0)

    def test_counts_match_tap_records_on_random_data(self):
        import numpy as np
        rng = np.random.default_rng(7)
        n = 120
        close = 100_000 + np.cumsum(rng.normal(0, 500, n))
        df = make_candles(highs=close + rng.uniform(0, 400, n),
                          lows=close - rng.uniform(0, 400, n))
        zones = scan(df)
        taps = taps_for_zones(df, zones)
        per_zone = taps.groupby("zone_id").size()
        for zid, count in zip(zones["zone_id"], zones["tap_count"]):
            self.assertEqual(int(per_zone.get(zid, 0)), int(count), msg=zid)

    def test_over_limit_raises(self):
        from engine import MAX_CANDLES
        df = make_candles(highs=[1.0] * (MAX_CANDLES + 1), lows=[0.5] * (MAX_CANDLES + 1))
        with self.assertRaises(ValueError):
            scan(df)


class TestForwardOnly(unittest.TestCase):
    def test_earlier_candles_do_not_tap_when_forward_only(self):
        # Candle 0 is earlier and has a high inside the zone of reference candle 2.
        df = make_candles(highs=[100_500, 90_000, 100_000], lows=[99_000, 89_000, 99_000])
        zones = scan(df, forward_only=True)
        self.assertEqual(zone_row(zones, "High-2")["tap_count"], 0)
        taps = taps_for_zones(df, zones, forward_only=True)
        self.assertEqual(len(taps[taps.zone_id == "High-2"]), 0)

    def test_later_candles_still_tap_when_forward_only(self):
        df = make_candles(highs=[100_000, 98_000, 99_500, 100_800],
                          lows=[95_000, 93_000, 94_500, 95_800])
        zones = scan(df, forward_only=True)
        self.assertEqual(zone_row(zones, "High-0")["tap_count"], 2)
        self.assertEqual(zone_row(zones, "Low-0")["tap_count"], 2)


if __name__ == "__main__":
    unittest.main()
