"""Step 0 — viability gate.

Filter the national brownfield register to the 33 London boroughs and count
sites per borough. Prints a 33-row table and a coverage verdict.

Per the brief: STOP AND REPORT after this. Do not silently proceed with
partial coverage.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"

# The 33 London local authorities are exactly the ONS statistical-geography
# codes E09000001..E09000033. Using the code rather than a name match avoids
# false hits ("City of London" vs "City of Westminster") and is stable.
LONDON_GSS_PREFIX = "E09"


def load_london_authorities() -> pd.DataFrame:
    la = pd.read_csv(RAW / "local-authority.csv", dtype=str)
    lon = la[la["statistical-geography"].fillna("").str.startswith(LONDON_GSS_PREFIX)].copy()
    lon["borough"] = (
        lon["name"]
        .str.replace(r"^(London Borough of|Royal Borough of)\s+", "", regex=True)
        .str.strip()
    )
    return lon[["entity", "borough", "name", "statistical-geography", "local-authority-type"]]


def main() -> None:
    lon = load_london_authorities()
    print(f"London authorities in lookup: {len(lon)}  (expected 33)")
    missing_types = lon["local-authority-type"].value_counts().to_dict()
    print(f"  by type: {missing_types}")

    bf = pd.read_csv(RAW / "brownfield-land.csv", dtype=str, low_memory=False)
    print(f"National register rows: {len(bf):,}")

    for col in ("hectares", "maximum-net-dwellings", "minimum-net-dwellings"):
        bf[col] = pd.to_numeric(bf[col], errors="coerce")

    merged = bf.merge(
        lon, left_on="organisation-entity", right_on="entity",
        how="inner", suffixes=("", "_la"),
    )
    print(f"London rows (all, incl. archived): {len(merged):,}")

    live = merged[merged["end-date"].isna() | (merged["end-date"].astype(str).str.strip() == "")]
    print(f"London rows (live, end-date empty): {len(live):,}")

    agg = (
        live.groupby("borough")
        .agg(
            sites=("entity", "count"),
            hectares=("hectares", "sum"),
            dwellings_max=("maximum-net-dwellings", "sum"),
            dwellings_min=("minimum-net-dwellings", "sum"),
        )
        .reset_index()
    )

    # Boroughs with zero rows never appear in a groupby — reintroduce them,
    # because a silent gap is exactly what the gate exists to catch.
    table = (
        lon[["borough"]]
        .drop_duplicates()
        .merge(agg, on="borough", how="left")
        .fillna({"sites": 0, "hectares": 0, "dwellings_max": 0, "dwellings_min": 0})
    )
    table["sites"] = table["sites"].astype(int)
    table = table.sort_values("sites", ascending=False).reset_index(drop=True)

    PROC.mkdir(parents=True, exist_ok=True)
    table.to_csv(PROC / "step0_coverage.csv", index=False)

    print("\n=== STEP 0: SITES PER LONDON BOROUGH (live sites) ===")
    print(f"{'Borough':<28}{'Sites':>7}{'Hectares':>11}{'Dwell.min':>11}{'Dwell.max':>11}")
    print("-" * 68)
    for _, r in table.iterrows():
        print(f"{r['borough']:<28}{r['sites']:>7}{r['hectares']:>11.1f}"
              f"{r['dwellings_min']:>11,.0f}{r['dwellings_max']:>11,.0f}")
    print("-" * 68)
    print(f"{'TOTAL':<28}{table['sites'].sum():>7}{table['hectares'].sum():>11.1f}"
          f"{table['dwellings_min'].sum():>11,.0f}{table['dwellings_max'].sum():>11,.0f}")

    zero = table[table["sites"] == 0]["borough"].tolist()
    thin = table[(table["sites"] > 0) & (table["sites"] < 10)]["borough"].tolist()
    print("\n=== COVERAGE VERDICT ===")
    print(f"Boroughs with data:      {(table['sites'] > 0).sum()} / {len(table)}")
    print(f"Zero rows ({len(zero)}): {', '.join(zero) if zero else 'none'}")
    print(f"Below 10 sites ({len(thin)}): {', '.join(thin) if thin else 'none'}")


if __name__ == "__main__":
    main()
