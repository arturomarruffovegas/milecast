import hashlib
import json
import os
import re
import unicodedata

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
            payload = response.json()
            code = payload.get("error_code")
            if code == 154:
                return payload  # This itinerary needs shorter truck-routing legs.
            if code in (170, 171, 400, 401, 442, 443) or payload.get("code") in ("NoRoute", "NoSegment"):
                return {}
        if response.status_code == 429:
            raise PlanningError(f"{provider} reached its request limit. Try again in a few minutes.", 503)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise PlanningError(f"{provider} is unavailable. Try again shortly.", 503) from exc


def _coordinates(query):
    coordinate = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*", query)
    if coordinate:
        lat, lon = map(float, coordinate.groups())
        if not (-85 <= lat <= 85 and -180 <= lon <= 180):
            raise PlanningError("Enter coordinates as latitude, longitude within the map bounds.")
        return {"name": f"{lat:.4f}, {lon:.4f}", "lat": lat, "lon": lon}


def place_input(value, field):
    if isinstance(value, str) and 2 <= len(value.strip()) <= 160:
        return value.strip()
    if isinstance(value, dict):
        name, lat, lon = (value.get(key) for key in ("name", "lat", "lon"))
        if (isinstance(name, str) and 1 <= len(name.strip()) <= 400
                and type(lat) in (float, int) and -85 <= lat <= 85
                and type(lon) in (float, int) and -180 <= lon <= 180):
            return {"name": name.strip(), "lat": lat, "lon": lon}
    raise PlanningError(f"Choose a valid {field} suggestion or enter 2 to 160 characters.", 400)


STREET_ALIASES = {
    "st": "street", "rd": "road", "ave": "avenue", "av": "avenue", "blvd": "boulevard",
    "dr": "drive", "ln": "lane", "ct": "court", "cir": "circle", "pl": "place",
    "pkwy": "parkway", "hwy": "highway", "ter": "terrace", "trl": "trail",
    "n": "north", "s": "south", "e": "east", "w": "west", "ne": "northeast",
    "nw": "northwest", "se": "southeast", "sw": "southwest",
}
US_STATES = dict(
    AL="Alabama", AK="Alaska", AZ="Arizona", AR="Arkansas", CA="California", CO="Colorado",
    CT="Connecticut", DE="Delaware", DC="District of Columbia", FL="Florida", GA="Georgia",
    HI="Hawaii", ID="Idaho", IL="Illinois", IN="Indiana", IA="Iowa", KS="Kansas",
    KY="Kentucky", LA="Louisiana", ME="Maine", MD="Maryland", MA="Massachusetts",
    MI="Michigan", MN="Minnesota", MS="Mississippi", MO="Missouri", MT="Montana",
    NE="Nebraska", NV="Nevada", NH="New Hampshire", NJ="New Jersey", NM="New Mexico",
    NY="New York", NC="North Carolina", ND="North Dakota", OH="Ohio", OK="Oklahoma",
    OR="Oregon", PA="Pennsylvania", RI="Rhode Island", SC="South Carolina",
    SD="South Dakota", TN="Tennessee", TX="Texas", UT="Utah", VT="Vermont",
    VA="Virginia", WA="Washington", WV="West Virginia", WI="Wisconsin", WY="Wyoming",
    PR="Puerto Rico", VI="United States Virgin Islands", GU="Guam",
)
STATE_CODES = {state: code for code, state in US_STATES.items()}


def _terms(value):
    text = "".join(c for c in unicodedata.normalize("NFKD", value.casefold())
                   if not unicodedata.combining(c))
    return {STREET_ALIASES.get(term, term) for term in re.findall(r"[^\W_]+", text)}


def _house_number(query):
    street = query.partition(",")[0].strip()
    if re.match(r"(route|highway|interstate|i-|sr |us )", street, re.I):
        return None
    match = re.search(r"^(\d+[a-z]?(?:-\d+[a-z]?)?)\s+\S|\s+(\d+[a-z]?)$", street, re.I)
    return (match.group(1) or match.group(2)).casefold() if match else None


def _photon(query):
    key = cache_key("photon", query.casefold())
    features = cache.get(key)
    if features is None:
        response = get_json("https://photon.komoot.io/api/",
                            {"q": query, "limit": 8, "lang": "en"}, "Photon address search")
        features = response.get("features", [])
        if re.fullmatch(r"\d{5}", query):
            features.sort(key=lambda f: f["properties"].get("countrycode") != "US")
        cache.set(key, features, 86400 if features else 600)
    return features


def _place(feature):
    props = feature["properties"]
    address = " ".join(filter(None, [props.get("housenumber"), props.get("street")]))
    parts = (props.get("name"), address, props.get("city") or props.get("district"),
             props.get("state"), props.get("postcode"), props.get("countrycode"))
    lon, lat = feature["geometry"]["coordinates"]
    return {"name": ", ".join(dict.fromkeys(filter(None, parts)))[:400], "lat": lat, "lon": lon}


def _matches_submission(query, feature, number):
    """Fuzzy typeahead results require a literal match before automatic selection."""
    props = feature["properties"]
    if number and number != str(props.get("housenumber", "")).casefold():
        return False
    head, comma, _ = query.partition(",")
    if number and comma:
        address = " ".join(str(props.get(k, "")) for k in ("street", "housenumber", "name"))
        if not _terms(head) <= _terms(address):
            return False
    area = " ".join(str(props.get(k, "")) for k in ("country", "county", "locality", "district"))
    state = STATE_CODES.get(props.get("state"), "") if props.get("countrycode") == "US" else ""
    aliases = {"US": "USA", "GB": "UK"}.get(props.get("countrycode"), "")
    return _terms(query) <= _terms(" ".join([_place(feature)["name"], area, state, aliases]))


def _census_address(query):
    """The Census Geocoder interpolates complete US addresses along TIGER street ranges."""
    key = cache_key("census-address", query.casefold())
    place = cache.get(key)
    if place is None:
        data = get_json("https://geocoding.geo.census.gov/geocoder/locations/onelineaddress",
                        {"address": query, "benchmark": "Public_AR_Current", "format": "json"},
                        "US Census address search")
        matches = data.get("result", {}).get("addressMatches", [])
        place = {}
        if matches:
            match = matches[0]
            xy = match["coordinates"]
            place = {"name": match["matchedAddress"], "lat": xy["y"], "lon": xy["x"]}
        cache.set(key, place, 86400 if place else 600)
    return place


def _complete_us_address(query, number):
    if not number:
        return False
    # Only consult the US street-range matcher after a complete address has
    # been entered, never for an unfinished street name.
    if re.search(r"\b\d{5}(?:-\d{4})?(?:,\s*USA?)?$", query, re.I):
        return True
    tail = re.search(r"\b([A-Za-z]{2})(?:,\s*USA?)?$", query, re.I)
    if not tail or tail[1].upper() not in US_STATES:
        return False
    before_state = query[:tail.start()].strip(", ")
    last_word = before_state.split()[-1].strip(",.").casefold()
    return len(before_state.split()) >= 3 and STREET_ALIASES.get(last_word, last_word) not in STREET_ALIASES.values()


def search_places(query, *, exact_only=False):
    if place := _coordinates(query):
        return [place]
    number = _house_number(query)
    us_address = _complete_us_address(query, number)
    try:
        features = _photon(query)
    except PlanningError:
        if us_address and (place := _census_address(query)):
            return [place]
        raise
    exact, fuzzy, seen = [], [], set()
    for feature in features:
        if number and number != str(feature["properties"].get("housenumber", "")).casefold():
            continue
        place = _place(feature)
        if place["name"] and place["name"] not in seen:
            seen.add(place["name"])
            if _matches_submission(query, feature, number):
                exact.append(place)
            else:
                fuzzy.append(place)
    if not exact and us_address and (place := _census_address(query)):
        exact.append(place)
    return exact if exact_only else (exact + fuzzy)[:6]


def geocode(query):
    if isinstance(query, dict):
        return query  # Already validated by place_input.
    if matches := search_places(query, exact_only=True):
        return matches[0]
    raise PlanningError(f'Could not match “{query}”. Select an address suggestion, add a city and region, or use coordinates.')
