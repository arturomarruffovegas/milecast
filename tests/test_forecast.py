import unittest

from server.forecast import at_time
from server.providers import PlanningError


class HourlyWeatherTests(unittest.TestCase):
    def setUp(self):
        self.hourly = {
            "time": [0, 3600, 7200],
            "wind_speed_10m": [20, 30, 40],
            "rain": [0, 0.08, 0.9],
            "showers": [0, 0.02, 0.2],
            "snowfall": [0, 0.6, 0.2],
        }

    def test_mid_hour_wind_interpolates_and_precipitation_uses_enclosing_bucket(self):
        self.assertEqual(at_time(self.hourly, 1800), (25, 0.10, 0.6))
        self.assertEqual(at_time(self.hourly, 3600), (30, 0.10, 0.6))
        self.assertEqual(at_time(self.hourly, 5400), (35, 1.10, 0.2))

    def test_outside_coverage_and_missing_readings_are_not_reported_as_low(self):
        for timestamp in (-1, 7201):
            with self.subTest(timestamp=timestamp), self.assertRaises(PlanningError):
                at_time(self.hourly, timestamp)
        self.hourly["snowfall"][1] = None
        with self.assertRaises(PlanningError):
            at_time(self.hourly, 1800)
