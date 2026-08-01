#!/usr/bin/env python3
"""End-to-end smoke test for the map build, with every network call stubbed.

WHY THIS EXISTS: on 2026-08-01 a refactor deleted the ORIGIN_RAMP constant but
left a reference to it in main(). `python -m py_compile` passed, every static
check passed, and the build died in CI with a NameError on the first real run.
A syntax check cannot catch a NameError; only executing main() can.

The FWC and DEP services are also unreachable from some sandboxes, so a
developer often cannot run the real thing locally. This stubs the four fetch
helpers and query_features, then runs main() for real and asserts on the HTML.

Run:
    python3 test_build.py
"""
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harbor_spots as hs   # noqa: E402

REEFS = [
    {"Name": "Novak Reef #1",   "Depth": 30, "MatCat": "Concrete", "Relief": None,
     "Lat_DD": 26.8095, "Long_DD": -82.3283},
    {"Name": "Cape Haze Reef",  "Depth": 24, "MatCat": "Concrete", "Relief": None,
     "Lat_DD": 26.7400, "Long_DD": -82.2600},
    # Deliberately far south: out of range from the default origin, in range from
    # Cabbage Key. It must still reach the browser, or selecting a southern origin
    # draws a range ring with a hole in it.
    {"Name": "Deep South Reef", "Depth": 45, "MatCat": "Vessel", "Relief": None,
     "Lat_DD": 26.4000, "Long_DD": -82.2000},
]
RAMPS = [
    {"RampName": "Ponce de Leon Park", "City": "Punta Gorda", "WaterBodyName": "Charlotte Harbor",
     "TotalLanes": 2, "Latitude": 26.9180, "Longitude": -82.0700},
    {"RampName": "Placida", "City": "Placida", "WaterBodyName": "Gasparilla Sound",
     "TotalLanes": 3, "Latitude": 26.8430, "Longitude": -82.2630},
]
EMPTY = {"type": "FeatureCollection", "features": []}


def main():
    hs.query_features = lambda url, where, out_fields: (
        REEFS if "Artificial_Reef" in url else RAMPS)
    hs.fetch_preserves = lambda bbox: EMPTY
    hs.fetch_seagrass = lambda bbox: EMPTY
    hs.fetch_zones = lambda bbox: EMPTY
    hs.fetch_manatee = lambda bbox: EMPTY

    hs.main()          # the point of the exercise: this must not raise

    out = pathlib.Path(hs.__file__).parent / "harbor_map.html"
    h = out.read_text()
    fail = []

    def check(label, ok):
        print(f"  {'ok  ' if ok else 'FAIL'} {label}")
        if not ok:
            fail.append(label)

    left = re.findall(r"__[A-Z]+__", h)
    check(f"no unsubstituted placeholders (found {left})", not left)

    reefs = json.loads(re.search(r"var reefs = (\[.*?\]);", h, re.S).group(1))
    check(f"all {len(REEFS)} reefs reach the browser, unfiltered by radius",
          len(reefs) == len(REEFS))
    check("the far-south reef survives (the bug this design prevents)",
          any(r["lat"] < 26.5 for r in reefs))
    check("reef payload carries no server-side dist",
          all("dist" not in r for r in reefs))

    curated = json.loads(re.search(r"var curated = (\[.*?\]);", h, re.S).group(1))
    check("curated origins injected", len(curated) > 0)
    check("exactly one default origin",
          sum(1 for o in curated if o.get("def")) == 1)

    check("origin selector present", 'id="origin"' in h)
    check("magnetic variation shipped", "MAG_VAR_W = " in h)
    check("legend explains the marina marker", "marina / creek" in h)
    check("legend no longer says 'origin ramp'", "origin ramp" not in h)

    print()
    if fail:
        print(f"FAILED: {len(fail)} check(s)")
        return 1
    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
