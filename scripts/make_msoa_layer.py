"""
make_msoa_layer.py  —  generate app/data/msoa_demand.geojson

Reads London MSOA demand data (gap, tightness) from wheretobuild_msoa_regions.csv
and joins to ONS MSOA 2021 BSC boundaries.

Output: app/data/msoa_demand.geojson
  Properties per feature: msoa_code, gap, lad_name

DUA NOTICE: output is derived from WhereToBuild (CAGE, University of Warwick).
Event-only. Do not commit or publish. See .gitignore.
"""
import csv, json, pathlib, time, urllib.request, urllib.parse

ROOT = pathlib.Path(__file__).parent.parent
MSOA_REGIONS = pathlib.Path.home() / "Downloads" / "wheretobuild_msoa_regions.csv"
OUT = ROOT / "app" / "data" / "msoa_demand.geojson"

ARCGIS = ("https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services"
          "/MSOA_2021_EW_BSC_V3_RUC/FeatureServer/0/query")

BATCH = 150  # codes per ArcGIS request

def fetch_batch(codes: list[str]) -> list[dict]:
    where = "MSOA21CD IN ({})".format(",".join(f"'{c}'" for c in codes))
    params = urllib.parse.urlencode({
        "where":       where,
        "outFields":   "MSOA21CD",
        "outSR":       "4326",
        "f":           "geojson",
        "resultRecordCount": len(codes) + 10,
    }).encode()
    req = urllib.request.Request(ARCGIS, data=params, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read()).get("features", [])

def main():
    if not MSOA_REGIONS.exists():
        raise FileNotFoundError(
            f"Cannot find {MSOA_REGIONS}\n"
            "Place wheretobuild_msoa_regions.csv in ~/Downloads/ and re-run."
        )

    # Load London MSOA demand data
    london = {}
    with open(MSOA_REGIONS, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["region"] != "London":
                continue
            code = row["msoa_code"]
            try:
                gap = float(row["gap"])
            except (ValueError, KeyError):
                gap = None
            london[code] = {"gap": gap, "lad_name": row.get("lad_name", "")}

    print(f"[msoa] {len(london)} London MSOAs loaded from demand dataset")

    codes = list(london.keys())
    batches = [codes[i:i+BATCH] for i in range(0, len(codes), BATCH)]
    features = []

    for i, batch in enumerate(batches):
        print(f"[msoa] Batch {i+1}/{len(batches)} ({len(batch)} codes)…")
        feats = fetch_batch(batch)
        for feat in feats:
            code = feat["properties"].get("MSOA21CD")
            if code in london:
                feat["properties"] = {
                    "msoa_code": code,
                    "gap":       london[code]["gap"],
                    "lad_name":  london[code]["lad_name"],
                }
                features.append(feat)
        if i < len(batches) - 1:
            time.sleep(0.3)

    gj = {"type": "FeatureCollection", "features": features}
    OUT.write_text(json.dumps(gj, separators=(",", ":")))
    surplus = sum(1 for f in features if (f["properties"]["gap"] or 0) < 0)
    print(f"[msoa] {len(features)} features written → {OUT}")
    print(f"[msoa] {surplus} surplus MSOAs (gap < 0), {len(features)-surplus} shortage")

if __name__ == "__main__":
    main()
