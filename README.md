# Milecast

Milecast compares truck routes using hourly wind, rain, snowfall, load weight, and estimated arrival times. The React map lets you inspect checkpoints and explore 48 hours of weather along the corridor. Django serves the planner API and the compiled frontend from one web service.

## Run locally

Use Python 3.12 and Node.js 22. Run these commands from the repository root in an activated Python virtual environment.

```sh
python -m pip install -r requirements.txt
npm ci --prefix frontend
npm run build --prefix frontend
python manage.py collectstatic --noinput
python manage.py runserver
```

Open [the local planner](http://127.0.0.1:8000). For frontend development, run `npm run dev --prefix frontend` in a second terminal and open the Vite URL. Run the automated tests with `python -m unittest discover -v`.

## Route and forecast calculations

- Type a street address, business, city, or ZIP code into either field and select a suggestion. You can also submit a full address or latitude and longitude directly. Departure time uses the browser’s local time zone.
- Valhalla supplies truck routes, road geometry, and maneuver times. When its native alternatives fall short, the planner tries intermediate points on either side of the corridor. For trips beyond the provider’s single-leg distance limit, OSRM suggests junctions and Valhalla calculates each truck leg. Joined legs must share their snapped road endpoint.
- The backend samples road miles at the selected spacing and includes both endpoints. It interpolates ETA within each maneuver, interpolates hourly wind, and uses the precipitation total for the hour containing the ETA.
- Each checkpoint receives the worst applicable wind, rain, or snow risk after the load adjustment. Each adjacent checkpoint accounts for half of the distance between them. The planner excludes routes with No Travel conditions, then minimizes Severe miles, High miles, average risk, and driving time in that order.
- The weather layer interpolates risk between forecast locations on and beside the routes. The slider shows the corridor at one time, together with peak wind, rain, and snowfall across the sampled locations for that hour. Checkpoint markers show risk at the truck’s own ETA.
- The initial Chicago–Madison example uses a saved forecast. **Calculate routes** requests a forecast for the form’s departure time. Upstream coverage and free API quotas can affect availability.

## Deployment

Use a Render Python web service on the Free instance type. The build command is `bash build.sh`, the start command is `gunicorn server.wsgi:application --workers 2 --threads 4 --timeout 120`, and the health endpoint is `/api/health`. The application uses in-memory caches and requires no database or API keys.

Map data come from [OpenStreetMap contributors](https://www.openstreetmap.org/copyright). Routing uses [Valhalla](https://valhalla.github.io/valhalla/) and [OSRM](https://project-osrm.org/). Forecasts come from [Open-Meteo](https://open-meteo.com/). Place lookup uses [Photon](https://photon.komoot.io/) and the [U.S. Census Geocoder](https://geocoding.geo.census.gov/geocoder/). The saved example uses [GeoNames](https://www.geonames.org/) city coordinates.
