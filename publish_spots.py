"""
Harbor Spots — Milestone 5: publish your own hosted feature layer.

Uploads the nearby-reefs CSV as an item in your ArcGIS content and publishes it
into a hosted feature layer, using the publish-scoped API key.

This talks to the ArcGIS REST API directly with `requests`, using the API key
as the token. We do that (instead of the arcgis Python SDK) because the SDK
treats an API-key session as anonymous for content operations. The key itself
carries the content privileges, so the raw REST calls are authorized.

Run:
  export ARCGIS_API_KEY="<your PUBLISH-scoped key>"
  python3 publish_spots.py

Requires the privileges we scoped on the publish key:
"Create, update, and delete content" and "Publish hosted feature layers".

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
        print("\nPublish failed:")
        print(json.dumps(pub["error"], indent=2))
        msg = json.dumps(pub["error"]).lower()
        if "credit" in msg or "billing" in msg or "subscription" in msg or "pay" in msg:
            print("\nThis looks like the billing gate. Enable pay-as-you-go in the")
            print("Location Platform dashboard (Billing tab), then re-run. Your data is")
            print("tiny, so it stays in the free tier. The CSV item already uploaded.")
        raise SystemExit(1)

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
