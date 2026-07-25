# Harbor Spots — ArcGIS ramp project (Charlotte Harbor)

A hands-on ArcGIS learning project built around real Charlotte Harbor data. It doubles as a personal
fishing/boating tool and a portfolio piece for county bids, since it is county-plus-state GIS
integration, the exact work Charlotte and Lee County agencies buy.

The build pulls public reef, seagrass, and ramp data, runs real spatial analysis on it, writes a
curated layer of your own, and ends up feeding the marine forecast you already built.

## Skills this covers

Auth (Web GIS / API key), REST querying, projections, spatial joins and distance, polygon overlay,
feature write-back, and front-end rendering. The full integration stack in one project.

## Confirmed live data sources

| Layer | Endpoint | Notes |
| --- | --- | --- |
| FWC Artificial Reefs | `https://gis.myfwc.com/mapping/rest/services/Open_Data/Artificial_Reef_Locations_in_Florida/MapServer/12` | Point layer. Fields: `County`, `Name`, `Depth`, `Relief`, `MatCat`, `Long_DD`, `Lat_DD`. Native SR wkid 6439 (FL GDL Albers, meters). Filter `County='Charlotte'`. |
| FWC Seagrass Statewide | `https://gis.myfwc.com/hosting/rest/services/Open_Data/Seagrass_Statewide/MapServer` | Polygon layer. Includes Gasparilla Sound–Charlotte Harbor mapping. |
| Charlotte County GIS | https://www.charlottecountyfl.gov/gis/ | Boat ramps, parcels, zoning, flood, aquatic-preserve boundaries. |
| Florida Geospatial Open Data | https://geodata.floridagio.gov/ | Statewide catalog; search "Charlotte County" for ramp/waterway services. |

## Milestones

Each is roughly one or two sessions. `harbor_spots.py` in this folder already implements 1 and 2.

**1. Setup and auth.** Create the ArcGIS Location Platform account, generate an API key, `pip install
arcgis`, connect with `GIS`. Confirm a token round-trips. Web GIS entry point plus the auth model.

**2. Read a public service + first spatial op.** Query the FWC reef layer filtered to Charlotte
County, pull into a Spatially Enabled DataFrame, request output in WGS84 to reconcile the native
Albers projection, then compute distance from a boat ramp to each reef and list the closest. Projections,
REST query, SEDF, geodesic distance. (This is `harbor_spots.py`.)

**3. Spatial operations, deeper.** Replace the hard-coded ramp coordinates with the Charlotte County
boat-ramps feature service. Project to a planar CRS (Florida State Plane West, EPSG 2882, feet, or UTM
17N) and buffer each ramp; point-in-polygon a reef into its aquatic preserve / slow-speed zone. Buffers,
spatial joins, projected distance.

**4. Overlay seagrass.** Intersect reef points with the FWC seagrass polygons and tag each by whether
it sits on or near grass. Polygon intersect, attribute join.

**5. Write-back to your own service.** Create a hosted feature layer on your Location Platform account,
"Harbor Spots," and push curated points (favorite reefs, ramps, a trip log) with attributes. Then edit
and update them. Closes the loop: pull from public services, push to one you own. This is the milestone
that proves real integration.

**6. Render and integrate.** Put the spots on a web map (Maps SDK for JavaScript), or add a small map
panel to the marine-forecast card so it shows spots alongside today's tide and wind. Answers a real
question: given today's wind and tide, which ramp and which grassy reef is the smart call.

## Effort

Two to three weeks part-time end to end, most of it hands-on. At the finish you have genuine working
fluency plus a demo you can screen-share on a discovery call.

## Getting started

1. Create the account and API key (see link Brian was given, `location.arcgis.com`).
2. `pip install arcgis`
3. `export ARCGIS_API_KEY="<your key>"`
4. `python harbor_spots.py`

---
© Brian Beals, LLC · brianbeals.com · July 25, 2026
