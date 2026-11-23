import json
from datetime import datetime, timedelta, timezone

from django.core.exceptions import RequestDataTooBig
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .engine import RISK_LABELS, classify, ranking_key, sample_route, summarize
from .forecast import at_time, corridor_points, fetch_forecasts, heatmap, location_key
from .providers import PlanningError, geocode, place_input, search_places
from .routing import road_routes


@require_GET
def health(request):
    return JsonResponse({"status": "ok"})


@require_GET
def places(request):
    query = request.GET.get("q", "").strip()
    if len(query) > 160:
        return JsonResponse({"error": "Use at most 160 characters for a place search."}, status=400)
    try:
        suggestions = search_places(query) if len(query) >= 3 else []
    except PlanningError as exc:
        return JsonResponse({"error": str(exc)}, status=exc.status)
    return JsonResponse({"places": suggestions})


def inputs(body):
    if not isinstance(body, dict):
        raise PlanningError("Enter your trip details as a JSON object.", 400)
    places = [place_input(body.get(field), field) for field in ("origin", "destination")]
    if all(isinstance(p, str) for p in places) and places[0].casefold() == places[1].casefold():
        raise PlanningError("Choose different places for the origin and destination.")
    load = body.get("loadLb")
    if isinstance(load, bool) or not isinstance(load, (float, int)) or not 0 <= load <= 1_000_000:
        raise PlanningError("Enter a load between 0 and 1,000,000 lb.", 400)
    interval = body.get("intervalMiles")
    if interval not in (10, 25, 50):
        raise PlanningError("Choose a checkpoint interval of 10, 25, or 50 miles.", 400)
    try:
        departure = datetime.fromisoformat(body["departure"])
        if departure.utcoffset() is None:
            raise ValueError
        departure = departure.astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise PlanningError("Enter a departure date and time with a time zone.", 400) from exc
    now = datetime.now(timezone.utc)
    if not now - timedelta(hours=1) <= departure <= now + timedelta(days=13):
        raise PlanningError("Choose a departure within the next 13 days to get a full 48-hour forecast.")
    return places, departure, load, int(interval)


def assess_trip(body):
    places, departure, load, interval = inputs(body)
    origin, destination = map(geocode, places)
    if (origin["lat"], origin["lon"]) == (destination["lat"], destination["lon"]):
        raise PlanningError("Both places resolve to the same location. Choose a different destination.")
    roads = road_routes(origin, destination)
    checkpoint_sets = [
        sample_route(r.coordinates, r.distance_m, r.duration_s, interval, departure,
                     segment_distances=r.edge_lengths, segment_durations=r.edge_seconds)
        for r in roads
    ]
    points = corridor_points(checkpoint_sets)
    last = departure + timedelta(seconds=max(48 * 3600, *(r.duration_s for r in roads)))
    forecasts = fetch_forecasts(points, departure, last)
    routes, ranking = [], []
    for i, (road, checkpoints) in enumerate(zip(roads, checkpoint_sets), 1):
        for cp in checkpoints:
            hourly = forecasts[location_key(cp["lat"], cp["lon"])]
            wind, rain, snow = at_time(hourly, datetime.fromisoformat(cp["eta"]).timestamp())
            cp.update(windMph=wind, rainInHr=rain, snowInHr=snow, risk=classify(wind, rain, snow, load))
        summary = summarize(checkpoints)
        route_id = f"r{i}"
        if not summary["noTravel"]:
            ranking.append((ranking_key(summary, road.duration_s), route_id))
        for cp in checkpoints:
            cp["risk"] = RISK_LABELS[cp["risk"]]
        routes.append({
            "id": route_id, "name": road.name, "geometry": road.coordinates,
            "distanceMiles": checkpoints[-1]["mile"], "durationMinutes": road.duration_s / 60,
            "arrival": checkpoints[-1]["eta"], "risk": RISK_LABELS[summary["maxRisk"]],
            "severeMiles": summary["riskMiles"][3], "highMiles": summary["riskMiles"][2],
            "noTravelMiles": summary["riskMiles"][4], "averageRisk": summary["averageRisk"],
            "checkpoints": checkpoints,
        })
    warnings = []
    if len(routes) < 3:
        warnings.append(f"The router found {len(routes)} distinct truck route{'s' if len(routes) != 1 else ''} for this trip.")
    if not ranking:
        warnings.append("All routes include No Travel conditions. Choose a different departure.")
    return {
        "origin": origin, "destination": destination, "departure": departure.isoformat(),
        "loadLb": load, "intervalMiles": interval, "routes": routes,
        "recommendedId": min(ranking)[1] if ranking else None,
        "heatmap": heatmap(points, forecasts, departure, load), "warnings": warnings,
    }


def plan(request):
    if request.method != "POST":
        response = JsonResponse({"error": "Send trip details with POST."}, status=405)
        response["Allow"] = "POST"
        return response
    if request.content_type != "application/json":
        return JsonResponse({"error": "Send the trip details as application/json."}, status=415)
    try:
        body = json.loads(request.body)
    except (ValueError, RecursionError, RequestDataTooBig):
        return JsonResponse({"error": "Send a valid JSON trip request under 8 KB."}, status=400)
    try:
        result = assess_trip(body)
    except PlanningError as exc:
        return JsonResponse({"error": str(exc)}, status=exc.status)
    return JsonResponse(result, json_dumps_params={"separators": (",", ":")})
