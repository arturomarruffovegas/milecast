import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory

from server.providers import PlanningError, geocode
from server.wsgi import application


def feature(props, xy=(-80.233811, 25.7277552)):
    return {"properties": props, "geometry": {"type": "Point", "coordinates": list(xy)}}


CITY_HALL = feature({
    "name": "Miami City Hall", "housenumber": "3500", "street": "Pan American Drive",
    "city": "Miami", "state": "Florida", "countrycode": "US", "postcode": "33133",
})
MIAMI = feature({"name": "Miami", "state": "Florida", "countrycode": "US"})


class AddressTests(unittest.TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    @patch("server.providers.get_json", return_value={"features": [MIAMI, CITY_HALL, CITY_HALL]})
    def test_suggests_actual_housenumber_and_caches_duplicate_requests(self, upstream):
        for _ in range(2):
            response = application.get_response(self.factory.get("/api/places", {"q": "3500 Pan Amer"}))
            self.assertEqual(response.status_code, 200)
            places = json.loads(response.content)["places"]
            self.assertEqual(places, [{"name": "Miami City Hall, 3500 Pan American Drive, Miami, Florida, 33133, US",
                                       "lat": 25.7277552, "lon": -80.233811}])
        upstream.assert_called_once()

    @patch("server.providers.get_json", return_value={"features": [MIAMI, CITY_HALL]})
    def test_typed_house_number_and_poi_never_select_a_city_center(self, _):
        self.assertEqual(geocode("3500 Pan American Dr, Miami, FL")["lon"], -80.233811)
        self.assertTrue(geocode("Miami City Hall, Miami, FL")["name"].startswith("Miami City Hall"))
        with self.assertRaises(PlanningError):
            geocode("Invented Avenue, Miami, FL")

    def test_complete_us_street_missing_from_photon_has_same_census_suggestion_on_submit(self):
        census = {"result": {"addressMatches": [
            {"matchedAddress": "3500 PAN AMERICAN DR, MIAMI, FL", "coordinates": {"x": -80.234, "y": 25.728}}
        ]}}
        with patch("server.providers.get_json", side_effect=[{"features": [MIAMI]}, census]) as upstream:
            query = "3500 Pan American Dr, Miami, FL"
            suggestions = application.get_response(self.factory.get("/api/places", {"q": query}))
            place = json.loads(suggestions.content)["places"][0]
            self.assertEqual(place["lat"], 25.728)
            self.assertEqual(geocode(query), place)
            self.assertEqual(upstream.call_count, 2)
            self.assertIn("census.gov", upstream.call_args.args[0])

    @patch("server.providers.get_json", return_value={"features": [MIAMI]})
    def test_partial_street_does_not_send_typeahead_to_census(self, upstream):
        response = application.get_response(self.factory.get("/api/places", {"q": "3500 Pan Amer"}))
        self.assertEqual(json.loads(response.content)["places"], [])
        upstream.assert_called_once()
        self.assertIn("photon.komoot.io", upstream.call_args.args[0])

    @patch("server.providers.get_json")
    def test_selected_coordinates_pass_directly_to_router_and_invalid_values_are_rejected(self, upstream):
        place = {"name": "Miami City Hall", "lat": 25.728, "lon": -80.234}
        other = {"name": "Miami Beach City Hall", "lat": 25.792, "lon": -80.135}
        body = {"origin": place, "destination": other, "loadLb": 32000, "intervalMiles": 10,
                "departure": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()}
        with patch("server.views.road_routes", side_effect=PlanningError("No routes")) as router:
            response = application.get_response(self.factory.post("/api/plan", body, content_type="application/json"))
            self.assertEqual(response.status_code, 422)
            router.assert_called_once_with(place, other)
            for bad_lat in (91, True, "25.7", None):
                body["origin"] = dict(place, lat=bad_lat)
                response = application.get_response(self.factory.post("/api/plan", body, content_type="application/json"))
                self.assertEqual(response.status_code, 400)
            self.assertEqual(router.call_count, 1)
        upstream.assert_not_called()
