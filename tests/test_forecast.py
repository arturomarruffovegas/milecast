import unittest
from datetime import datetime, timezone

from server.forecast import at_time, heatmap
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

    def test_corridor_peaks_track_each_hour_even_when_weather_stays_low(self):
        points = [(42.0, -89.0), (42.1, -89.1)]
        forecasts = {}
        for index, point in enumerate(points):
            forecasts[point] = {
                "time": [h * 3600 for h in range(49)],
                "wind_speed_10m": [6.0 + index + h / 4 for h in range(49)],
                "rain": [0.04 * (1 - index)] * 49,
                "showers": [0.02] * 49,
                "snowfall": [0.05 * index] * 49,
            }
        result = heatmap(points, forecasts, datetime.fromtimestamp(0, timezone.utc), 100000)
        self.assertEqual(result["hourlyPeaks"][0], {"windMph": 7, "rainInHr": 0.06, "snowInHr": 0.05})
        self.assertEqual(result["hourlyPeaks"][48]["windMph"], 19)
        self.assertTrue(all(point["risks"] == ["Low"] * 49 for point in result["points"]))
