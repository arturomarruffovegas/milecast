"""Road checkpoints, weather exposure and route ranking. Distances are statute miles."""

from bisect import bisect_right
from datetime import timedelta, timezone
from itertools import accumulate
from math import asin, cos, floor, isclose, isfinite, radians, sin, sqrt


METERS_PER_MILE = 1609.344
RISK_LABELS = ("Low", "Moderate", "High", "Severe", "No Travel")


def classify(wind_mph, rain_in_hr, snow_in_hr, load_lb):
    """Return the highest applicable risk. Shared rain/snow boundaries round up."""
    values = (wind_mph, rain_in_hr, snow_in_hr, load_lb)
    if any(value is None or not isfinite(value) or value < 0 for value in values):
        raise ValueError("Risk requires nonnegative, finite weather readings and load.")

    wind = bisect_right((25, 35, 45, 55), wind_mph)
    if (wind == 3 and load_lb > 30000) or (wind == 2 and load_lb > 40000):
        wind += 1
    rain = 4 if rain_in_hr > 1 else bisect_right((0.10, 0.25, 0.50), rain_in_hr)
    snow = 4 if snow_in_hr > 3 else bisect_right((0.5, 1, 2), snow_in_hr)
    return max(wind, rain, snow)


def edge_length_m(a, b):
    """Great-circle meters for one short edge of a road geometry."""
    lon_a, lat_a = map(radians, a)
    lon_b, lat_b = map(radians, b)
    h = sin((lat_b - lat_a) / 2) ** 2
    h += cos(lat_a) * cos(lat_b) * sin((lon_b - lon_a) / 2) ** 2
    return 12742017.6 * asin(sqrt(min(1, h)))


def _cumulative(weights, total):
    """Scale edge weights to the whole-route total reported by the router."""
    cumulative = list(accumulate(weights, initial=0.0))
    if cumulative[-1] <= 0:
        raise ValueError("The route has no measurable road geometry.")
    scale = total / cumulative[-1]
    return [value * scale for value in cumulative]


def _usable_weights(weights, edge_count):
    return (
        weights is not None and len(weights) == edge_count
        and all(value is not None and isfinite(value) and value >= 0 for value in weights)
        and any(weights)
    )


def sample_route(coordinates, distance_m, duration_s, spacing_miles, departure,
                 *, segment_distances=None, segment_durations=None):
    """Sample a GeoJSON route by road mile and interpolate ETAs along its segments.

    Annotation arrays align one-to-one with edges of the full geometry. If an
    annotation is unavailable, geometry weights estimate distance and distance
    weights estimate duration. Both always match the provider's route totals.
    """
    if len(coordinates) < 2 or not isfinite(distance_m) or distance_m <= 0:
        raise ValueError("A route needs at least two coordinates and a positive distance.")
    if not isfinite(duration_s) or duration_s < 0 or spacing_miles not in (10, 25, 50):
        raise ValueError("Invalid duration or checkpoint spacing.")
    if departure.utcoffset() is None:
        raise ValueError("Departure must include a time zone.")

    edge_count = len(coordinates) - 1
    if not _usable_weights(segment_distances, edge_count):
        segment_distances = [edge_length_m(a, b) for a, b in zip(coordinates, coordinates[1:])]
    distances = _cumulative(segment_distances, distance_m)
    if not _usable_weights(segment_durations, edge_count):
        segment_durations = segment_distances
    times = _cumulative(segment_durations, duration_s)

    total_miles = distance_m / METERS_PER_MILE
    miles = [i * spacing_miles for i in range(1 + floor(total_miles / spacing_miles))]
    if len(miles) > 1 and isclose(miles[-1], total_miles, abs_tol=1e-7, rel_tol=0):
        miles.pop()
    miles.append(total_miles)

    departure_utc = departure.astimezone(timezone.utc)
    checkpoints = []
    for number, mile in enumerate(miles):
        if number == 0:
            (lon, lat), seconds = coordinates[0], 0
        elif number == len(miles) - 1:
            (lon, lat), seconds = coordinates[-1], duration_s
        else:
            meters = mile * METERS_PER_MILE
            edge = bisect_right(distances, meters) - 1
            fraction = (meters - distances[edge]) / (distances[edge + 1] - distances[edge])
            lon_a, lat_a = coordinates[edge]
            lon_b, lat_b = coordinates[edge + 1]
            # Use the shorter longitude arc even on roads crossing the antimeridian.
            lon_delta = ((lon_b - lon_a + 180) % 360) - 180
            lon = ((lon_a + fraction * lon_delta + 180) % 360) - 180
            lat = lat_a + fraction * (lat_b - lat_a)
            seconds = times[edge] + fraction * (times[edge + 1] - times[edge])
        eta = departure_utc + timedelta(seconds=seconds)
        checkpoints.append({"mile": mile, "lat": lat, "lon": lon, "eta": eta.isoformat(timespec="seconds")})
    return checkpoints


def summarize(checkpoints):
    """Attribute road miles to the nearest checkpoint's weather on either side."""
    if len(checkpoints) < 2:
        raise ValueError("A route needs departure and arrival checkpoints.")
    risk_miles = [0.0] * len(RISK_LABELS)
    for start, end in zip(checkpoints, checkpoints[1:]):
        miles = end["mile"] - start["mile"]
        if not isfinite(miles) or miles < 0:
            raise ValueError("Checkpoint miles must be finite and ordered.")
        for checkpoint in (start, end):
            risk = checkpoint["risk"]
            if not isinstance(risk, int) or risk not in range(len(risk_miles)):
                raise ValueError("Checkpoint has an invalid risk level.")
            risk_miles[risk] += miles / 2
    total = sum(risk_miles)
    if total <= 0:
        raise ValueError("Cannot score a zero-length route.")
    max_risk = max(checkpoint["risk"] for checkpoint in checkpoints)
    return {
        "riskMiles": risk_miles,
        "averageRisk": sum(risk * miles for risk, miles in enumerate(risk_miles)) / total,
        "maxRisk": max_risk,
        "noTravel": max_risk == 4,
    }


def ranking_key(summary, duration_s):
    """Sort ascending. No Travel disqualifies a route whenever a viable one exists."""
    _, _, high, severe, blocked = summary["riskMiles"]
    # Ignore floating-point noise when comparing physically equivalent exposures.
    return (summary["noTravel"], round(blocked, 6), round(severe, 6),
            round(high, 6), round(summary["averageRisk"], 9), duration_s)
