import unittest
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.coach_policy_engine import _parse_iso_datetime
from app.services.north_star_metrics_service import _as_datetime
from app.services.projection_outbox_service import _parse_datetime
from app.utils.utc import to_db_utc, to_utc, to_utc_iso, utc_now_db, utc_now_iso, utc_today


class UtcContractTests(unittest.TestCase):
    def test_naive_values_are_explicitly_interpreted_as_utc(self):
        value = datetime(2026, 9, 1, 12, 30, 45, 123456)

        self.assertEqual(to_utc(value).utcoffset(), timedelta(0))
        self.assertEqual(to_db_utc(value), value)
        self.assertEqual(to_utc_iso(value), "2026-09-01T12:30:45.123456Z")

    def test_offset_values_are_converted_instead_of_dropping_the_offset(self):
        value = datetime(
            2026,
            9,
            1,
            20,
            30,
            tzinfo=timezone(timedelta(hours=8)),
        )

        self.assertEqual(to_db_utc(value), datetime(2026, 9, 1, 12, 30))
        self.assertEqual(to_utc_iso(value), "2026-09-01T12:30:00Z")

    def test_now_helpers_keep_database_and_boundary_shapes_distinct(self):
        database_value = utc_now_db()
        boundary_value = utc_now_iso()

        self.assertIsNone(database_value.tzinfo)
        self.assertTrue(boundary_value.endswith("Z"))
        self.assertNotIn("+00:00", boundary_value)
        self.assertIsInstance(utc_today(), date)

    def test_non_datetime_inputs_fail_fast(self):
        with self.assertRaises(TypeError):
            to_db_utc("2026-09-01")  # type: ignore[arg-type]

    def test_service_parsers_share_the_same_offset_conversion(self):
        expected = datetime(2026, 9, 1, 12, 30)

        self.assertEqual(_parse_iso_datetime("2026-09-01T20:30:00+08:00"), expected)
        self.assertEqual(_parse_datetime("2026-09-01T20:30:00+08:00"), expected)

    def test_service_parsers_accept_rfc3339_z(self):
        expected = datetime(2026, 9, 1, 12, 30)

        self.assertEqual(_parse_iso_datetime("2026-09-01T12:30:00Z"), expected)
        self.assertEqual(_parse_datetime("2026-09-01T12:30:00Z"), expected)
        self.assertEqual(
            _as_datetime("2026-09-01T12:30:00Z", zone=ZoneInfo("UTC")),
            expected,
        )


if __name__ == "__main__":
    unittest.main()
