"""London Land Ledger — supply-side pipeline.

Brownfield register -> live London sites -> borough scorecard.

Every output column traces to a source column. Nothing is modelled, estimated
or interpolated. Where the register is blank we emit null and count it.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
REF = ROOT / "data" / "reference"

LONDON_GSS_PREFIX = "E09"

# --- planning-permission-status normalisation -------------------------------
# The register is meant to hold three values; London rows contain twelve,
# including free text and typos. Every reassignment below is printed at run
# time so it can be audited. Anything unmapped becomes "unknown", never
# silently bucketed into a real category.
STATUS_MAP = {
    "permissioned": "permissioned",
    "not-permissioned": "not-permissioned",
    "pending-decision": "pending-decision",
    # typos / free text -> permissioned
    "pemrissioned": "permissioned",
    "full permissioned": "permissioned",
    "full permission": "permissioned",
    # a site under construction necessarily holds permission
    "started": "permissioned",
    # submitted but not determined
    "submitted": "pending-decision",
    "application pending": "pending-decision",
    # allocated in a local plan is NOT a permission
    "allocation": "not-permissioned",
    "site allocation": "not-permissioned",
}


def london_authorities() -> pd.DataFrame:
    la = pd.read_csv(RAW / "local-authority.csv", dtype=str)
    lon = la[la["statistical-geography"].fillna("").str.startswith(LONDON_GSS_PREFIX)].copy()
    lon["borough"] = (
        lon["name"]
        .str.replace(r"^(London Borough of|Royal Borough of)\s+", "", regex=True)
        .str.replace("City of London Corporation", "City of London", regex=False)
        .str.replace("City of Westminster", "Westminster", regex=False)
        .str.strip()
    )
    return lon[["entity", "borough", "statistical-geography"]].rename(
        columns={"statistical-geography": "gss_code"}
    )


def parse_point(s: pd.Series) -> pd.DataFrame:
    """POINT(lon lat) WKT -> lon/lat floats. Unparseable -> null, counted."""
    ex = s.str.extract(r"POINT\s*\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)")
    return pd.DataFrame({
        "lon": pd.to_numeric(ex[0], errors="coerce"),
        "lat": pd.to_numeric(ex[1], errors="coerce"),
    })


def main() -> None:
    PROC.mkdir(parents=True, exist_ok=True)
    lon = london_authorities()

    bf = pd.read_csv(RAW / "brownfield-land.csv", dtype=str, low_memory=False)
    print(f"national register rows          : {len(bf):,}")

    sites = bf.merge(lon, left_on="organisation-entity", right_on="entity",
                     how="inner", suffixes=("", "_la"))
    print(f"London rows (incl. archived)    : {len(sites):,}")

    # --- live filter: end-date empty means not completed / not withdrawn ----
    ended = sites["end-date"].fillna("").str.strip() != ""
    rejected = sites[ended].copy()
    rejected["reject_reason"] = "archived (end-date populated)"
    sites = sites[~ended].copy()
    print(f"  excluded, archived            : {ended.sum():,}")
    print(f"London live sites               : {len(sites):,}")

    # --- numerics: coerce, and log what failed per column -------------------
    print("\nnull/uncoercible counts (live London sites):")
    for col in ("hectares", "minimum-net-dwellings", "maximum-net-dwellings"):
        raw_nonblank = sites[col].fillna("").str.strip() != ""
        sites[col] = pd.to_numeric(sites[col], errors="coerce")
        failed = (raw_nonblank & sites[col].isna()).sum()
        print(f"  {col:<24} null={sites[col].isna().sum():>5}"
              f"  ({sites[col].isna().mean():>5.1%})  uncoercible={failed}")

    # A site cannot have negative area or negative dwellings.
    for col in ("hectares", "minimum-net-dwellings", "maximum-net-dwellings"):
        bad = sites[col] < 0
        if bad.any():
            print(f"  !! {col}: {bad.sum()} negative values -> null")
            sites.loc[bad, col] = pd.NA

    # min should not exceed max; where it does, the pair is untrustworthy.
    swapped = (sites["minimum-net-dwellings"] > sites["maximum-net-dwellings"])
    if swapped.any():
        print(f"  !! min>max dwellings on {swapped.sum()} sites -> flagged, kept as-is")
    sites["flag_min_gt_max"] = swapped

    # --- permission status normalisation -----------------------------------
    raw_status = sites["planning-permission-status"].fillna("").str.strip()
    key = raw_status.str.lower()
    sites["permission_status"] = key.map(STATUS_MAP).fillna(
        pd.Series(["unknown"] * len(sites), index=sites.index)
    )
    sites.loc[key == "", "permission_status"] = "unknown"

    print("\npermission-status normalisation:")
    audit = (
        pd.DataFrame({"raw": raw_status.replace("", "<blank>"),
                      "normalised": sites["permission_status"]})
        .value_counts().reset_index(name="n").sort_values("n", ascending=False)
    )
    for _, r in audit.iterrows():
        mark = "" if r["raw"].lower() == r["normalised"] else "   <-- remapped"
        print(f"  {r['raw']:<22} -> {r['normalised']:<18}{r['n']:>6}{mark}")
    audit.to_csv(PROC / "status_normalisation_audit.csv", index=False)

    # --- "permitted but not started" ---------------------------------------
    # The register's own `Started` value marks sites under construction. Those
    # are stalled-no-longer, so we carve them out. This is a better proxy than
    # end-date alone, and we name it as a proxy in the README.
    sites["is_started"] = key.eq("started")
    sites["permitted_not_started"] = (
        (sites["permission_status"] == "permissioned") & ~sites["is_started"]
    )

    # --- geometry -----------------------------------------------------------
    pts = parse_point(sites["point"].fillna(""))
    sites[["lon", "lat"]] = pts
    unparsed = sites["lat"].isna()
    # London bounding box sanity check: anything outside is a bad coordinate.
    outside = (~unparsed) & ~(
        sites["lat"].between(51.20, 51.75) & sites["lon"].between(-0.60, 0.35)
    )
    if outside.any():
        print(f"\n  !! {outside.sum()} sites plot outside London bbox -> geo nulled")
        sites.loc[outside, ["lat", "lon"]] = pd.NA
    nogeo = sites["lat"].isna()  # after nulling, so this matches the written file
    print(f"sites without usable coordinates : {nogeo.sum()} "
          f"({nogeo.mean():.1%}) — kept in table, absent from map")

    sites["deliverable_yes"] = sites["deliverable"].fillna("").str.strip().str.lower() == "yes"
    sites["public_owned"] = (
        sites["ownership-status"].fillna("").str.strip().str.lower()
        == "owned-by-a-public-authority"
    )
    sites["permission_date"] = pd.to_datetime(
        sites["planning-permission-date"], errors="coerce", format="mixed"
    )

    rejected.to_csv(PROC / "rejected_rows.csv", index=False)
    keep = [
        "entity", "borough", "gss_code", "reference", "name", "site-address",
        "hectares", "minimum-net-dwellings", "maximum-net-dwellings",
        "permission_status", "permitted_not_started", "is_started",
        "planning-permission-type", "permission_date", "deliverable_yes",
        "public_owned", "lat", "lon", "site-plan-url",
        "planning-permission-history", "flag_min_gt_max", "entry-date",
    ]
    sites[keep].to_csv(PROC / "london_sites.csv", index=False)
    print(f"\nwrote data/processed/london_sites.csv ({len(sites):,} rows)")
    return sites


if __name__ == "__main__":
    main()
