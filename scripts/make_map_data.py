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
INDEX = ROOT / "app" / "index.html"

SIMPLIFY_DP = 3  # ~110m at London's latitude — plenty for borough outlines

# The scorecard fields the page reads out of the inlined `DATA` literal.
#
# `DATA` is inlined rather than fetched so the ledger view — the headline, the
# quadrant chart and the ranked table — still renders from a file:// page with
# no server. That is worth keeping, but it used to mean hand-editing a 33-object
# literal: the list silently froze, and when the demand-lens columns were added
# the leaderboard rendered zero rows and the surplus stat read "0 of 33" with no
# error anywhere. So the literal is now generated here, and this list is the
# contract — a name that is not in the scorecard aborts the build.
DATA_FIELDS = [
    "borough", "sites_permitted_not_started", "hectares_permitted_not_started",
    "homes_min_permitted_not_started", "homes_max_permitted_not_started",
    "ten_year_target", "pct_of_target_pns", "median_permission_age_years",
    "homes_capacity_reported", "sites_total", "hectares_total",
    "data_quality_flag", "pct_sites_with_homes", "homes_min_unpermissioned",
    "pct_hectares_public",
    # demand lens
    "demand_gap_per_km2", "demand_gap_per_km2_median", "tightness_median",
    "msoas", "msoas_surplus",
]
DATA_RE = re.compile(r"<script>const DATA=\[.*?\];</script>", re.S)


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


def _generic_url(u) -> bool:
    """True if the url can't possibly point at one specific site.

    A per-site link needs something identifying it — a query string, a
    fragment, or a deep path. A bare register landing page has none, so it
    lands the reader on a borough-wide map with no idea which dot to look at.
    """
    if pd.isna(u):
        return False
    return "?" not in str(u) and "#" not in str(u)


def inject_data(sc: pd.DataFrame) -> None:
    """Rewrite the inlined `const DATA=[...]` literal in app/index.html.

    Every failure here is raised, never warned. The bug this replaces was
    silent — the page loaded, the console was clean, and one panel was simply
    empty. A broken build is far cheaper than a plausible-looking wrong one.
    """
    missing = [c for c in DATA_FIELDS if c not in sc.columns]
    if missing:
        raise SystemExit(
            f"index.html needs scorecard fields that aggregate.py did not "
            f"produce: {missing}. Either add them upstream or drop them from "
            f"DATA_FIELDS — do not leave the page reading a column that is "
            f"not there.")

    html = INDEX.read_text()
    if len(DATA_RE.findall(html)) != 1:
        raise SystemExit(
            f"expected exactly 1 `const DATA=[…]` block in {INDEX.name}, found "
            f"{len(DATA_RE.findall(html))}. The literal was probably reformatted; "
            f"fix it or this script will silently stop updating the page.")

    # Order matches the ledger's default sort so a hand-read of the file and the
    # rendered table agree.
    recs = json.loads(sc[DATA_FIELDS].round(2)
                      .to_json(orient="records", double_precision=2))
    block = "<script>const DATA=" + json.dumps(recs, separators=(",", ":")) + ";</script>"
    # A plain replacement string would treat backslashes and \g as escapes.
    updated = DATA_RE.sub(lambda _m: block, html, count=1)
    if updated != html:
        INDEX.write_text(updated)
        print(f"index.html: DATA refreshed ({len(recs)} boroughs, "
              f"{len(DATA_FIELDS)} fields)")
    else:
        print(f"index.html: DATA already current ({len(recs)} boroughs)")


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
                  "demand_gap_per_km2_median", "tightness_median",
                  "msoas", "msoas_surplus",
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
            # The register's own entity id. Unlike site-plan-url this always
            # resolves, so the app can always offer one working link.
            "e": int(r["entity"]),
            "u": (r["site-plan-url"]
                  if not pd.isna(r["site-plan-url"]) else None),
            # Roughly half of site-plan-urls are a borough's generic register
            # landing page, not this site's plan, and a sampled check found
            # ~37% of the distinct urls dead (404, timeout, host gone). Flag
            # the generic ones so the app can label rather than oversell them.
            "ug": bool(_generic_url(r["site-plan-url"])),
        })
    out2 = APP / "sites.json"
    out2.write_text(json.dumps(recs, separators=(",", ":")))
    print(f"sites: {len(recs):,} mappable of {len(sites):,}"
          f"  -> {out2.stat().st_size/1e6:.1f} MB")

    sc.drop(columns=["bname"]).to_json(APP / "scorecard.json",
                                       orient="records", double_precision=2)
    print("scorecard.json written")

    # London-wide medians: the denominators behind "Nx a typical London area".
    ref_src = PROC / "london_reference.json"
    if ref_src.exists():
        (APP / "london_reference.json").write_text(ref_src.read_text())
        print("london_reference.json written")

    # Last, so the page is only rewritten once every payload beside it is valid.
    inject_data(sc)


if __name__ == "__main__":
    main()
