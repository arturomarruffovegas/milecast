import json
import math
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass

from django.core.cache import caches

from .engine import edge_length_m
from .providers import PlanningError, cache_key, get_json


@dataclass
class RoadRoute:
    name: str
    coordinates: list
    distance_m: float
    duration_s: float
    edge_lengths: list
    edge_seconds: list


def decode_polyline(encoded):
    """Valhalla's native geometry is a polyline with six decimal places."""
    cursor, lat, lon = 0, 0, 0
    coordinates = []
    while cursor < len(encoded):
        deltas = []
        for _ in range(2):
            value, shift = 0, 0
            while True:
                byte = ord(encoded[cursor]) - 63
                cursor += 1
                value |= (byte & 31) << shift
                if byte < 32:
                    break
                shift += 5
            deltas.append(~(value >> 1) if value & 1 else value >> 1)
        lat += deltas[0]
        lon += deltas[1]
        coordinates.append([lon / 1e6, lat / 1e6])
    return coordinates


def parse_trip(trip):
    # Intermediate waypoints use type=through, so the route remains one leg.
    leg = trip["legs"][0]
    coords = decode_polyline(leg["shape"])
    lengths = [edge_length_m(a, b) for a, b in zip(coords, coords[1:])]
    seconds = [0.0] * len(lengths)
    roads = Counter()
    for maneuver in leg["maneuvers"]:
        start, end = maneuver["begin_shape_index"], maneuver["end_shape_index"]
        section = lengths[start:end]
        geometry_length = sum(section)
        if geometry_length > 0:
            # Apportion the maneuver's reported distance/time over its actual edges.
            fractions = [d / geometry_length for d in section]
            seconds[start:end] = [f * maneuver["time"] for f in fractions]
            if maneuver["length"] > 0:
                lengths[start:end] = [f * maneuver["length"] * 1000 for f in fractions]
        names = maneuver.get("street_names") or []
        if names:
            name = re.sub(r"^(I|US) (\d+)", r"\1-\2", names[0])
            roads[name] += maneuver["length"]
    name = " / ".join(road for road, _ in roads.most_common(2)) or "Connecting roads"
    summary = trip["summary"]
    return RoadRoute(name, coords, summary["length"] * 1000, summary["time"], lengths, seconds)


_router_clock = 0.0
_router_lock = threading.Lock()


def request_routes(locations, alternates):
    global _router_clock
    key = cache_key("truck", locations, alternates)
    stored = caches["routing"].get(key)
    if stored is not None:
        return stored
    # Space public demo requests even when multiple users plan trips together.
    with _router_lock:
        time.sleep(max(0.0, 1.0 - (time.monotonic() - _router_clock)))
        _router_clock = time.monotonic()
    params = {"locations": locations, "costing": "truck", "alternates": alternates, "units": "kilometers"}
    data = get_json("https://valhalla1.openstreetmap.de/route", {"json": json.dumps(params, separators=(",", ":"))},
                    "Truck routing", allow_no_route=True)
    trips = [data["trip"], *(a["trip"] for a in data.get("alternates", []))] if "trip" in data else []
    routes = [parse_trip(trip) for trip in trips if trip["summary"]["length"] > 0]
    # Bound large route entries separately from weather and geocoding records.
    if sum(len(r.coordinates) for r in routes) < 45000:
        caches["routing"].set(key, routes, 3600)
    return routes


def via_locations(origin, destination):
    """Search both sides of the corridor for a through point on a major road."""
    lat = (origin["lat"] + destination["lat"]) / 2
    lon_delta = (destination["lon"] - origin["lon"] + 180) % 360 - 180
    cos_lat = max(0.1, math.cos(math.radians(lat)))
    dx = lon_delta * 111 * cos_lat
    dy = (destination["lat"] - origin["lat"]) * 111
    length = math.hypot(dx, dy)
    if length == 0:
        return
    width = max(0.3, min(42, 0.12 * length))
    for fraction, side in ((0.5, 1), (0.5, -1), (0.32, 1), (0.68, -1)):
        lat = origin["lat"] + (fraction * dy + side * width * dx / length) / 111
        lon = origin["lon"] + (fraction * dx - side * width * dy / length) / (111 * cos_lat)
        yield {"type": "through", "lat": round(lat, 5), "lon": round((lon + 180) % 360 - 180, 5),
               "radius": min(8000, max(300, int(width * 150))),
               "search_filter": {"min_road_class": "secondary", "exclude_ramp": True}}


def road_routes(origin, destination):
    endpoints = [{k: place[k] for k in ("lat", "lon")} for place in (origin, destination)]
    primary = request_routes(endpoints, 2)
    if not primary:
        raise PlanningError("No connected truck route was found between these places.")
    selected, signatures = [], []

    def include(route):
        if route.distance_m > primary[0].distance_m * 1.8:
            return
        # Compare the occupied road cells, so a minor local detour doesn't count
        # as another option. Native alternates and via results use the same test.
        cells = {(round(x, 3), round(y, 3)) for x, y in route.coordinates}
        if any(len(cells & other) / max(len(cells), len(other)) > 0.94 for other in signatures):
            return
        signatures.append(cells)
        selected.append(route)

    for route in primary:
        include(route)
    for via in via_locations(*endpoints):
        if len(selected) >= 3:
            break
        try:
            options = request_routes([endpoints[0], via, endpoints[1]], 0)
        except PlanningError as exc:
            if exc.status == 503:
                break  # The native routes can still be assessed.
            raise
        for route in options:
            include(route)
    return selected
