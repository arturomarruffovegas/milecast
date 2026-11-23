import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from server.routing import RoadRoute
from server.views import assess_trip


class PlannerTests(unittest.TestCase):
    def test_no_travel_is_never_recommended_and_a_missing_alternate_is_disclosed(self):
        origin = {"name": "Origin", "lat": 44, "lon": -86}
        destination = {"name": "Destination", "lat": 44, "lon": -87}
        road = RoadRoute("Main Road", [[-86, 44], [-87, 44]], 80000, 3600, [80000], [3600])
        departure = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
        params = dict(origin="Origin", destination="Destination", departure=departure.isoformat(),
                      loadLb=32000, intervalMiles=25)

        def forecasts(points, start, end):
            count = int((end - start).total_seconds() / 3600) + 2
            hourly = {
                "time": [start.timestamp() + h * 3600 for h in range(count)],
                "wind_speed_10m": [48] * count, "rain": [0] * count,
                "showers": [0] * count, "snowfall": [0] * count,
            }
            return dict.fromkeys(points, hourly)

        with patch("server.views.geocode", side_effect=[origin, destination]), \
             patch("server.views.road_routes", return_value=[road]), \
             patch("server.views.fetch_forecasts", side_effect=forecasts):
            plan = assess_trip(params)
        self.assertIsNone(plan["recommendedId"])
        self.assertEqual(plan["routes"][0]["risk"], "No Travel")
        self.assertAlmostEqual(plan["routes"][0]["noTravelMiles"], 80000 / 1609.344)
        self.assertTrue(any("1 distinct" in warning for warning in plan["warnings"]))
        self.assertTrue(all(p["risks"] == ["No Travel"] * 49 for p in plan["heatmap"]["points"]))
