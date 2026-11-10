"""Deterministic tests for the TrailTrain planner.

Run from the repo root:  python3 -m unittest discover tests
"""

import json
import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))

import planner  # noqa: E402

ROUTE = json.loads((APP / "data" / "route.json").read_text())

FRIENDS = [
    {"name": "Emily", "station": "Grand Central", "fitness": "moderate", "budget": 40},
    {"name": "Sam", "station": "Harlem-125 St", "fitness": "easy", "budget": 40},
]


class PlannerTest(unittest.TestCase):
    def test_picks_first_train_after_earliest_departure(self):
        p = planner.make_plan(ROUTE, FRIENDS, "08:30")
        self.assertTrue(p["ok"])
        self.assertEqual(p["main"]["train"], "H-0843")
        self.assertEqual(p["backup"]["train"], "H-0943")

    def test_slowest_person_sets_hike_length(self):
        p = planner.make_plan(ROUTE, FRIENDS, "08:30")
        self.assertEqual(p["hike_minutes"], 300)  # Sam is "easy"
        # arrive 10:00 + 15 walk = 10:15 start, + 5h = 15:15 end
        self.assertEqual(p["main"]["trail_start"], "10:15")
        self.assertEqual(p["main"]["trail_end"], "15:15")

    def test_return_train_is_first_one_after_walking_back(self):
        p = planner.make_plan(ROUTE, FRIENDS, "08:30")
        # off trail 15:15 + 15 walk = 15:30 at station -> 15:58 train
        self.assertEqual(p["main"]["return_train"], "R-1558")

    def test_latest_off_trail_works_back_from_sunset_and_last_train(self):
        p = planner.make_plan(ROUTE, FRIENDS, "08:30")
        # sunset 16:40 - 15 buffer = 16:25 is earlier than last train 18:58 - 30
        self.assertEqual(p["latest_off_trail"], "16:25")
        self.assertEqual(p["latest_off_trail_reason"], "sunset")

    def test_delay_switches_to_next_train_and_notifies(self):
        before = planner.make_plan(ROUTE, FRIENDS, "08:30")
        after = planner.make_plan(ROUTE, FRIENDS, "08:30", {"H-0843": 70})
        self.assertEqual(after["main"]["train"], "H-0943")
        self.assertIn("H-0943", planner.describe_change(before, after))

    def test_no_plan_when_nothing_fits_before_sunset(self):
        p = planner.make_plan(ROUTE, FRIENDS, "10:00")
        # 10:43 arrives 12:00, 5h hike ends 17:15, after sunset
        self.assertFalse(p["ok"])

    def test_budget_warning(self):
        poor = [{"name": "Kai", "station": "Grand Central", "fitness": "strong", "budget": 20}]
        p = planner.make_plan(ROUTE, poor, "08:30")
        self.assertEqual(len(p["warnings"]), 1)

    def test_every_plan_time_has_a_source(self):
        p = planner.make_plan(ROUTE, FRIENDS, "08:30", {"H-0843": 70})
        self.assertIn("data date", p["main"]["source"])
        self.assertIn("route.json", p["source"])


if __name__ == "__main__":
    unittest.main()
