import hashlib
import json
import os
import re

import requests
from django.core.cache import cache


class PlanningError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


def cache_key(label, *parts):
    digest = hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()
    return f"{label}:{digest}"


def get_json(url, params, provider, *, allow_no_route=False):
    try:
        response = requests.get(
            url,
            params=params,
            headers={
                "User-Agent": "Milecast/1.0 (weather-aware trip planner)",
                "X-Client-Id": os.environ.get("RENDER_EXTERNAL_HOSTNAME", "milecast-trip-planner"),
            },
            timeout=(4, 16),
        )
        if allow_no_route and response.status_code in (400, 404):
            code = response.json().get("error_code")
            if code in (154, 170, 171, 400, 401, 442, 443):
                return {}
        if response.status_code == 429:
            raise PlanningError(f"{provider} reached its request limit. Try again in a few minutes.", 503)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise PlanningError(f"{provider} is unavailable. Try again shortly.", 503) from exc


def geocode(query):
    coordinate = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*", query)
    if coordinate:
        lat, lon = map(float, coordinate.groups())
        if not (-85 <= lat <= 85 and -180 <= lon <= 180):
            raise PlanningError("Enter coordinates as latitude, longitude within the map bounds.")
        return {"name": f"{lat:.4f}, {lon:.4f}", "lat": lat, "lon": lon}

    key = cache_key("place", query.casefold())
    place = cache.get(key)
    if place:
        return place
    data = get_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        {"name": query, "count": 1, "language": "en"},
        "Place search",
    )
    if not data.get("results"):
        raise PlanningError(f'Could not find “{query}”. Try a city and state, postal code, or coordinates.')
    result = data["results"][0]
    parts = dict.fromkeys(filter(None, [result["name"], result.get("admin1"), result.get("country_code")]))
    place = {"name": ", ".join(parts), "lat": result["latitude"], "lon": result["longitude"]}
    cache.set(key, place, 86400)
    return place
