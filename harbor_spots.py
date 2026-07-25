"""
Harbor Spots — Milestones 1 and 2
Charlotte Harbor artificial-reef finder built on the ArcGIS API for Python.

What it does:
  1. Connects to ArcGIS (Web GIS auth via an API key).
  2. Queries the public FWC Artificial Reef layer, filtered to Charlotte County,
     and pulls the result into a Spatially Enabled DataFrame (the pandas-like object).
  3. Reconciles projections: the layer is stored in Florida GDL Albers (wkid 6439,
     meters); we ask the server to return WGS84 (wkid 4326) so we get lat/lon.
  4. Computes geodesic distance from a boat ramp to every reef and lists the closest.

Run:
  pip install arcgis
  export ARCGIS_API_KEY="<your key from location.arcgis.com>"
  python harbor_spots.py

Notes:
  - The FWC reef layer is public, so the query works with or without a key. The key
    is what you will need later for basemaps, geocoding, and the Milestone 5 write-back.
  - Ramp coordinates below are approximate. Milestone 3 replaces them with the
    Charlotte County boat-ramp feature service.

© Brian Beals, LLC · brianbeals.com
"""

import os
import math
import json

import requests
import pandas as pd
from arcgis.gis import GIS
from arcgis.features import FeatureLayer

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REEF_LAYER_URL = (
    "https://gis.myfwc.com/mapping/rest/services/Open_Data/"
    "Artificial_Reef_Locations_in_Florida/MapServer/12"
)

# A few real Charlotte Harbor ramps (approximate lat/lon). Pick one as the origin.
RAMPS = {
    "El Jobean":            (26.9583, -82.2078),
    "Placida / Eldred's":   (26.8430, -82.2630),
    "Ponce de Leon Park":   (26.9180, -82.0700),
    "Laishley Park":        (26.9280, -82.0490),
    "Port Charlotte Beach": (26.9830, -82.0780),
}

ORIGIN_RAMP = "El Jobean"     # change to any key above
RADIUS_NM   = 15              # nautical miles to include
COUNTY      = "Charlotte"     # try 'Lee' or 'Sarasota' too

# FL DEP aquatic-preserve polygons (Milestone 3). Envelope filter keeps the
# payload to just the Charlotte Harbor / SW Florida preserves.
PRESERVE_QUERY = (
    "https://ca.dep.state.fl.us/arcgis/rest/services/OpenData/"
    "AQUATIC_PRESERVES/MapServer/0/query"
)
HARBOR_BBOX = "-82.75,26.40,-81.80,27.25"   # xmin,ymin,xmax,ymax (lon/lat)


# ---------------------------------------------------------------------------
# Distance helper (geodesic, no extra dependencies)
# ---------------------------------------------------------------------------

def haversine_nm(lat1, lon1, lat2, lon2):
    """Great-circle distance in nautical miles between two lat/lon points.

    This is the correct way to measure distance on lat/lon (geographic) data.
    When you move to planar operations in Milestone 3 (buffers, overlays), you
    project to a flat CRS first (e.g. Florida State Plane West, EPSG 2882) so
    units come out in feet and area math is valid. For point-to-point distance,
    geodesic like this is both simpler and more accurate.
    """
    r_nm = 3440.065  # earth radius in nautical miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return r_nm * 2 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Aquatic preserves + point-in-polygon (Milestone 3)
# ---------------------------------------------------------------------------

def fetch_preserves(bbox):
    """Pull aquatic-preserve polygons intersecting bbox, as GeoJSON (WGS84).

    Uses a plain REST call (requests) rather than the arcgis SDK. Mixing the
    SDK with raw REST is normal integration work, and here it keeps the polygon
    payload small via the envelope filter plus maxAllowableOffset (which asks the
    server to generalize the shorelines so the map stays light).
    """
    params = {
        "where": "1=1",
        "geometry": bbox,
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "NAME,COUNTIES",
        "returnGeometry": "true",
        "maxAllowableOffset": "0.0004",   # ~40 m; generalizes the boundary
        "geometryPrecision": "5",
        "f": "geojson",
    }
    r = requests.get(PRESERVE_QUERY, params=params, timeout=60)
    r.raise_for_status()
    return r.json()   # a GeoJSON FeatureCollection


def _preserve_index(geojson):
    """Flatten GeoJSON features into [{name, polys}] for fast point tests.

    Each `polys` entry is one polygon: [outer_ring, hole_ring, ...]. A
    MultiPolygon contributes several such entries.
    """
    idx = []
    for feat in geojson.get("features", []):
        name = (feat.get("properties") or {}).get("NAME") or ""
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []
        if gtype == "Polygon":
            polys = [coords]
        elif gtype == "MultiPolygon":
            polys = coords
        else:
            polys = []
        idx.append({"name": name, "polys": polys})
    return idx


def _in_ring(x, y, ring):
    """Ray-casting point-in-polygon for a single ring of [lon, lat] pairs."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and \
           (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-15) + xi):
            inside = not inside
        j = i
    return inside


def _in_polygon(x, y, poly):
    """poly = [outer, hole1, ...]. Inside outer and outside every hole."""
    if not poly or not _in_ring(x, y, poly[0]):
        return False
    return not any(_in_ring(x, y, hole) for hole in poly[1:])


def preserve_for_point(lon, lat, index):
    """Return the name of the preserve containing (lon, lat), or ''."""
    for p in index:
        for poly in p["polys"]:
            if _in_polygon(lon, lat, poly):
                return p["name"]
    return ""


# ---------------------------------------------------------------------------
# Map output (self-contained Leaflet HTML; open in a browser)
# ---------------------------------------------------------------------------

MAP_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Harbor Spots</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#map{height:100%;margin:0} .lgnd{position:absolute;z-index:1000;bottom:12px;left:12px;background:#fff;padding:8px 10px;font:12px system-ui;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.3)}</style>
</head>
<body>
<div id="map"></div>
<div class="lgnd"><b>__RAMP__</b><br>reefs within __RADNM__ nm<br><span style="color:#1E8449">&#9632;</span> aquatic preserve</div>
<script>
var reefs = __DATA__;
var preserves = __PRESERVES__;
var origin = [__LAT__, __LON__];
var map = L.map('map').fitBounds([[__S__, __W__], [__N__, __E__]]);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {maxZoom:19, attribution:'&copy; OpenStreetMap'}).addTo(map);
try {
  L.geoJSON(preserves, {style:{color:'#1E8449', weight:1, fillColor:'#1E8449', fillOpacity:0.15},
    onEachFeature:function(f,l){l.bindPopup((f.properties&&f.properties.NAME)||'Aquatic Preserve');}}).addTo(map);
} catch(e) { console.error('preserve layer failed:', e); }
L.circle(origin, {radius:__RADIUSM__, color:'#1E3A5F', weight:1, fill:false}).addTo(map);
L.circleMarker(origin, {radius:7, color:'#7B241C', fillColor:'#E74C3C', fillOpacity:1, weight:2})
  .addTo(map).bindPopup('Ramp: __RAMP__');
reefs.forEach(function(f){
  L.circleMarker([f.lat, f.lon],
    {radius:6, color:'#0B3D6B', fillColor:'#2E86C1', fillOpacity:0.95, weight:1}).addTo(map)
   .bindPopup('<b>'+f.name+'</b><br>'+f.dist+' nm &middot; '+(f.depth?f.depth+' ft':'? ft')+' &middot; '+f.material+(f.preserve?'<br><i>'+f.preserve+'</i>':''));
});
console.log('harbor-spots: '+reefs.length+' reefs, '+((preserves.features||[]).length)+' preserves');
</script>
</body>
</html>"""


def write_map(df, ramp_name, origin_lat, origin_lon, radius_nm, preserves_geojson, out_path):
    """Write a self-contained Leaflet map of the reefs, ramp, and preserves."""
    reefs = []
    for _, r in df.iterrows():
        depth = r.get("Depth")
        reefs.append({
            "name": str(r.get("Name") or ""),
            "lat": float(r["Lat_DD"]),
            "lon": float(r["Long_DD"]),
            "depth": None if (depth is None or pd.isna(depth)) else round(float(depth)),
            "material": str(r.get("MatCat") or ""),
            "dist": round(float(r["dist_nm"]), 1),
            "preserve": str(r.get("preserve") or ""),
        })
    # Explicit view bounds: reef points plus the ramp's range ring, so the map
    # always frames the cluster deterministically (no reliance on auto-fit).
    lats = [origin_lat] + [r["lat"] for r in reefs]
    lons = [origin_lon] + [r["lon"] for r in reefs]
    dlat = radius_nm / 60.0
    dlon = radius_nm / (60.0 * max(0.1, math.cos(math.radians(origin_lat))))
    south = min(min(lats), origin_lat - dlat)
    north = max(max(lats), origin_lat + dlat)
    west = min(min(lons), origin_lon - dlon)
    east = max(max(lons), origin_lon + dlon)

    html = (MAP_TEMPLATE
            .replace("__DATA__", json.dumps(reefs))
            .replace("__PRESERVES__", json.dumps(preserves_geojson or {"type": "FeatureCollection", "features": []}))
            .replace("__LAT__", str(origin_lat))
            .replace("__LON__", str(origin_lon))
            .replace("__S__", str(south)).replace("__N__", str(north))
            .replace("__W__", str(west)).replace("__E__", str(east))
            .replace("__RADIUSM__", str(radius_nm * 1852.0))
            .replace("__RADNM__", str(radius_nm))
            .replace("__RAMP__", ramp_name))
    with open(out_path, "w") as fh:
        fh.write(html)
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # --- Milestone 1: auth + read a public service ---
    api_key = os.environ.get("ARCGIS_API_KEY")
    if api_key:
        gis = GIS(api_key=api_key)
        print("Connected to ArcGIS with an API key.")
    else:
        gis = GIS()  # anonymous still works for this public layer
        print("No ARCGIS_API_KEY found; connecting anonymously (fine for reading).")

    layer = FeatureLayer(REEF_LAYER_URL)

    # Ask for WGS84 (4326) so we get plain lat/lon back, not Albers meters.
    result = layer.query(
        where=f"County = '{COUNTY}'",
        out_fields="OBJECTID,Name,County,Depth,Relief,MatCat,Long_DD,Lat_DD",
        out_sr=4326,
        return_geometry=True,
    )
    # Build a plain DataFrame from the query attributes. (We avoid result.sdf /
    # the Spatially Enabled DataFrame because its GeoAccessor fails to import on
    # some Python 3.14 / pandas 3.0 builds. We asked for Long_DD/Lat_DD in the
    # out_fields, so we already have lat/lon without needing the geometry object.)
    sdf = pd.DataFrame([f.attributes for f in result.features])
    print(f"\nPulled {len(sdf)} reef deployments in {COUNTY} County.")
    if sdf.empty:
        return

    # --- Milestone 2: distance from a ramp to every reef ---
    origin_lat, origin_lon = RAMPS[ORIGIN_RAMP]
    sdf["dist_nm"] = sdf.apply(
        lambda row: haversine_nm(origin_lat, origin_lon, row["Lat_DD"], row["Long_DD"]),
        axis=1,
    )

    # --- Milestone 3: tag each reef with the aquatic preserve it sits in ---
    try:
        preserves_geojson = fetch_preserves(HARBOR_BBOX)
        pidx = _preserve_index(preserves_geojson)
        sdf["preserve"] = sdf.apply(
            lambda row: preserve_for_point(row["Long_DD"], row["Lat_DD"], pidx), axis=1)
        print(f"Loaded {len(pidx)} aquatic preserve(s) in the harbor area.")
    except Exception as e:
        print(f"(Preserve layer unavailable, skipping tag: {e})")
        preserves_geojson = None
        sdf["preserve"] = ""

    nearby = sdf[sdf["dist_nm"] <= RADIUS_NM].sort_values("dist_nm")
    cols = ["Name", "dist_nm", "Depth", "Relief", "MatCat", "preserve", "Lat_DD", "Long_DD"]

    print(f"\nReefs within {RADIUS_NM} nm of {ORIGIN_RAMP} "
          f"({origin_lat:.4f}, {origin_lon:.4f}):\n")
    for _, r in nearby[cols].iterrows():
        depth = f"{r['Depth']:.0f}ft" if r["Depth"] else "  ? "
        pres = f"  ·  {r['preserve']}" if r["preserve"] else ""
        print(f"  {r['dist_nm']:5.1f} nm  {depth:>6}  {str(r['MatCat'] or ''):8}  {r['Name']}{pres}")

    here = os.path.dirname(os.path.abspath(__file__))
    out_csv = os.path.join(here, "harbor_reefs_nearby.csv")
    nearby[cols].to_csv(out_csv, index=False)
    print(f"\nWrote {len(nearby)} rows to {out_csv}")

    out_map = os.path.join(here, "harbor_map.html")
    write_map(nearby, ORIGIN_RAMP, origin_lat, origin_lon, RADIUS_NM, preserves_geojson, out_map)
    print(f"Wrote map to {out_map} — open it in a browser.")


if __name__ == "__main__":
    main()
