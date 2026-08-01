"""Export map payloads: simplified borough boundaries + site points.

Writes app/data/*.json. Everything is embedded locally so the page runs
with wifi off (§7). Geometry is simplified hard — at London-wide zoom the
extra vertices cost render time and show nothing (§4.2).
"""
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
APP = ROOT / "app" / "data"

SIMPLIFY_DP = 3  # ~110m at London's latitude — plenty for borough outlines


def parse_multipolygon(wkt: str):
    """WKT MULTIPOLYGON/POLYGON -> GeoJSON coords, decimated.

    No shapely dependency: we round coordinates to SIMPLIFY_DP and drop
    consecutive duplicates. That is a real reduction in vertex count while
    preserving ring topology (first==last is re-closed).
    """
    if not isinstance(wkt, str) or "(" not in wkt:
        return None
    is_multi = wkt.strip().upper().startswith("MULTIPOLYGON")
    body = wkt[wkt.index("("):]

    def ring(s: str):
        pts = []
        last = None
        for m in re.finditer(r"(-?\d+\.?\d*)\s+(-?\d+\.?\d*)", s):
            p = [round(float(m.group(1)), SIMPLIFY_DP),
                 round(float(m.group(2)), SIMPLIFY_DP)]
            if p != last:
                pts.append(p)
                last = p
        if len(pts) < 4:
            return None
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        return pts

    polys = []
    # split top-level polygons of a MULTIPOLYGON: "((...)),((...))"
    chunks = re.findall(r"\(\(.*?\)\)", body, re.S) if is_multi else [body]
    for ch in chunks:
        rings = [ring(r) for r in re.findall(r"\(([^()]*)\)", ch)]
        rings = [r for r in rings if r]
        if rings:
            polys.append(rings)
    if not polys:
        return None
    return {"type": "MultiPolygon", "coordinates": polys}


def main() -> None:
    APP.mkdir(parents=True, exist_ok=True)
    sc = pd.read_csv(PROC / "borough_scorecard.csv")

    # --- boundaries ---------------------------------------------------------
    lpa = pd.read_csv(RAW / "local-planning-authority.csv", dtype=str,
                      usecols=["name", "geometry", "reference", "end-date"])
    lpa = lpa[lpa["end-date"].fillna("").str.strip() == ""]
    lpa["gss_code"] = lpa["reference"]

    feats = []
    matched = 0
    # LPA rows carry an E60 reference; boroughs are E09 — join by cleaned name.
    lpa["bname"] = (lpa["name"].str.replace(r"\s+LPA$", "", regex=True)
                    .str.replace("&", "and", regex=False).str.strip())
    sc["bname"] = sc["borough"].str.replace("&", "and", regex=False).str.strip()
    name_to_row = {r["bname"]: r for _, r in sc.iterrows()}

    for _, row in lpa.iterrows():
        rec = name_to_row.get(row["bname"])
        if rec is None:
            continue
        geom = parse_multipolygon(row["geometry"])
        if geom is None:
            continue
        matched += 1
        props = {"borough": rec["borough"], "gss_code": rec["gss_code"]}
        for c in ("sites_total", "hectares_total",
                  "hectares_permitted_not_started",
                  "homes_min_permitted_not_started",
                  "homes_max_permitted_not_started",
                  "homes_min_unpermissioned", "ten_year_target",
                  "pct_of_target_pns", "pct_of_target_unpermissioned",
                  "median_permission_age_years", "demand_gap_per_km2",
                  "tightness_mean", "pct_hectares_public",
                  "pct_sites_with_homes", "homes_capacity_reported",
                  "data_quality_flag", "sites_permitted_not_started"):
            v = rec.get(c)
            if pd.isna(v):
                props[c] = None
            elif isinstance(v, (bool, str)):
                props[c] = v
            else:
                props[c] = round(float(v), 2)
        feats.append({"type": "Feature", "properties": props, "geometry": geom})

    gj = {"type": "FeatureCollection", "features": feats}
    out = APP / "boroughs.json"
    out.write_text(json.dumps(gj, separators=(",", ":")))
    print(f"boundaries: {matched}/33 boroughs  -> {out.stat().st_size/1e6:.1f} MB")

    # --- site points --------------------------------------------------------
    sites = pd.read_csv(PROC / "london_sites.csv", low_memory=False)
    pts = sites.dropna(subset=["lat", "lon"]).copy()

    def clean(v, nd=None):
        if pd.isna(v):
            return None
        return round(float(v), nd) if nd is not None else v

    # Explicit column access — positional itertuples accessors break silently
    # if the upstream column order ever shifts.
    recs = []
    for _, r in pts.iterrows():
        recs.append({
            "b": r["borough"],
            "y": round(r["lat"], 5),
            "x": round(r["lon"], 5),
            "ha": clean(r["hectares"], 3),
            "dmin": clean(r["minimum-net-dwellings"], 0),
            "dmax": clean(r["maximum-net-dwellings"], 0),
            "st": r["permission_status"],
            "pns": bool(r["permitted_not_started"]),
            "dlv": bool(r["deliverable_yes"]),
            "pub": bool(r["public_owned"]),
            "pd": (str(r["permission_date"])[:10]
                   if not pd.isna(r["permission_date"]) else None),
            "ad": (str(r["site-address"])[:80]
                   if not pd.isna(r["site-address"]) else None),
            "u": (r["site-plan-url"]
                  if not pd.isna(r["site-plan-url"]) else None),
        })
    out2 = APP / "sites.json"
    out2.write_text(json.dumps(recs, separators=(",", ":")))
    print(f"sites: {len(recs):,} mappable of {len(sites):,}"
          f"  -> {out2.stat().st_size/1e6:.1f} MB")

    sc.drop(columns=["bname"]).to_json(APP / "scorecard.json",
                                       orient="records", double_precision=2)
    print("scorecard.json written")


if __name__ == "__main__":
    main()
