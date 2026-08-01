"""Build-opportunity index: pct_of_target_pns + demand + absolute stalled homes.

Two outputs, deliberately kept separate:

1. `opportunity_index` (0-100, continuous) - the mean of the three percentile
   ranks, computed for every borough where pct_of_target_pns is published
   (24/33). This is the MAP FILL - a full gradient, not gated by a threshold,
   so the choropleth is fully populated rather than mostly blank.

2. `all_three_high` (boolean) - True only if the borough ALSO clears the 50th
   percentile on all three components independently. This is a stricter,
   separate claim ("genuinely strong on every axis at once", not just a good
   average) and should be rendered as a badge/star on top of the map fill,
   not as the map fill itself.

Boroughs with no published PNS capacity (9/33) are left unscored (None), not
assigned zero, and should render as insufficient-data (hatched/grey) on the map.

Demand uses the MEDIAN across a borough's MSOAs, not the mean. London's
gap_per_km2 distribution is skewed ~58% (London mean 606 vs median 383), and the
rest of the app standardised on medians when the demand lens was built - ranking
here on the mean would let this table and the app's own comparison sentences
disagree about the same borough. See INDEX_METHODOLOGY.md.

See INDEX_METHODOLOGY.md for full reasoning.

Input:  data/processed/borough_scorecard.csv
Output: data/processed/borough_opportunity_index.csv
"""
from pathlib import Path

import pandas as pd

THRESHOLD = 0.5

ROOT = Path(__file__).resolve().parent.parent
IN_PATH = ROOT / "data" / "processed" / "borough_scorecard.csv"
OUT_PATH = ROOT / "data" / "processed" / "borough_opportunity_index.csv"

# Median, not mean — see the module docstring.
DEMAND_COL = "demand_gap_per_km2_median"


def main():
    df = pd.read_csv(IN_PATH)

    rankable = df[df["pct_of_target_pns"].notna()].copy()
    not_rankable = df[df["pct_of_target_pns"].isna()].copy()

    rankable["pns_rank"] = rankable["pct_of_target_pns"].rank(pct=True)
    rankable["demand_rank"] = rankable[DEMAND_COL].rank(pct=True)
    rankable["homes_rank"] = rankable["homes_min_permitted_not_started"].rank(pct=True)

    # 1. continuous score for every rankable borough - this is the map fill
    rankable["opportunity_index"] = (
        rankable[["pns_rank", "demand_rank", "homes_rank"]].mean(axis=1) * 100
    ).round(1)

    # 2. separate, stricter flag - genuinely high on all three at once
    rankable["all_three_high"] = (
        (rankable["pns_rank"] >= THRESHOLD)
        & (rankable["demand_rank"] >= THRESHOLD)
        & (rankable["homes_rank"] >= THRESHOLD)
    )

    rankable["low_confidence"] = rankable["data_quality_flag"].str.contains(
        "PARTIAL_CAPACITY|LOW_SITE_COUNT", na=False
    )

    not_rankable["opportunity_index"] = None
    not_rankable["all_three_high"] = None
    not_rankable["low_confidence"] = None

    out = pd.concat([rankable, not_rankable], ignore_index=True)
    # Secondary sort by name: three boroughs tie at 47.2, and without a
    # deterministic tiebreak this CSV and the app's table disagree about the
    # order of rows that are in fact equal.
    out = out.sort_values(
        by=["opportunity_index", "borough"], ascending=[False, True],
        na_position="last"
    )

    keep_cols = [
        "borough",
        "gss_code",
        "opportunity_index",
        "all_three_high",
        "low_confidence",
        "pct_of_target_pns",
        DEMAND_COL,
        "homes_min_permitted_not_started",
        "data_quality_flag",
    ]
    out[keep_cols].to_csv(OUT_PATH, index=False)

    print(f"{len(rankable)} boroughs scored (continuous), "
          f"{rankable['all_three_high'].sum()} clear all three, "
          f"{len(not_rankable)} excluded (no PNS capacity)")
    print(out[out["opportunity_index"].notna()][
        ["borough", "opportunity_index", "all_three_high", "low_confidence"]
    ].to_string(index=False))
    print(f"\nWritten to {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
