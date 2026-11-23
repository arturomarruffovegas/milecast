import React, { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { displayTime, journeyTime, riskColors, riskLevels, routeColors } from "./format";
import "./map.css";

const colorByRisk = Object.fromEntries(riskLevels.map((risk, index) => [risk, riskColors[index]]));
const rgbColors = riskColors.map(hex => hex.slice(1).match(/../g).map(byte => parseInt(byte, 16)));
const tileUrl = import.meta.env.VITE_TILE_URL || "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const tileAttribution = import.meta.env.VITE_TILE_ATTRIBUTION ||
  '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a> · <a href="https://www.openstreetmap.org/fixthemap" target="_blank" rel="noreferrer">Fix the map</a>';
const formatMiles = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });

// Each tile stays in Leaflet's projected tile grid throughout pan and zoom.
// Changing hours repaints the existing canvases without reloading any map tiles.
class ForecastLayer extends L.GridLayer {
  constructor(points, radiusMeters) {
    super({ pane: "forecast", noWrap: true, keepBuffer: 1 });
    this.points = points;
    this.radiusMeters = radiusMeters;
    this.hour = 0;
    this.tiles = new Map();
    this.on("tileunload", ({ tile }) => this.tiles.delete(tile));
  }

  createTile(coords) {
    const tile = document.createElement("canvas");
    tile.width = tile.height = this.getTileSize().x;
    this.tiles.set(tile, coords);
    this.paint(tile, coords);
    return tile;
  }

  setHour(hour) {
    this.hour = hour;
    this.tiles.forEach((coords, tile) => this.paint(tile, coords));
  }

  paint(tile, coords) {
    const ctx = tile.getContext("2d");
    const size = tile.width;
    const step = 8;
    // A one-cell gutter lets neighbouring tiles interpolate across the same edge.
    const width = size / step + 2;
    const scores = new Float32Array(width * width);
    const weights = new Float32Array(width * width);
    const coverage = new Float32Array(width * width);
    for (const sample of this.points) {
      const risk = riskLevels.indexOf(sample.risks[this.hour]);
      if (risk < 0) continue;
      const projected = L.CRS.EPSG3857.latLngToPoint(L.latLng(sample.lat, sample.lon), coords.z);
      const x = (projected.x - coords.x * size) / step + 0.5;
      const y = (projected.y - coords.y * size) / step + 0.5;
      const metersPerPixel = 156543.03 * Math.cos(sample.lat * Math.PI / 180) / 2 ** coords.z;
      const radius = Math.max(1.25, this.radiusMeters / metersPerPixel / step);
      for (let row = Math.max(0, Math.ceil(y - radius)); row <= Math.min(width - 1, y + radius); row++) {
        for (let col = Math.max(0, Math.ceil(x - radius)); col <= Math.min(width - 1, x + radius); col++) {
          const d2 = ((col - x) ** 2 + (row - y) ** 2) / radius ** 2;
          if (d2 >= 1) continue;
          const fade = (1 - d2) ** 2;
          const weight = fade / (0.006 + d2);
          const index = row * width + col;
          scores[index] += weight * risk;
          weights[index] += weight;
          coverage[index] = Math.max(coverage[index], fade);
        }
      }
    }
    const field = document.createElement("canvas");
    field.width = field.height = width;
    const fieldCtx = field.getContext("2d");
    const pixels = fieldCtx.createImageData(width, width);
    for (let index = 0; index < weights.length; index++) {
      if (!weights[index]) continue;
      const score = Math.min(riskLevels.length - 1, scores[index] / weights[index]);
      const low = Math.floor(score), high = Math.ceil(score);
      const mix = score - low;
      for (let channel = 0; channel < 3; channel++) {
        pixels.data[index * 4 + channel] = rgbColors[low][channel] * (1 - mix) + rgbColors[high][channel] * mix;
      }
      pixels.data[index * 4 + 3] = (98 + 14 * score) * coverage[index];
    }
    fieldCtx.putImageData(pixels, 0, 0);
    ctx.clearRect(0, 0, size, size);
    ctx.drawImage(field, 1, 1, width - 2, width - 2, 0, 0, size, size);
  }
}

function node(tag, className, value) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (value !== undefined) element.textContent = value;
  return element;
}

function popupContent(title, risk, rows) {
  const card = node("section", "route-map-popup");
  card.append(node("strong", "route-map-popup-title", title));
  const status = node("span", "route-map-risk", risk);
  status.style.setProperty("--risk", colorByRisk[risk]);
  card.append(status);
  const stats = node("dl", "route-map-popup-stats");
  rows.forEach(([label, value]) => stats.append(node("dt", "", label), node("dd", "", value)));
  card.append(stats);
  return card;
}

function routeSummary(route) {
  return popupContent(route.name, route.risk, [
    ["Distance", formatMiles.format(route.distanceMiles) + " mi"],
    ["Drive time", journeyTime(route.durationMinutes)],
    ["Arrival", displayTime(route.arrival, true)],
    ["High / Severe miles", formatMiles.format(route.highMiles) + " / " + formatMiles.format(route.severeMiles)],
    ["No Travel miles", formatMiles.format(route.noTravelMiles)],
  ]);
}

function checkpointDetails(point, title) {
  return popupContent(title || "Checkpoint · Mile " + formatMiles.format(point.mile), point.risk, [
    ["ETA", displayTime(point.eta, true)],
    ["Wind", formatMiles.format(point.windMph) + " mph"],
    ["Rain", point.rainInHr.toFixed(2) + " in/hr"],
    ["Snow", point.snowInHr.toFixed(2) + " in/hr"],
  ]);
}

function fitRoutes(map, bounds) {
  if (!bounds?.isValid()) return;
  const { x: width, y: height } = map.getSize();
  const side = width < 450 ? 27 : 55;
  map.fitBounds(bounds, {
    paddingTopLeft: [side, Math.min(64, height * 0.16)],
    paddingBottomRight: [side, Math.min(102, height * 0.25)], maxZoom: 13, animate: false,
  });
}

function bindAction(layer, activate) {
  layer.on("click", activate);
  layer.on("keypress", event => {
    if (event.originalEvent.key === "Enter" || event.originalEvent.key === " ") {
      L.DomEvent.preventDefault(event.originalEvent);
      activate(event);
    }
  });
}

export default function RouteMap({ plan, selectedId, onSelect, showHeat, hour, fitSignal }) {
  const container = useRef(null);
  const mapRef = useRef(null);
  const routeViews = useRef([]);
  const forecast = useRef(null);
  const boundsRef = useRef(null);
  const popupRef = useRef(null);
  const currentSelection = useRef(selectedId);
  const select = useRef(onSelect);
  currentSelection.current = selectedId;
  select.current = onSelect;

  useEffect(() => {
    const map = L.map(container.current, {
      center: [38.5, -97.5], zoom: 4, zoomControl: false,
      zoomSnap: 0.1, minZoom: 2, maxZoom: 19, attributionControl: true,
    });
    mapRef.current = map;
    map.attributionControl.setPrefix(false);
    const pane = map.createPane("forecast");
    pane.style.zIndex = "350";
    pane.style.pointerEvents = "none";
    L.tileLayer(tileUrl, { attribution: tileAttribution, maxZoom: 19, className: "route-map-basemap" }).addTo(map);
    L.control.zoom({ position: "topright" }).addTo(map);
    L.control.scale({ metric: false, maxWidth: 80 }).addTo(map);
    const observer = new ResizeObserver(() => {
      map.invalidateSize({ pan: false });
    });
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!plan || !map) return;
    const layers = L.layerGroup().addTo(map);
    const bounds = L.latLngBounds([]);
    function openCard(id, location, content) {
      const popup = L.popup({
        className: "route-map-popup-wrap", maxWidth: 250,
        autoPanPaddingTopLeft: [15, 60], autoPanPaddingBottomRight: [15, 88],
      }).setLatLng(location).setContent(content).openOn(map);
      popupRef.current = { id, popup };
      select.current?.(id);
    }
    routeViews.current = plan.routes.map((route, index) => {
      const color = routeColors[index % routeColors.length];
      const latLngs = route.geometry.map(([lon, lat]) => [lat, lon]);
      const casing = L.polyline(latLngs, { color: "#fff", interactive: false }).addTo(layers);
      const line = L.polyline(latLngs, { color, bubblingMouseEvents: false }).addTo(layers);
      // The wide transparent path gives the road an easy touch target.
      const hit = L.polyline(latLngs, {
        color, opacity: 0.001, weight: 14, bubblingMouseEvents: false,
      }).addTo(layers);
      bounds.extend(line.getBounds());
      bindAction(hit, event => openCard(route.id, event.latlng, routeSummary(route)));
      const points = route.checkpoints.slice(1, -1).map(point => {
        const dot = L.circleMarker([point.lat, point.lon], {
          color: "white", fillColor: colorByRisk[point.risk], fillOpacity: 1, bubblingMouseEvents: false,
        }).addTo(layers);
        dot.bindTooltip("Mile " + formatMiles.format(point.mile) + " · " + point.risk,
          { direction: "top", offset: [0, -5] });
        bindAction(dot, () => openCard(route.id, dot.getLatLng(), checkpointDetails(point)));
        return dot;
      });
      const tag = node("span", "route-map-road-tag", journeyTime(route.durationMinutes));
      tag.style.setProperty("--track", color);
      // Use different fractions so similar route labels stay apart on shared roads.
      const fraction = [0.48, 0.28, 0.72][index % 3];
      const tagPosition = latLngs[Math.round((latLngs.length - 1) * fraction)];
      const label = L.marker(tagPosition, {
        icon: L.divIcon({ html: tag, className: "route-map-tag-anchor", iconSize: [1, 1], iconAnchor: [0, 0] }),
        title: route.name + " · " + journeyTime(route.durationMinutes), riseOnHover: true,
        bubblingMouseEvents: false,
      }).addTo(layers);
      bindAction(label, () => openCard(route.id, label.getLatLng(), routeSummary(route)));
      return { id: route.id, casing, line, hit, points, label, tag };
    });
    [plan.origin, plan.destination].forEach((place, index) => {
      const symbol = index === 0 ? "A" : "B";
      const pin = node("span", "route-map-endpoint", symbol);
      const marker = L.marker([place.lat, place.lon], {
        icon: L.divIcon({ html: pin, className: "route-map-endpoint-anchor", iconSize: [28, 34], iconAnchor: [14, 32] }),
        title: symbol + " · " + place.name, zIndexOffset: 1500, bubblingMouseEvents: false,
      }).addTo(layers);
      bounds.extend(marker.getLatLng());
      bindAction(marker, () => {
        const route = plan.routes.find(item => item.id === currentSelection.current) || plan.routes[0];
        const point = index ? route.checkpoints.at(-1) : route.checkpoints[0];
        openCard(route.id, marker.getLatLng(), checkpointDetails(point, symbol + " · " + place.name));
      });
    });
    boundsRef.current = bounds;
    return () => {
      layers.remove();
      if (popupRef.current) popupRef.current.popup.remove();
      popupRef.current = null;
      boundsRef.current = null;
      routeViews.current = [];
    };
  }, [plan]);

  useEffect(() => {
    let active;
    routeViews.current.forEach(view => {
      const selected = view.id === selectedId;
      if (selected) active = view;
      view.casing.setStyle({ weight: selected ? 8 : 6, opacity: 0.95 });
      view.line.setStyle({ weight: selected ? 4.8 : 3.5, opacity: selected ? 1 : 0.84 });
      view.points.forEach(dot => {
        dot.setRadius(selected ? 4.7 : 3.1);
        dot.setStyle({ weight: selected ? 1.8 : 1.2, fillOpacity: selected ? 1 : 0.88 });
      });
      view.tag.classList.toggle("is-selected", selected);
      view.label.setZIndexOffset(selected ? 500 : 0);
    });
    if (active) {
      [active.casing, active.line, active.hit, ...active.points].forEach(layer => layer.bringToFront());
    }
    if (popupRef.current && popupRef.current.id !== selectedId) {
      popupRef.current.popup.remove();
      popupRef.current = null;
    }
  }, [plan, selectedId]);

  useEffect(() => {
    if (mapRef.current) fitRoutes(mapRef.current, boundsRef.current);
  }, [plan, fitSignal]);

  useEffect(() => {
    if (!plan?.heatmap?.points?.length || !showHeat || !mapRef.current) return;
    const radiusMeters = Math.min(120000, Math.max(22500, plan.intervalMiles * 1750));
    const layer = new ForecastLayer(plan.heatmap.points, radiusMeters);
    forecast.current = layer;
    layer.addTo(mapRef.current);
    return () => {
      layer.remove();
      forecast.current = null;
    };
  }, [plan, showHeat]);

  useEffect(() => {
    forecast.current?.setHour(Math.max(0, Math.min(48, Math.round(hour))));
  }, [plan, hour, showHeat]);

  return <div className="route-map" ref={container} role="region" aria-label="Interactive routes and weather map" />;
}
