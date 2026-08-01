# Harbor Spots

**Live map: https://harbor.brianbeals.com/**

A self-updating map of Charlotte Harbor and Pine Island Sound, Florida that pulls live public
GIS services and renders artificial reefs, boat ramps, aquatic-preserve boundaries, seagrass
beds, boating restricted/speed zones, and manatee protection zones on one interactive map.
Built as a working demonstration of ArcGIS / Esri integration: querying government feature
services, reconciling projections, running spatial joins, and publishing the result.

Pick where you're leaving from. The map recomputes every reef's distance and magnetic bearing
from that point, redraws the 20 nm range ring, and refits the view. Departure points include
the public boat ramps from the FWC inventory plus a curated list of the marinas people
actually leave from, which no GIS layer knows about. Each reef is tagged by the aquatic
preserve it sits in and by whether it falls on a seagrass bed, with the regulated speed zones
drawn over the top.

A conditions strip in the corner shows today's wind, water state, and storm risk, read live
from the marine forecast at weather.brianbeals.com.

## Data sources (all public, no key required)

| Layer | Service |
| --- | --- |
| Artificial reefs | FWC Artificial Reef Inventory (ArcGIS REST) |
| Boat ramps | FWC Florida Boat Ramp Inventory (ArcGIS REST) |
| Aquatic preserves | FL DEP Aquatic Preserves (ArcGIS REST) |
| Seagrass beds | FWC Seagrass Statewide (ArcGIS REST) |
| Boating restricted / speed zones | FWC State Boating Safety Zones, FAC 68D-24 (ArcGIS REST) |
| Manatee protection zones | FWC State Manatee Protection Zones, FAC 68C-22 (ArcGIS REST) |
| Current conditions | weather.brianbeals.com `conditions.json`, fetched in the browser |
| Basemap | OpenStreetMap tiles |

Every GIS source is queried live over the ArcGIS REST API. The reef and ramp layers carry
lat/lon as attributes; the preserve, seagrass, boating-zone, and manatee-zone polygons are
pulled as generalized GeoJSON with a bounding-box filter to keep the payload small.

## What it demonstrates

- **REST querying** of ArcGIS feature services: where-clauses, output fields, envelope
  filters, server-side generalization.
- **Projection reconciliation.** The source layers are stored in Florida GDL Albers (meters);
  the map requests WGS84 so everything lands in lat/lon.
- **Spatial analysis in pure Python.** Geodesic distance and a ray-casting point-in-polygon
  that tags each reef by preserve and by seagrass, with no heavy geospatial dependencies.
- **Splitting work between build time and run time.** Reefs don't move, so they're baked in
  weekly. The origin does move, so distance, bearing, and the radius cut are computed in the
  browser against whatever you select. Conditions change hourly, so they're fetched on every
  page load rather than frozen into a page that rebuilds on Mondays.
- **Deterministic rendering.** A self-contained Leaflet map whose layers degrade gracefully if
  a source is unavailable.
- **CI/CD.** A GitHub Action rebuilds the map from live data every week and deploys it to
  GitHub Pages. No secrets; the whole pipeline runs anonymously.

## Bearings are magnetic

Reef popups read like `8.4 nm · 212°M`. Bearings are magnetic, not true, because that's what a
compass and a US chartplotter default to. `MAG_VAR_W` in `harbor_spots.py` holds the variation
for this area in degrees west, and it drifts about 0.1° a year.

## Run locally

```
pip install requests pandas pyyaml
python3 harbor_spots.py
open harbor_map.html
```

Configuration lives at the top of `harbor_spots.py`:

- `COUNTIES`: which counties to pull reefs and ramps from. Charlotte plus Lee, because
  Cabbage Key, Burnt Store, and the southern reefs sit below the county line.
- `RAMP_BOX`: the geographic box that keeps ramps to the Charlotte Harbor / Pine Island Sound
  system. Lee County brings 117 ramps, most of them up the Caloosahatchee or in the Cape Coral
  canals, which are a different boating area. The comment above it records the filters that
  were tried and rejected first, so nobody re-tries them.
- `RADIUS_NM`: the range ring, applied in the browser.
- `MAG_VAR_W`: magnetic variation, degrees west.

Departure points that aren't public ramps live in `origins.yml`. That file also records why
one particular departure point is deliberately absent from a public map.

## Tests

```
python3 test_build.py
```

Runs the real `main()` with the network stubbed and asserts on the generated HTML. It exists
because a refactor once deleted a constant that `main()` still referenced: every static check
passed and the build died in CI with a `NameError`. A syntax check can't catch that; executing
the code can. It also guards the load-bearing behavior, including that reefs reach the browser
unfiltered by radius, which is what lets a southern origin draw a full range ring.

## Files

- `harbor_spots.py`: pulls the layers, does the spatial work, writes the map.
- `origins.yml`: curated departure points, and the note about the one that's excluded.
- `test_build.py`: end-to-end smoke test with the network stubbed.
- `og-card.png`: social preview card, staged into the deploy by the workflow.
- `.github/workflows/build-map.yml`: weekly rebuild and Pages deploy.
- `publish_spots.py`: optional. Uploads the reef shortlist to ArcGIS as a content item using
  an API key, the first half of the write-back. Publishing that item into a hosted feature
  layer, and sharing it, require a signed-in user (ArcGIS UI or OAuth), not an API key, on a
  Location Platform account; the script prints the item link to finish the publish there. Not
  part of the public build.

---
© Brian Beals, LLC · brianbeals.com
