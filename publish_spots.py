"""
Harbor Spots — upload the reef CSV to ArcGIS as a content item.

Uploads the nearby-reefs CSV to your ArcGIS content over the REST API, using an
API key as the token. Uploading works with a content-scoped API key.

Learned the hard way: on an ArcGIS Location Platform account you cannot *publish*
the uploaded item into a hosted feature layer with an API key, nor share it
publicly. Those operations require a signed-in user (the ArcGIS Online web UI or
an OAuth user token). So this script gets the data into ArcGIS; you finish the
publish from the item's page (Publish button). That upload-by-API, publish-by-user
split is common in real integrations.

Run:
  export ARCGIS_API_KEY="<your content-scoped key>"
  python3 publish_spots.py
  # then open the uploaded item in ArcGIS and click Publish

Each run uploads a fresh timestamped item. Delete old ones from your ArcGIS
content when tidying up.

© Brian Beals, LLC · brianbeals.com
"""

import os
import json
import time
import requests

# From your ArcGIS Location Platform account (seen in the item URLs / dashboard).
ORG = "https://brianbeals.maps.arcgis.com"
USERNAME = "bbeals42"

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(HERE, "harbor_reefs_nearby.csv")
TITLE = "My Harbor Spots"


def main():
    key = os.environ.get("ARCGIS_API_KEY")
    if not key:
        raise SystemExit("Set ARCGIS_API_KEY to your publish-scoped key first.")
    if not os.path.exists(CSV_FILE):
        raise SystemExit(f"{CSV_FILE} not found — run harbor_spots.py first.")

    # Unique suffix each run so ArcGIS never rejects a name as a duplicate
    # (listing/deleting prior items needs a real user session, which an API
    # key doesn't provide, so we sidestep collisions with unique names).
    stamp = time.strftime("%Y%m%d-%H%M%S")
    upload_name = f"harbor_spots_{stamp}.csv"

    # 1. Upload the CSV as a content item (REST addItem).
    print(f"Uploading as {upload_name} ...")
    add_url = f"{ORG}/sharing/rest/content/users/{USERNAME}/addItem"
    with open(CSV_FILE, "rb") as fh:
        r = requests.post(
            add_url,
            data={
                "f": "json",
                "token": key,
                "title": f"{TITLE} {stamp}",
                "type": "CSV",
                "tags": "harbor,fishing,reefs,charlotte harbor",
                "snippet": "Curated Charlotte Harbor reef spots from Harbor Spots.",
            },
            files={"file": (upload_name, fh, "text/csv")},
            timeout=120,
        )
    add = r.json()
    if not add.get("success"):
        print("Upload failed:", json.dumps(add, indent=2))
        raise SystemExit(1)
    item_id = add["id"]
    print(f"  uploaded item {item_id}")

    # 2. Publish it into a hosted feature layer from the coordinate columns.
    print("Publishing hosted feature layer ...")
    pub_url = f"{ORG}/sharing/rest/content/users/{USERNAME}/publish"
    publish_parameters = {
        "name": f"my_harbor_spots_{stamp}",
        "locationType": "coordinates",
        "latitudeFieldName": "Lat_DD",
        "longitudeFieldName": "Long_DD",
    }
    r2 = requests.post(
        pub_url,
        data={
            "f": "json",
            "token": key,
            "itemID": item_id,
            "filetype": "csv",
            "publishParameters": json.dumps(publish_parameters),
        },
        timeout=180,
    )
    pub = r2.json()

    if "error" in pub:
        print("\nPublish via API key was refused (expected on Location Platform):")
        print(json.dumps(pub["error"], indent=2))
        print("\nThe CSV item uploaded fine. Publishing a hosted feature layer needs")
        print("a signed-in user, so open the item in ArcGIS and click Publish:")
        print(f"  {ORG}/home/item.html?id={item_id}")
        raise SystemExit(0)

    svc = (pub.get("services") or [{}])[0]
    svc_item = svc.get("serviceItemId")
    if svc_item:
        print(f"\nPublished hosted feature layer.")
        print(f"View it:  {ORG}/home/item.html?id={svc_item}")
        print("\nThis layer is now yours to edit. Milestone 5 done.")
    else:
        print("\nUnexpected publish response:")
        print(json.dumps(pub, indent=2))


if __name__ == "__main__":
    main()
