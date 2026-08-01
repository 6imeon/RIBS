"""Build-opportunity index: pct_of_target_pns + demand_gap_per_km2 +
homes_min_permitted_not_started.

Method: percentile-rank each of the three components across boroughs where
pct_of_target_pns is published. A borough must clear the 50th percentile on
ALL THREE to receive a score; the score is then the mean of the three
percentile ranks (0-100). Boroughs that don't clear all three, or that have
no published PNS capacity, are left unscored (None) rather than assigned zero.

See INDEX_METHODOLOGY.md for full reasoning.

Input:  data/processed/borough_scorecard.csv
Output: data/processed/borough_opportunity_index.csv
"""
import pandas as pd

THRESHOLD = 0.5

IN_PATH = "data/processed/borough_scorecard.csv"
OUT_PATH = "data/processed/borough_opportunity_index.csv"


def main():
    df = pd.read_csv(IN_PATH)

    rankable = df[df["pct_of_target_pns"].notna()].copy()
    not_rankable = df[df["pct_of_target_pns"].isna()].copy()

    rankable["pns_rank"] = rankable["pct_of_target_pns"].rank(pct=True)
    rankable["demand_rank"] = rankable["demand_gap_per_km2"].rank(pct=True)
    rankable["homes_rank"] = rankable["homes_min_permitted_not_started"].rank(pct=True)

    qualifies = (
        (rankable["pns_rank"] >= THRESHOLD)
        & (rankable["demand_rank"] >= THRESHOLD)
        & (rankable["homes_rank"] >= THRESHOLD)
    )

    rankable["opportunity_index"] = None
    rankable.loc[qualifies, "opportunity_index"] = (
        rankable.loc[qualifies, ["pns_rank", "demand_rank", "homes_rank"]]
        .mean(axis=1)
        * 100
    ).round(1)

    rankable["low_confidence"] = rankable["data_quality_flag"].str.contains(
        "PARTIAL_CAPACITY|LOW_SITE_COUNT", na=False
    )

    not_rankable["opportunity_index"] = None
    not_rankable["low_confidence"] = None
    not_rankable["pns_rank"] = None
    not_rankable["demand_rank"] = None
    not_rankable["homes_rank"] = None

    out = pd.concat([rankable, not_rankable], ignore_index=True)
    out = out.sort_values(
        by="opportunity_index", ascending=False, na_position="last"
    )

    keep_cols = [
        "borough",
        "gss_code",
        "opportunity_index",
        "low_confidence",
        "pct_of_target_pns",
        "demand_gap_per_km2",
        "homes_min_permitted_not_started",
        "data_quality_flag",
    ]
    out[keep_cols].to_csv(OUT_PATH, index=False)

    print(f"{qualifies.sum()} boroughs scored, {len(not_rankable)} excluded (no PNS capacity)")
    print(out[out["opportunity_index"].notna()][["borough", "opportunity_index", "low_confidence"]].to_string(index=False))
    print(f"\nWritten to {OUT_PATH}")


if __name__ == "__main__":
    main()
