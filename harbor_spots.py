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
<div class="lgnd"><b>__RAMP__</b><br>reefs within __RADNM__ nm</div>
<script>
var reefs = __DATA__;
var origin = [__LAT__, __LON__];
var map = L.map('map');
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {maxZoom:19, attribution:'&copy; OpenStreetMap'}).addTo(map);
L.marker(origin).addTo(map).bindPopup('Ramp: __RAMP__');
L.circle(origin, {radius:__RADIUSM__, color:'#1E3A5F', weight:1, fill:false}).addTo(map);
var pts = [origin];
reefs.forEach(function(f){
  var c = L.circleMarker([f.lat, f.lon],
    {radius:6, color:'#2E86C1', fillColor:'#2E86C1', fillOpacity:0.85, weight:1}).addTo(map);
  c.bindPopup('<b>'+f.name+'</b><br>'+f.dist+' nm &middot; '+(f.depth?f.depth+' ft':'? ft')+' &middot; '+f.material);
  pts.push([f.lat, f.lon]);
});
map.fitBounds(pts, {padding:[30,30]});
</script>
</body>
</html>"""


def write_map(df, ramp_name, origin_lat, origin_lon, radius_nm, out_path):
    """Write a self-contained Leaflet map of the reefs and the ramp."""
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
        })
    html = (MAP_TEMPLATE
            .replace("__DATA__", json.dumps(reefs))
            .replace("__LAT__", str(origin_lat))
            .replace("__LON__", str(origin_lon))
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

    nearby = sdf[sdf["dist_nm"] <= RADIUS_NM].sort_values("dist_nm")
    cols = ["Name", "dist_nm", "Depth", "Relief", "MatCat", "Lat_DD", "Long_DD"]

    print(f"\nReefs within {RADIUS_NM} nm of {ORIGIN_RAMP} "
          f"({origin_lat:.4f}, {origin_lon:.4f}):\n")
    for _, r in nearby[cols].iterrows():
        depth = f"{r['Depth']:.0f}ft" if r["Depth"] else "  ? "
        print(f"  {r['dist_nm']:5.1f} nm  {depth:>6}  {str(r['MatCat'] or ''):8}  {r['Name']}")

    here = os.path.dirname(os.path.abspath(__file__))
    out_csv = os.path.join(here, "harbor_reefs_nearby.csv")
    nearby[cols].to_csv(out_csv, index=False)
    print(f"\nWrote {len(nearby)} rows to {out_csv}")

    out_map = os.path.join(here, "harbor_map.html")
    write_map(nearby, ORIGIN_RAMP, origin_lat, origin_lon, RADIUS_NM, out_map)
    print(f"Wrote map to {out_map} — open it in a browser.")


if __name__ == "__main__":
    main()
