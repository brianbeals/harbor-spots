"""
Harbor Spots — Charlotte Harbor reef, ramp, and habitat map.

Pulls public Florida GIS layers via plain REST and renders a self-contained
Leaflet map:
  - FWC Artificial Reef Inventory (reefs, filtered to the county)
  - FWC Boat Ramp Inventory (county ramps; the origin ramp is chosen from it)
  - FL DEP Aquatic Preserves (polygons; each reef tagged by preserve)
  - FWC Seagrass Statewide (continuous / patchy beds; reefs tagged on-grass)

It ranks reefs by geodesic distance from a chosen boat ramp, reconciling the
layers' native Florida GDL Albers projection to WGS84 lat/lon on the server side,
and writes harbor_map.html.

Pure `requests` + `pandas`, no ArcGIS SDK and no API key — every source is public.

Run:
  pip install requests pandas
  python3 harbor_spots.py
  open harbor_map.html

© Brian Beals, LLC · brianbeals.com
"""

import os
import math
import json

import requests
import pandas as pd

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

ORIGIN_RAMP = "Ponce de Leon" # matched against the live ramp name OR city
RADIUS_NM   = 20              # nautical miles to include
COUNTY      = "Charlotte"     # try 'Lee' or 'Sarasota' too

# FL DEP aquatic-preserve polygons (Milestone 3). Envelope filter keeps the
# payload to just the Charlotte Harbor / SW Florida preserves.
PRESERVE_QUERY = (
    "https://ca.dep.state.fl.us/arcgis/rest/services/OpenData/"
    "AQUATIC_PRESERVES/MapServer/0/query"
)
HARBOR_BBOX = "-82.75,26.40,-81.80,27.25"   # xmin,ymin,xmax,ymax (lon/lat)

# FWC Florida Boat Ramp Inventory (Milestone 3). Real ramps replace the
# hard-coded coordinates: we plot every county ramp and pick the origin from it.
RAMP_LAYER_URL = (
    "https://gis.myfwc.com/mapping/rest/services/Open_Data/"
    "FWC_Florida_Boat_Ramp_Inventory/MapServer/4"
)

# FWC statewide seagrass beds (Milestone 4). DESCRIPT = "Continuous Seagrass"
# or "Patchy (Discontinuous) Seagrass".
SEAGRASS_QUERY = (
    "https://gis.myfwc.com/hosting/rest/services/Open_Data/"
    "Seagrass_Statewide/MapServer/15/query"
)

# FWC State Boating Safety Zones = Boating Restricted Areas (FAC 68D-24):
# idle-speed, slow-speed/minimum-wake, and other regulated-operation polygons.
# Same envelope-filtered GeoJSON pattern as preserves/seagrass.
ZONES_QUERY = (
    "https://gis.myfwc.com/hosting/rest/services/Open_Data/"
    "State_Boating_Safety_Zones_Florida/MapServer/10/query"
)

# FWC State Manatee Protection Zones (FAC 68C-22): seasonal and year-round
# speed zones set to protect manatees. Separate rule chapter and dataset from
# the general boating safety zones above, so it's its own overlay.
MANATEE_QUERY = (
    "https://gis.myfwc.com/hosting/rest/services/Open_Data/"
    "State_Manatee_Protection_Zones_in_Florida/MapServer/9/query"
)


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
# Feature-layer query (plain REST, no arcgis SDK)
# ---------------------------------------------------------------------------

def query_features(layer_url, where, out_fields):
    """Return a list of attribute dicts from an ArcGIS feature layer.

    Uses the layer's REST /query endpoint directly. Both the reef and ramp
    layers carry lat/lon as plain fields, so we skip geometry entirely. This
    keeps the whole script on `requests` + `pandas` with no SDK dependency,
    so it runs anywhere (including CI) with no API key.
    """
    r = requests.get(
        f"{layer_url}/query",
        params={
            "where": where,
            "outFields": out_fields,
            "outSR": "4326",
            "returnGeometry": "false",
            "f": "json",
        },
        timeout=90,
    )
    r.raise_for_status()
    return [f["attributes"] for f in r.json().get("features", [])]


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


def fetch_seagrass(bbox):
    """Pull seagrass beds intersecting bbox, as GeoJSON (WGS84).

    Same pattern as the preserves. Seagrass is far more detailed, so the
    generalization offset is larger and we keep only the classification field.
    """
    params = {
        "where": "1=1",
        "geometry": bbox,
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "DESCRIPT",
        "returnGeometry": "true",
        "maxAllowableOffset": "0.0006",
        "geometryPrecision": "5",
        "f": "geojson",
    }
    r = requests.get(SEAGRASS_QUERY, params=params, timeout=90)
    r.raise_for_status()
    return r.json()


def fetch_zones(bbox):
    """Pull boating restricted/speed-zone polygons intersecting bbox, as GeoJSON.

    Same envelope-filtered REST call as the preserves. Keeps the fields that make
    a useful popup: area name, the restriction (e.g. Idle Speed, Slow Speed
    Minimum Wake), the short condition text, and the implementation date.
    """
    params = {
        "where": "1=1",
        "geometry": bbox,
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "AREA_NAME,RESTRICTION,CON_SHORT,DATE_IMP",
        "returnGeometry": "true",
        "maxAllowableOffset": "0.0002",   # ~20 m; zones are small, keep detail
        "geometryPrecision": "5",
        "f": "geojson",
    }
    r = requests.get(ZONES_QUERY, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def fetch_manatee(bbox):
    """Pull manatee protection-zone polygons intersecting bbox, as GeoJSON.

    Same envelope-filtered REST call. Keeps the restriction text (TEXT_68C),
    the zone class (MASTER_CL), and the county for the popup.
    """
    params = {
        "where": "1=1",
        "geometry": bbox,
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "MASTER_CL,TEXT_68C,COUNTY",
        "returnGeometry": "true",
        "maxAllowableOffset": "0.0003",   # ~30 m; some manatee zones are large
        "geometryPrecision": "5",
        "f": "geojson",
    }
    r = requests.get(MANATEE_QUERY, params=params, timeout=90)
    r.raise_for_status()
    return r.json()


def _preserve_index(geojson, field="NAME"):
    """Flatten GeoJSON features into [{name, polys}] for fast point tests.

    Each `polys` entry is one polygon: [outer_ring, hole_ring, ...]. A
    MultiPolygon contributes several such entries. `field` is the property
    used as the label (NAME for preserves, DESCRIPT for seagrass).
    """
    idx = []
    for feat in geojson.get("features", []):
        name = (feat.get("properties") or {}).get(field) or ""
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
<title>Harbor Spots &middot; Charlotte Harbor</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta property="og:type" content="website">
<meta property="og:title" content="Harbor Spots &middot; Charlotte Harbor">
<meta property="og:description" content="Artificial reefs, boat ramps, aquatic preserves, seagrass, and manatee and speed zones within 20 nm of Charlotte Harbor. Rebuilt weekly from live FWC and FL DEP layers.">
<meta property="og:url" content="https://brianbeals.github.io/harbor-spots/">
<meta property="og:image" content="https://brianbeals.github.io/harbor-spots/og-card.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#map{height:100%;margin:0} .lgnd{position:absolute;z-index:1000;bottom:12px;left:12px;background:#fff;padding:8px 10px;font:12px system-ui;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.3)}</style>
</head>
<body>
<div id="map"></div>
<div class="lgnd"><b>__RAMP__</b><br>reefs within __RADNM__ nm<br><span style="color:#E74C3C">&#9679;</span> origin ramp &nbsp; <span style="color:#F39C12">&#9679;</span> boat ramp<br><span style="color:#2E86C1">&#9679;</span> reef &nbsp; <span style="color:#2874A6">&#9633;</span> preserve<br><span style="color:#4CA64C">&#9632;</span> continuous grass &nbsp; <span style="color:#C9E68A">&#9632;</span> patchy grass<br><span style="color:#D6336C">&#9632;</span> restricted / speed zone<br><span style="color:#845EF7">&#9632;</span> manatee zone</div>
<script>
var reefs = __DATA__;
var preserves = __PRESERVES__;
var seagrass = __SEAGRASS__;
var zones = __ZONES__;
var manatee = __MANATEE__;
var ramps = __RAMPS__;
var origin = [__LAT__, __LON__];
var map = L.map('map').fitBounds([[__S__, __W__], [__N__, __E__]]);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {maxZoom:19, attribution:'&copy; OpenStreetMap'}).addTo(map);
try {
  L.geoJSON(seagrass, {style:function(f){
    var d=(f.properties&&f.properties.DESCRIPT)||'';
    var col = d.indexOf('Continuous')>=0 ? '#4CA64C' : '#C9E68A';
    return {color:col, weight:0, fillColor:col, fillOpacity:0.5};
  }, onEachFeature:function(f,l){l.bindPopup((f.properties&&f.properties.DESCRIPT)||'Seagrass');}}).addTo(map);
} catch(e) { console.error('seagrass layer failed:', e); }
try {
  L.geoJSON(preserves, {style:{color:'#2874A6', weight:1.5, fill:false},
    onEachFeature:function(f,l){l.bindPopup((f.properties&&f.properties.NAME)||'Aquatic Preserve');}}).addTo(map);
} catch(e) { console.error('preserve layer failed:', e); }
try {
  L.geoJSON(manatee, {style:{color:'#5F3DC4', weight:1, fillColor:'#845EF7', fillOpacity:0.22},
    onEachFeature:function(f,l){
      var p=f.properties||{};
      var rest=p.TEXT_68C||p.MASTER_CL||'Manatee Protection Zone';
      var cty=p.COUNTY?'<br><i>'+p.COUNTY+' County</i>':'';
      l.bindPopup('<b>Manatee Zone</b><br>'+rest+cty);
    }}).addTo(map);
} catch(e) { console.error('manatee layer failed:', e); }
try {
  L.geoJSON(zones, {style:{color:'#A61E4D', weight:1, fillColor:'#D6336C', fillOpacity:0.28},
    onEachFeature:function(f,l){
      var p=f.properties||{};
      var name=p.AREA_NAME||'Boating Restricted Area';
      var rest=p.RESTRICTION?'<br>'+p.RESTRICTION:'';
      var cond=p.CON_SHORT?'<br><i>'+p.CON_SHORT+'</i>':'';
      l.bindPopup('<b>'+name+'</b>'+rest+cond);
    }}).addTo(map);
} catch(e) { console.error('zone layer failed:', e); }
L.circle(origin, {radius:__RADIUSM__, color:'#1E3A5F', weight:1, fill:false}).addTo(map);
ramps.forEach(function(r){
  L.circleMarker([r.lat, r.lon], {radius:5, color:'#7E5109', fillColor:'#F39C12', fillOpacity:0.9, weight:1}).addTo(map)
   .bindPopup('<b>'+r.name+'</b>'+(r.water?'<br>'+r.water:'')+(r.lanes?'<br>'+r.lanes+' lanes':''));
});
L.circleMarker(origin, {radius:7, color:'#7B241C', fillColor:'#E74C3C', fillOpacity:1, weight:2})
  .addTo(map).bindPopup('Ramp: __RAMP__');
reefs.forEach(function(f){
  L.circleMarker([f.lat, f.lon],
    {radius:6, color:'#0B3D6B', fillColor:'#2E86C1', fillOpacity:0.95, weight:1}).addTo(map)
   .bindPopup('<b>'+f.name+'</b><br>'+f.dist+' nm &middot; '+(f.depth?f.depth+' ft':'? ft')+' &middot; '+f.material+(f.preserve?'<br><i>'+f.preserve+'</i>':'')+(f.seagrass?'<br>on '+f.seagrass:''));
});
console.log('harbor-spots: '+reefs.length+' reefs, '+((preserves.features||[]).length)+' preserves');
</script>
</body>
</html>"""


def write_map(df, ramp_name, origin_lat, origin_lon, radius_nm,
              preserves_geojson, seagrass_geojson, zones_geojson, manatee_geojson, ramps, out_path):
    """Write a self-contained Leaflet map: reefs, ramps, preserves, seagrass."""
    ramps = ramps or []
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
            "seagrass": str(r.get("seagrass") or ""),
        })
    # Explicit view bounds: reef points, all ramps, plus the range ring, so the
    # map always frames the area deterministically (no reliance on auto-fit).
    lats = [origin_lat] + [r["lat"] for r in reefs] + [r["lat"] for r in ramps]
    lons = [origin_lon] + [r["lon"] for r in reefs] + [r["lon"] for r in ramps]
    dlat = radius_nm / 60.0
    dlon = radius_nm / (60.0 * max(0.1, math.cos(math.radians(origin_lat))))
    south = min(min(lats), origin_lat - dlat)
    north = max(max(lats), origin_lat + dlat)
    west = min(min(lons), origin_lon - dlon)
    east = max(max(lons), origin_lon + dlon)

    html = (MAP_TEMPLATE
            .replace("__DATA__", json.dumps(reefs))
            .replace("__PRESERVES__", json.dumps(preserves_geojson or {"type": "FeatureCollection", "features": []}))
            .replace("__SEAGRASS__", json.dumps(seagrass_geojson or {"type": "FeatureCollection", "features": []}))
            .replace("__ZONES__", json.dumps(zones_geojson or {"type": "FeatureCollection", "features": []}))
            .replace("__MANATEE__", json.dumps(manatee_geojson or {"type": "FeatureCollection", "features": []}))
            .replace("__RAMPS__", json.dumps(ramps))
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
    # --- Milestone 1: read the public FWC reef layer (WGS84 lat/lon) ---
    rows = query_features(
        REEF_LAYER_URL,
        where=f"County = '{COUNTY}'",
        out_fields="OBJECTID,Name,County,Depth,Relief,MatCat,Long_DD,Lat_DD",
    )
    sdf = pd.DataFrame(rows)
    print(f"Pulled {len(sdf)} reef deployments in {COUNTY} County.")
    if sdf.empty:
        return

    # --- Milestone 3: pull county boat ramps from the FWC service ---
    ramps = []
    try:
        for a in query_features(
                RAMP_LAYER_URL,
                where=f"County = '{COUNTY}'",
                out_fields="RampName,City,WaterBodyName,TotalLanes,Latitude,Longitude"):
            if a.get("Latitude") and a.get("Longitude"):
                ramps.append({
                    "name": str(a.get("RampName") or "Ramp"),
                    "lat": float(a["Latitude"]),
                    "lon": float(a["Longitude"]),
                    "water": str(a.get("WaterBodyName") or ""),
                    "lanes": a.get("TotalLanes"),
                    "city": str(a.get("City") or ""),
                })
        print(f"Loaded {len(ramps)} boat ramps in {COUNTY} County.")
    except Exception as e:
        print(f"(Ramp layer unavailable: {e})")

    # --- Milestone 2: distance from the origin ramp to every reef ---
    _q = ORIGIN_RAMP.lower()
    origin = next((r for r in ramps
                   if _q in r["name"].lower() or _q in r.get("city", "").lower()), None)
    if origin:
        origin_lat, origin_lon, origin_label = origin["lat"], origin["lon"], origin["name"]
    else:
        origin_lat, origin_lon = RAMPS.get(ORIGIN_RAMP, (26.9583, -82.2078))
        origin_label = ORIGIN_RAMP
    print(f"Origin ramp: {origin_label} ({origin_lat:.4f}, {origin_lon:.4f})")

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

    # --- Milestone 4: tag each reef that sits on a seagrass bed ---
    try:
        seagrass_geojson = fetch_seagrass(HARBOR_BBOX)
        sidx = _preserve_index(seagrass_geojson, "DESCRIPT")
        sdf["seagrass"] = sdf.apply(
            lambda row: preserve_for_point(row["Long_DD"], row["Lat_DD"], sidx), axis=1)
        on_grass = int((sdf["seagrass"] != "").sum())
        print(f"Loaded {len(sidx)} seagrass polygon(s); {on_grass} reef(s) sit on grass.")
    except Exception as e:
        print(f"(Seagrass layer unavailable, skipping: {e})")
        seagrass_geojson = None
        sdf["seagrass"] = ""

    # --- Boating restricted / speed zones in the harbor area ---
    try:
        zones_geojson = fetch_zones(HARBOR_BBOX)
        print(f"Loaded {len((zones_geojson or {}).get('features', []))} boating restricted/speed zone(s).")
    except Exception as e:
        print(f"(Zone layer unavailable, skipping: {e})")
        zones_geojson = None

    # --- Manatee protection zones in the harbor area ---
    try:
        manatee_geojson = fetch_manatee(HARBOR_BBOX)
        print(f"Loaded {len((manatee_geojson or {}).get('features', []))} manatee protection zone(s).")
    except Exception as e:
        print(f"(Manatee layer unavailable, skipping: {e})")
        manatee_geojson = None

    nearby = sdf[sdf["dist_nm"] <= RADIUS_NM].sort_values("dist_nm")
    cols = ["Name", "dist_nm", "Depth", "Relief", "MatCat", "preserve", "seagrass", "Lat_DD", "Long_DD"]

    print(f"\nReefs within {RADIUS_NM} nm of {origin_label} "
          f"({origin_lat:.4f}, {origin_lon:.4f}):\n")
    for _, r in nearby[cols].iterrows():
        depth = f"{r['Depth']:.0f}ft" if r["Depth"] else "  ? "
        pres = f"  ·  {r['preserve']}" if r["preserve"] else ""
        grass = "  [grass]" if r["seagrass"] else ""
        print(f"  {r['dist_nm']:5.1f} nm  {depth:>6}  {str(r['MatCat'] or ''):8}  {r['Name']}{pres}{grass}")

    here = os.path.dirname(os.path.abspath(__file__))
    out_csv = os.path.join(here, "harbor_reefs_nearby.csv")
    nearby[cols].to_csv(out_csv, index=False)
    print(f"\nWrote {len(nearby)} rows to {out_csv}")

    out_map = os.path.join(here, "harbor_map.html")
    write_map(nearby, origin_label, origin_lat, origin_lon, RADIUS_NM,
              preserves_geojson, seagrass_geojson, zones_geojson, manatee_geojson, ramps, out_map)
    print(f"Wrote map to {out_map} — open it in a browser.")


if __name__ == "__main__":
    main()
