"""Unit tests for the tracked-field history primitives."""

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vault import history
from vault.timestamps import SyncClock, normalize_published


def clock_at(text):
    return SyncClock(datetime.fromisoformat(text))


class RecordTests(unittest.TestCase):
    def test_first_value_uses_the_sync_second(self):
        values = {}
        history.record(values, "hello", clock_at("2024-01-01T12:00:00"))
        self.assertEqual(values, {"2024-01-01T12:00:00": "hello"})

    def test_identical_value_is_not_repeated(self):
        values = {"2024-01-01T12:00:00": 7}
        history.record(values, 7, clock_at("2024-01-01T12:00:05"))
        self.assertEqual(list(values), ["2024-01-01T12:00:00"])

    def test_same_second_change_advances_past_the_existing_key(self):
        values = {"2024-01-01T12:00:00": 7}
        history.record(values, 8, clock_at("2024-01-01T12:00:00"))
        self.assertEqual(values["2024-01-01T12:00:01"], 8)

    def test_stale_clock_still_moves_forward(self):
        values = {"2024-01-01T12:00:09": 7}
        history.record(values, 8, clock_at("2024-01-01T11:00:00"))
        self.assertEqual(list(values), ["2024-01-01T12:00:09", "2024-01-01T12:00:10"])

    def test_one_clock_keeps_every_field_of_a_sync_in_order(self):
        clock = clock_at("2024-01-01T12:00:00")
        collided = {"2024-01-01T12:00:00": "old"}
        fresh = {}
        history.record(collided, "new", clock)
        history.record(fresh, "first", clock)
        self.assertEqual(history.latest_key(fresh), history.latest_key(collided))

    def test_null_and_zero_are_distinct_values(self):
        values = {}
        clock = clock_at("2024-01-01T12:00:00")
        history.record(values, None, clock)
        history.record(values, 0, clock)
        self.assertEqual(list(values.values()), [None, 0])


class NormalizePublishedTests(unittest.TestCase):
    def test_date_only_gains_a_midnight_time(self):
        self.assertEqual(normalize_published("2024-05-06"), "2024-05-06T00:00:00")

    def test_fractional_seconds_and_offsets_are_dropped(self):
        self.assertEqual(normalize_published("2024-05-06T07:08:09.123+02:00"), "2024-05-06T07:08:09")

    def test_unparseable_text_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_published("last tuesday")


if __name__ == "__main__":
    unittest.main()
