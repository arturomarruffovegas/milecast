from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from math import cos, hypot, isfinite, radians

from django.core.cache import cache

from .engine import RISK_LABELS, classify
from .providers import PlanningError, get_json


def location_key(lat, lon):
    # About 100 m, much finer than the provider's forecast grids.
    return round(lat, 3), round(lon, 3)


def corridor_points(checkpoint_sets):
    """Forecast on each route and along both flanks of its corridor."""
    points = set()
    for checkpoints in checkpoint_sets:
        points.update(location_key(c["lat"], c["lon"]) for c in checkpoints)
        stride = max(1, len(checkpoints) // 5)
        width_km = min(16, checkpoints[-1]["mile"] * 1.609344 * 0.075)
        for i in range(0, len(checkpoints), stride):
            before = checkpoints[max(0, i - 1)]
            center = checkpoints[i]
            after = checkpoints[min(i + 1, len(checkpoints) - 1)]
            cos_lat = max(0.1, cos(radians(center["lat"])))
            dx = ((after["lon"] - before["lon"] + 180) % 360 - 180) * cos_lat
            dy = after["lat"] - before["lat"]
            norm = hypot(dx, dy)
            if not norm:
                continue
            for sign in (-1, 1):
                lat = center["lat"] + sign * width_km * dx / (norm * 111)
                lon = center["lon"] - sign * width_km * dy / (norm * 111 * cos_lat)
                points.add(location_key(lat, (lon + 180) % 360 - 180))
    return sorted(points)


def fetch_forecasts(points, start, end):
    start = start.replace(minute=0, second=0, microsecond=0)
    end = end.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    latest = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=16)
    if end >= latest:
        raise PlanningError("The trip extends beyond the available forecast. Choose an earlier departure.")
    date_params = {"start_hour": start.strftime("%Y-%m-%dT%H:00"), "end_hour": end.strftime("%Y-%m-%dT%H:00")}
    keys = {pt: f"wx:{start.timestamp():.0f}:{end.timestamp():.0f}:{pt[0]}:{pt[1]}" for pt in points}
    cached = cache.get_many(keys.values())
    forecasts = {pt: cached[key] for pt, key in keys.items() if key in cached}
    missing = [pt for pt in points if pt not in forecasts]
    for offset in range(0, len(missing), 40):
        batch = missing[offset:offset + 40]
        params = {
            **date_params,
            "latitude": ",".join(str(pt[0]) for pt in batch),
            "longitude": ",".join(str(pt[1]) for pt in batch),
            "hourly": "wind_speed_10m,rain,showers,snowfall",
            "wind_speed_unit": "mph", "precipitation_unit": "inch", "timeformat": "unixtime",
        }
        data = get_json("https://api.open-meteo.com/v1/forecast", params, "Weather forecasts")
        records = data if isinstance(data, list) else [data]
        if len(records) != len(batch) or any("hourly" not in r for r in records):
            raise PlanningError("Weather coverage is incomplete for this corridor. Try a different departure.", 503)
        fresh = {pt: record["hourly"] for pt, record in zip(batch, records)}
        forecasts.update(fresh)
        cache.set_many({keys[pt]: hourly for pt, hourly in fresh.items()}, 1800)
    return forecasts


def at_time(hourly, timestamp):
    """Interpolate instantaneous wind; use the enclosing hour's precipitation."""
    times = hourly["time"]
    hi = bisect_left(times, timestamp)
    if hi == len(times) or timestamp < times[0]:
        raise PlanningError("Forecasts do not cover this trip's full time window.")
    lo = hi if times[hi] == timestamp else max(0, hi - 1)
    wind0, wind1 = hourly["wind_speed_10m"][lo], hourly["wind_speed_10m"][hi]
    rain, showers, snow = (hourly[field][hi] for field in ("rain", "showers", "snowfall"))
    if any(v is None or not isfinite(v) or v < 0 for v in (wind0, wind1, rain, showers, snow)):
        raise PlanningError("The forecast has missing weather observations for this trip. Try another departure.", 503)
    fraction = (timestamp - times[lo]) / (times[hi] - times[lo]) if lo != hi else 0
    return wind0 + fraction * (wind1 - wind0), round(rain + showers, 6), snow


def heatmap(points, forecasts, departure, load):
    start = departure.timestamp()
    result = []
    # Keep the actual peaks alongside the map colors. Two Low hours can have
    # very different readings even though the risk category is identical.
    hourly_peaks = [dict(windMph=0.0, rainInHr=0.0, snowInHr=0.0) for _ in range(49)]
    for lat, lon in points:
        hourly = forecasts[lat, lon]
        risks = []
        for hour, peaks in enumerate(hourly_peaks):
            wind, rain, snow = at_time(hourly, start + hour * 3600)
            risks.append(RISK_LABELS[classify(wind, rain, snow, load)])
            peaks["windMph"] = max(peaks["windMph"], wind)
            peaks["rainInHr"] = max(peaks["rainInHr"], rain)
            peaks["snowInHr"] = max(peaks["snowInHr"], snow)
        result.append({"lat": lat, "lon": lon, "risks": risks})
    return {"start": departure.isoformat(), "points": result, "hourlyPeaks": hourly_peaks}
