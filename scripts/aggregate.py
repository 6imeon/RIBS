"""Borough scorecard: supply (brownfield register) vs demand (WhereToBuild)
vs the London Plan ten-year target.

Headline framing: land that already has planning permission but has not been
started, expressed in hectares and in the council's own dwelling estimate,
against the borough's ten-year target and its demand pressure.

DUA: demand columns derive from the WhereToBuild MSOA extract (CAGE, Warwick).
Borough-level aggregates only; no MSOA-level output is written to data/processed.
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
REF = ROOT / "data" / "reference"
RESTRICTED = ROOT / "data" / "restricted"

MIN_SITES_FLAG = 10  # §5.4 suppression threshold


def demand_by_borough() -> pd.DataFrame | None:
    """MSOA demand -> borough mean. Returns None if the DUA file is absent,
    so the whole pipeline still runs supply-only without it."""
    src = RESTRICTED / "wheretobuild_msoa_stats.csv"
    if not src.exists():
        print("NOTE: WhereToBuild extract absent — demand columns will be null.")
        return None

    w = pd.read_csv(src, dtype={"msoa_code": str})
    lu = pd.read_csv(RAW / "msoa11_msoa21_lad22.csv", dtype=str)
    lu = lu[lu.LAD22CD.str.startswith("E09", na=False)].drop_duplicates("MSOA21CD")

    m = lu.merge(w, left_on="MSOA21CD", right_on="msoa_code", how="left")
    print(f"demand: {m.msoa_code.notna().sum()}/{len(m)} London MSOAs matched")

    # area-weighted where it matters: gap_per_km2 is a density, so a plain
    # mean over MSOAs is the borough's mean local pressure. `gap` is a count,
    # so it sums. Both are reported.
    #
    # Medians are carried alongside the means because London's distribution is
    # badly skewed by City of London — the mean overstates typical pressure by
    # ~58%. The app's comparison sentence divides by a London-wide median, so
    # the borough figure it divides must be a median too or the ratio is
    # comparing two different kinds of average.
    out = m.groupby("LAD22CD").agg(
        demand_gap_per_km2=("gap_per_km2", "mean"),
        demand_gap_per_km2_median=("gap_per_km2", "median"),
        demand_gap_total=("gap", "sum"),
        tightness_mean=("tightness", "mean"),
        tightness_median=("tightness", "median"),
        msoas=("MSOA21CD", "nunique"),
        # A "surplus" MSOA has supply exceeding demand. Only 3 exist in all of
        # London, which is itself the finding — 31 of 33 boroughs have none.
        msoas_surplus=("gap", lambda s: int((s < 0).sum())),
    ).reset_index().rename(columns={"LAD22CD": "gss_code"})
    return out


def london_reference(demand: pd.DataFrame | None) -> dict:
    """London-wide medians — the denominators for the app's 'Nx a typical
    London area' sentence. Recomputed from source rather than hard-coded so
    they cannot drift away from the borough figures they are compared against.
    """
    src = RESTRICTED / "wheretobuild_msoa_stats.csv"
    if demand is None or not src.exists():
        return {}
    w = pd.read_csv(src, dtype={"msoa_code": str})
    lu = pd.read_csv(RAW / "msoa11_msoa21_lad22.csv", dtype=str)
    lu = lu[lu.LAD22CD.str.startswith("E09", na=False)].drop_duplicates("MSOA21CD")
    m = lu.merge(w, left_on="MSOA21CD", right_on="msoa_code", how="inner")
    ref = {
        "median_gap_per_km2": round(float(m["gap_per_km2"].median()), 1),
        "median_tightness": round(float(m["tightness"].median()), 4),
        "mean_gap_per_km2": round(float(m["gap_per_km2"].mean()), 1),
        "msoas": int(len(m)),
        "msoas_surplus": int((m["gap"] < 0).sum()),
    }
    print(f"london reference: median gap/km2 {ref['median_gap_per_km2']}, "
          f"median tightness {ref['median_tightness']}, "
          f"{ref['msoas_surplus']}/{ref['msoas']} MSOAs in surplus")
    return ref


def main() -> None:
    sites = pd.read_csv(PROC / "london_sites.csv", low_memory=False)
    targets = pd.read_csv(REF / "borough_targets.csv")

    sites["permission_date"] = pd.to_datetime(sites["permission_date"], errors="coerce")

    def block(df: pd.DataFrame, suffix: str) -> pd.DataFrame:
        out = df.groupby("gss_code").agg(**{
            f"sites{suffix}": ("entity", "count"),
            f"hectares{suffix}": ("hectares", "sum"),
            f"homes_min{suffix}": ("minimum-net-dwellings", "sum"),
            f"homes_max{suffix}": ("maximum-net-dwellings", "sum"),
            # How many sites in THIS segment actually state a capacity. A
            # segment where none do sums to 0, which is missing data, not a
            # finding — distinct from a borough that genuinely records zero.
            f"homes_reported{suffix}": ("minimum-net-dwellings",
                                        lambda s: int(s.notna().sum())),
        })
        none_reported = out[f"homes_reported{suffix}"] == 0
        out.loc[none_reported, [f"homes_min{suffix}", f"homes_max{suffix}"]] = pd.NA
        return out

    total = block(sites, "_total")

    # Headline segment: permission granted, construction not started.
    pns = sites[sites["permitted_not_started"]]
    seg_pns = block(pns, "_permitted_not_started")

    unperm = sites[sites["permission_status"] == "not-permissioned"]
    seg_unperm = block(unperm, "_unpermissioned")

    deliv = sites[sites["deliverable_yes"] & sites["permitted_not_started"]]
    seg_deliv = block(deliv, "_pns_deliverable")

    sc = total.join([seg_pns, seg_unperm, seg_deliv], how="left").reset_index()

    # --- capacity-reporting coverage ---------------------------------------
    # 8 boroughs publish no dwelling numbers at all. A zero there is missing
    # data, not a finding — so we measure it and null the derived shares.
    cov = sites.groupby("gss_code").agg(
        homes_reported=("minimum-net-dwellings", lambda s: s.notna().sum()),
        sites_n=("entity", "count"),
        hectares_reported=("hectares", lambda s: s.notna().sum()),
    ).reset_index()
    cov["pct_sites_with_homes"] = cov.homes_reported / cov.sites_n * 100
    sc = sc.merge(cov[["gss_code", "pct_sites_with_homes"]], on="gss_code")

    sc = sc.merge(targets, on="gss_code", how="right")

    # --- public ownership & permission age ---------------------------------
    pub = sites.groupby("gss_code").apply(
        lambda g: pd.Series({
            "pct_hectares_public": (
                g.loc[g.public_owned, "hectares"].sum() / g["hectares"].sum() * 100
                if g["hectares"].sum() else pd.NA
            )
        }), include_groups=False
    ).reset_index()
    sc = sc.merge(pub, on="gss_code", how="left")

    now = pd.Timestamp("2026-08-01")
    age = pns.dropna(subset=["permission_date"]).copy()
    age["yrs"] = (now - age["permission_date"]).dt.days / 365.25
    age_agg = age.groupby("gss_code").agg(
        median_permission_age_years=("yrs", "median"),
        permissions_dated=("yrs", "count"),
    ).reset_index()
    sc = sc.merge(age_agg, on="gss_code", how="left")

    # --- demand -------------------------------------------------------------
    dem = demand_by_borough()
    if dem is not None:
        sc = sc.merge(dem, on="gss_code", how="left")
    # London-wide denominators are scalars, not per-borough facts, so they get
    # their own file rather than being repeated down 33 identical rows.
    ref = london_reference(dem)
    if ref:
        (PROC / "london_reference.json").write_text(json.dumps(ref, indent=2))

    # --- derived shares (null where capacity is unreported) -----------------
    has_homes = sc["pct_sites_with_homes"] > 0
    for col, src in [
        ("pct_of_target_pns", "homes_min_permitted_not_started"),
        ("pct_of_target_unpermissioned", "homes_min_unpermissioned"),
        ("pct_of_target_total", "homes_min_total"),
    ]:
        # Null unless the borough reports capacity AND this segment does.
        sc[col] = (sc[src] / sc["ten_year_target"] * 100).where(
            has_homes & sc[src].notna())

    sc["homes_capacity_reported"] = has_homes
    sc["data_quality_flag"] = ""
    sc.loc[sc["sites_total"].fillna(0) < MIN_SITES_FLAG, "data_quality_flag"] += "LOW_SITE_COUNT;"
    sc.loc[~has_homes, "data_quality_flag"] += "NO_CAPACITY_PUBLISHED;"
    sc.loc[(sc["pct_sites_with_homes"] > 0) & (sc["pct_sites_with_homes"] < 60),
           "data_quality_flag"] += "PARTIAL_CAPACITY;"

    # Homes figures are meaningless where nothing is published — null them so
    # no one reads a 0 as "this borough has no capacity".
    numeric_homes = [c for c in sc.columns
                     if c.startswith("homes_") and sc[c].dtype != bool]
    for c in numeric_homes:
        sc.loc[~has_homes, c] = pd.NA

    sc = sc.sort_values("pct_of_target_pns", ascending=False, na_position="last")
    sc.to_csv(PROC / "borough_scorecard.csv", index=False)

    print(f"\nwrote data/processed/borough_scorecard.csv ({len(sc)} boroughs)")
    print("\n=== PERMITTED BUT NOT STARTED — top 15 by share of 10-yr target ===")
    show = sc[sc.homes_capacity_reported].head(15)
    print(f"{'Borough':<24}{'Sites':>6}{'Ha':>9}{'Homes':>9}{'Target':>9}{'%tgt':>7}{'Age':>6}")
    print("-" * 70)
    for _, r in show.iterrows():
        print(f"{r['borough']:<24}{r['sites_permitted_not_started']:>6.0f}"
              f"{r['hectares_permitted_not_started']:>9.1f}"
              f"{r['homes_min_permitted_not_started']:>9,.0f}"
              f"{r['ten_year_target']:>9,.0f}{r['pct_of_target_pns']:>6.0f}%"
              f"{r['median_permission_age_years']:>6.1f}")

    nocap = sc[~sc.homes_capacity_reported]
    print(f"\n=== NO CAPACITY PUBLISHED ({len(nocap)}) — hectares only ===")
    for _, r in nocap.iterrows():
        print(f"  {r['borough']:<24}{r['sites_total']:>5.0f} sites"
              f"{r['hectares_permitted_not_started']:>9.1f} ha permitted-not-started")


if __name__ == "__main__":
    main()
