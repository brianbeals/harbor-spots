# Harbor Spots

**Live map: https://brianbeals.github.io/harbor-spots/**

A self-updating map of Charlotte Harbor, Florida that pulls live public GIS
services and renders artificial reefs, boat ramps, aquatic-preserve boundaries,
and seagrass beds on one interactive map. Built as a working demonstration of
ArcGIS / Esri integration: querying government feature services, reconciling
projections, running spatial joins, and publishing the result.

Pick a boat ramp; the map ranks every county reef by distance from it, draws a
range ring, tags each reef by the aquatic preserve it sits in and whether it
falls on a seagrass bed, and frames the view on the cluster.

## Data sources (all public, no key required)

| Layer | Service |
| --- | --- |
| Artificial reefs | FWC Artificial Reef Inventory (ArcGIS REST) |
| Boat ramps | FWC Florida Boat Ramp Inventory (ArcGIS REST) |
| Aquatic preserves | FL DEP Aquatic Preserves (ArcGIS REST) |
| Seagrass beds | FWC Seagrass Statewide (ArcGIS REST) |
| Basemap | OpenStreetMap tiles |

Every source is queried live over the ArcGIS REST API. The reef and ramp layers
carry lat/lon as attributes; the preserve and seagrass polygons are pulled as
generalized GeoJSON with a bounding-box filter to keep the payload small.

## What it demonstrates

- **REST querying** of ArcGIS feature services (where-clauses, output fields,
  envelope filters, server-side generalization).
- **Projection reconciliation** — the source layers are stored in Florida GDL
  Albers (meters); the map requests WGS84 so everything lands in lat/lon.
- **Spatial analysis in pure Python** — geodesic distance ranking and a
  ray-casting point-in-polygon that tags each reef by preserve and by seagrass,
  with no heavy geospatial dependencies.
- **Deterministic rendering** — a self-contained Leaflet map with computed view
  bounds and layers that degrade gracefully if a source is unavailable.
- **CI/CD** — a GitHub Action rebuilds the map from live data every week and
  deploys it to GitHub Pages. No secrets; the whole pipeline runs anonymously.

## Run locally

```
pip install requests pandas
python3 harbor_spots.py
open harbor_map.html
```

Configuration lives at the top of `harbor_spots.py`: `ORIGIN_RAMP` (matched
against the live ramp name or city), `RADIUS_NM`, and `COUNTY`. Change one, re-run,
refresh the browser.

## Files

- `harbor_spots.py` — pulls the layers, does the spatial work, writes the map.
- `.github/workflows/build-map.yml` — weekly rebuild + Pages deploy.
- `publish_spots.py` — optional: publishes the reef shortlist as your own hosted
  ArcGIS feature layer (needs an ArcGIS Location Platform key with content
  privileges; not part of the public build).

---
© Brian Beals, LLC · brianbeals.com
