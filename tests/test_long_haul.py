import unittest
from unittest.mock import Mock, patch

from server.providers import PlanningError, get_json
from server.routing import RoadRoute, RouteDistanceLimit, join_legs, road_routes


def leg(name, coordinates, distance, seconds):
    count = len(coordinates) - 1
    return RoadRoute(name, coordinates, distance, seconds, [distance / count] * count, [seconds / count] * count)


class LongHaulRoutingTests(unittest.TestCase):
    def test_provider_distance_limit_survives_transport(self):
        response = Mock(status_code=400)
        response.json.return_value = {"error_code": 154, "error": "Path distance exceeds the max distance limit"}
        with patch("server.providers.requests.get", return_value=response):
            self.assertEqual(get_json("https://example.org", {}, "Routing", allow_no_route=True)["error_code"], 154)

    def test_join_preserves_only_real_road_edges_and_their_timings(self):
        a = leg("A", [[0, 0], [1, 0], [2, 0]], 900000, 11000)
        b = leg("B", [[2, 0], [3, 0]], 700000, 14000)
        result = join_legs([a, b])
        self.assertEqual(result.coordinates, [[0, 0], [1, 0], [2, 0], [3, 0]])
        self.assertEqual(result.edge_seconds, [5500, 5500, 14000])
        self.assertEqual(result.edge_lengths, [450000, 450000, 700000])
        self.assertEqual(result.duration_s, 25000)
        self.assertEqual(result.distance_m, 1600000)
        self.assertIsNone(join_legs([a, leg("Wrong lane", [[2, 0.001], [3, 0]], 700000, 14000)]))
        self.assertIsNone(join_legs([a, leg("Opposite direction", [[2, 0], [1, 0]], 700000, 14000)]))

    def test_over_limit_trip_uses_three_distinct_truck_alternatives(self):
        origin = {"lat": 0, "lon": 0}
        destination = {"lat": 0, "lon": 4}
        via = {"lat": 0, "lon": 2}
        west = [leg("A", [[0, 0], [0.5, y], [1, y], [1.5, 0], [2, 0]], 950000, t)
                for y, t in ((0, 18000), (0.2, 18200), (-0.2, 18400))]
        east = [leg("B", [[2, 0], [3, 0], [4, 0]], 900000, 19000)]
        with patch("server.routing.guide_corridors", return_value=[[via]]), \
             patch("server.routing.request_routes", side_effect=[RouteDistanceLimit("limit"), west, east]) as router:
            routes = road_routes(origin, destination)
        self.assertEqual(router.call_count, 3)
        self.assertEqual([r.duration_s for r in routes], [37000, 37200, 37400])
        self.assertEqual(len({tuple(map(tuple, r.coordinates)) for r in routes}), 3)
        self.assertTrue(all(len(r.edge_seconds) == len(r.coordinates) - 1 for r in routes))

    def test_unresolved_long_trip_reports_limit_and_never_invents_geometry(self):
        stops = [[{"lat": 0, "lon": 2}]]
        with patch("server.routing.guide_corridors", return_value=stops), \
             patch("server.routing.request_routes", side_effect=[RouteDistanceLimit("limit"), []]):
            with self.assertRaisesRegex(PlanningError, "single-leg limit"):
                road_routes({"lat": 0, "lon": 0}, {"lat": 0, "lon": 4})
