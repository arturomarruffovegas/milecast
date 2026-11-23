import json
import math
import re
import threading
import time
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from itertools import accumulate

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


class RouteDistanceLimit(PlanningError):
    pass


def pace_routing_request():
    global _router_clock
    # Both public routing services share a one-request-per-second usage policy.
    with _router_lock:
        time.sleep(max(0.0, 1.0 - (time.monotonic() - _router_clock)))
        _router_clock = time.monotonic()


def request_routes(locations, alternates):
    key = cache_key("truck", locations, alternates)
    stored = caches["routing"].get(key)
    if stored is not None:
        return stored
    pace_routing_request()
    params = {"locations": locations, "costing": "truck", "alternates": alternates, "units": "kilometers"}
    data = get_json("https://valhalla1.openstreetmap.de/route", {"json": json.dumps(params, separators=(",", ":"))},
                    "Truck routing", allow_no_route=True)
    if data.get("error_code") == 154:
        raise RouteDistanceLimit("The truck-routing provider's distance limit was reached.")
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


def bearing(a, b):
    dlon = (b[0] - a[0] + 180) % 360 - 180
    lat = math.radians((a[1] + b[1]) / 2)
    return math.degrees(math.atan2(dlon * math.cos(lat), b[1] - a[1])) % 360


def guide_stops(route):
    """Choose oriented points inside road edges for truck-routing leg boundaries."""
    # Valhalla's public truck endpoint accepts up to 1,500 km per call. Target
    # 1,200 road km per leg, leaving headroom for differences in truck access.
    count = max(2, math.ceil(route["distance"] / 1_200_000))
    coords = decode_polyline(route["geometry"])
    distances = list(accumulate((edge_length_m(a, b) for a, b in zip(coords, coords[1:])), initial=0.0))
    stops = []
    for i in range(1, count):
        j = bisect_left(distances, i * distances[-1] / count)
        a, b = coords[j - 1], coords[j]
        dlon = (b[0] - a[0] + 180) % 360 - 180
        lat = (a[1] + b[1]) / 2
        stops.append({"lat": round(lat, 6), "lon": round((a[0] + dlon / 2 + 180) % 360 - 180, 6),
                      "heading": round(bearing(a, b)) % 360, "heading_tolerance": 45, "node_snap_tolerance": 1})
    return stops


def guide_corridors(endpoints):
    key = cache_key("long-haul-stops", endpoints)
    corridors = caches["default"].get(key)
    if corridors is None:
        encoded = ";".join(f"{p['lon']},{p['lat']}" for p in endpoints)
        pace_routing_request()
        # OSRM supplies candidate junction coordinates only. Each leg's geometry,
        # mileage and travel time subsequently come from Valhalla truck routing.
        data = get_json(f"https://routing.openstreetmap.de/routed-car/route/v1/driving/{encoded}",
                        {"geometries": "polyline6", "overview": "full", "alternatives": 2},
                        "Long-distance corridor search", allow_no_route=True)
        corridors = [guide_stops(r) for r in data.get("routes", [])[:2] if r.get("geometry")]
        caches["default"].set(key, corridors, 3600)
    return corridors


def join_legs(legs):
    # A different carriageway, bridge level or disconnected road must never be
    # drawn as a continuous truck itinerary. Both legs must share the snapped point.
    for a, b in zip(legs, legs[1:]):
        seam = a.coordinates[-1]
        if seam != b.coordinates[0]:
            return None
        before = next((p for p in reversed(a.coordinates) if p != seam), None)
        after = next((p for p in b.coordinates if p != seam), None)
        if before is None or after is None:
            return None
        turn = (bearing(seam, after) - bearing(before, seam) + 180) % 360 - 180
        if abs(turn) > 90:  # Opposing approach/departure would introduce a U-turn.
            return None
    roads = Counter()
    coords = [legs[0].coordinates[0]]
    lengths, seconds = [], []
    for leg in legs:
        roads[leg.name.split(" / ")[0]] += leg.distance_m
        coords.extend(leg.coordinates[1:])
        lengths.extend(leg.edge_lengths)
        seconds.extend(leg.edge_seconds)
    return RoadRoute(" / ".join(name for name, _ in roads.most_common(2)), coords,
                     sum(r.distance_m for r in legs), sum(r.duration_s for r in legs), lengths, seconds)


def add_distinct(route, selected, signatures):
    if selected and route.distance_m > selected[0].distance_m * 1.8:
        return
    cells = {(round(x, 3), round(y, 3)) for x, y in route.coordinates}
    if any(len(cells & other) / max(len(cells), len(other)) > 0.94 for other in signatures):
        return
    signatures.append(cells)
    selected.append(route)


def long_haul_routes(endpoints):
    selected, signatures = [], []
    for stops in guide_corridors(endpoints):
        locations = [endpoints[0], *stops, endpoints[1]]
        options = []
        for start, end in zip(locations, locations[1:]):
            try:
                legs = request_routes([start, end], 2)
            except RouteDistanceLimit:
                break
            if not legs:
                break
            options.append(sorted(legs, key=lambda r: r.duration_s))
        if len(options) != len(locations) - 1:
            continue
        fastest = [legs[0] for legs in options]
        # Try a change to each leg, plus whole-corridor alternate combinations.
        # This keeps the candidate count linear in the number of routing legs.
        choices = [fastest]
        for i, legs in enumerate(options):
            for alternate in legs[1:]:
                choices.append([*fastest[:i], alternate, *fastest[i + 1:]])
        for rank in (1, 2):
            choices.append([legs[min(rank, len(legs) - 1)] for legs in options])
        for legs in sorted(choices, key=lambda rows: sum(r.duration_s for r in rows)):
            route = join_legs(legs)
            if route:
                add_distinct(route, selected, signatures)
            if len(selected) == 3:
                return selected
    if not selected:
        raise PlanningError("The trip exceeds the provider's single-leg limit and a continuous truck itinerary "
                            "could not be assembled. Try planning shorter sections.")
    return selected


def road_routes(origin, destination):
    endpoints = [{k: place[k] for k in ("lat", "lon")} for place in (origin, destination)]
    try:
        primary = request_routes(endpoints, 2)
    except RouteDistanceLimit:
        return long_haul_routes(endpoints)
    if not primary:
        raise PlanningError("No connected truck route was found between these places.")
    selected, signatures = [], []

    for route in primary:
        add_distinct(route, selected, signatures)
    for via in via_locations(*endpoints):
        if len(selected) >= 3:
            break
        try:
            options = request_routes([endpoints[0], via, endpoints[1]], 0)
        except RouteDistanceLimit:
            continue
        except PlanningError as exc:
            if exc.status == 503:
                break  # The native routes can still be assessed.
            raise
        for route in options:
            add_distinct(route, selected, signatures)
    return selected
