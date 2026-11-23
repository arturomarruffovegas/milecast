from datetime import datetime, timedelta, timezone
import unittest

from server.engine import METERS_PER_MILE, classify, ranking_key, sample_route, summarize


class WeatherRiskTests(unittest.TestCase):
    def test_wind_edges_and_strict_load_limits(self):
        cases = (
            (24.99, 41000, 0), (25, 41000, 1), (34.99, 41000, 1),
            (35, 40000, 2), (35, 40001, 3), (44.99, 40001, 3),
            (45, 30000, 3), (45, 30001, 4), (54.99, 1500, 3), (55, 0, 4),
        )
        for wind, load, expected in cases:
            with self.subTest(wind=wind, load=load):
                self.assertEqual(classify(wind, 0, 0, load), expected)

    def test_precipitation_thresholds_and_worst_condition(self):
        rain_cases = ((0.099, 0), (0.10, 1), (0.25, 2), (0.50, 3), (1, 3), (1.001, 4))
        snow_cases = ((0.499, 0), (0.5, 1), (1, 2), (2, 3), (3, 3), (3.001, 4))
        for rate, risk in rain_cases:
            self.assertEqual(classify(0, rate, 0, 0), risk)
        for rate, risk in snow_cases:
            self.assertEqual(classify(0, 0, rate, 0), risk)
        self.assertEqual(classify(26, .3, 3.01, 1000), 4)

    def test_unknown_observations_are_not_scored_as_low(self):
        for wind in (None, float("nan"), float("inf"), -1):
            with self.assertRaises(ValueError):
                classify(wind, 0, 0, 0)


class SamplingTests(unittest.TestCase):
    departure = datetime(2026, 11, 23, 23, 30, tzinfo=timezone(timedelta(hours=-5)))
    coordinates = [[-90, 36], [-89, 36], [-88, 36]]

    def test_eta_interpolates_road_durations_and_converts_to_utc(self):
        checkpoints = sample_route(self.coordinates, 40 * METERS_PER_MILE, 3600, 10,
                                   self.departure, segment_distances=[30, 10],
                                   segment_durations=[900, 2700])
        self.assertEqual([p["mile"] for p in checkpoints], [0, 10, 20, 30, 40])
        self.assertAlmostEqual(checkpoints[1]["lon"], -90 + 1/3)
        self.assertEqual([p["eta"] for p in checkpoints], [
            "2026-11-24T04:30:00+00:00", "2026-11-24T04:35:00+00:00",
            "2026-11-24T04:40:00+00:00", "2026-11-24T04:45:00+00:00",
            "2026-11-24T05:30:00+00:00",
        ])

    def test_geometry_fallback_keeps_short_final_interval(self):
        checkpoints = sample_route(self.coordinates, 55 * METERS_PER_MILE, 3300, 25,
                                   self.departure, segment_distances=[100])
        self.assertEqual([p["mile"] for p in checkpoints], [0, 25, 50, 55])
        start, second = [datetime.fromisoformat(p["eta"]) for p in checkpoints[:2]]
        self.assertEqual(second - start, timedelta(minutes=25))

    def test_trip_shorter_than_spacing_still_includes_endpoints(self):
        checkpoints = sample_route(self.coordinates, METERS_PER_MILE / 5, 60, 50, self.departure)
        self.assertEqual(len(checkpoints), 2)
        self.assertEqual(checkpoints[0]["lon"], -90)
        self.assertEqual(checkpoints[-1]["lon"], -88)

    def test_duplicate_geometry_points_do_not_divide_by_zero(self):
        checkpoints = sample_route([[0, 1], [0, 1], [1, 1], [1, 1], [2, 1]],
                                   20 * METERS_PER_MILE, 60, 10, self.departure)
        self.assertAlmostEqual(checkpoints[1]["lon"], 1)


class RouteSummaryTests(unittest.TestCase):
    def test_endpoint_risk_and_short_last_segment_are_weighted_by_road_miles(self):
        summary = summarize([{"mile": 0, "risk": 1}, {"mile": 25, "risk": 3},
                             {"mile": 27, "risk": 4}])
        self.assertEqual(summary["riskMiles"], [0, 12.5, 0, 13.5, 1])
        self.assertEqual(summary["maxRisk"], 4)
        self.assertTrue(summary["noTravel"])
        self.assertAlmostEqual(summary["averageRisk"], (12.5 + 13.5 * 3 + 4) / 27)

    def test_recommendation_uses_exposure_before_travel_time(self):
        def key(miles, duration):
            average = sum(r * m for r, m in enumerate(miles)) / sum(miles)
            return ranking_key({"riskMiles": miles, "averageRisk": average,
                                "noTravel": miles[-1] > 0}, duration)

        order = [
            key([10, 0, 0, 0, 0], 10), key([10, 0, 0, 0, 0], 20),
            key([0, 1, 0, 0, 0], 9), key([500, 0, 1, 0, 0], 8),
            key([500, 0, 0, 1, 0], 7), key([100, 0, 0, 0, .1], 5),
            key([100, 0, 0, 0, 1], 2),
        ]
        self.assertEqual(order, sorted(reversed(order)))


if __name__ == "__main__":
    unittest.main()
