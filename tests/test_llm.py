"""Tests for llm.normalize(): checks the model's output without calling the network.

Run from the repo root:  python3 -m unittest discover tests
"""

import json
import sys
import unittest
from datetime import date
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))

import llm  # noqa: E402

ROUTE = json.loads((APP / "data" / "route.json").read_text())
TODAY = date(2026, 11, 15)


class NormalizeTest(unittest.TestCase):
    def test_clean_reply_fills_all_fields(self):
        raw = json.dumps({
            "title": "Saturday hike", "date": "2026-11-21", "earliest_departure": "09:00",
            "group_size": 4, "home_by": "19:00", "destination": "Cold Spring",
        })
        out = llm.normalize(raw, ROUTE, TODAY)
        self.assertEqual(out["fields"], {
            "title": "Saturday hike", "date": "2026-11-21", "earliest_departure": "09:00",
            "group_size": 4, "home_by": "19:00",
        })
        self.assertEqual(out["notes"], [])

    def test_messy_values_are_dropped_with_notes(self):
        raw = '```json\n{"earliest_departure": "9:30", "home_by": "7pm", "group_size": "lots", "date": "2026-01-01"}\n```'
        out = llm.normalize(raw, ROUTE, TODAY)
        self.assertEqual(out["fields"], {"earliest_departure": "09:30"})
        self.assertEqual(len(out["notes"]), 3)  # bad home_by, bad group size, past date

    def test_unsupported_destination_is_flagged(self):
        out = llm.normalize('{"destination": "Bear Mountain"}', ROUTE, TODAY)
        self.assertIn("only", out["notes"][0])

    def test_non_json_reply_raises(self):
        with self.assertRaises(llm.LLMError):
            llm.normalize("Sure! You want to go hiking.", ROUTE, TODAY)


if __name__ == "__main__":
    unittest.main()
