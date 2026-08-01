# Build-opportunity index — methodology

## What this index answers

"Which boroughs have high stalled housing capacity, high demand pressure, and a
substantial absolute number of homes stuck in planning limbo — all three at once?"

This is deliberately stricter than "highest average score across some signals." A
borough only ranks if it is genuinely strong on every axis, not merely strong on
one and mediocre on the rest.

## The three components

1. **`pct_of_target_pns`** — stalled capacity as a % of the borough's ten-year
   London Plan target. Sites with full planning permission, not yet started,
   summed and divided by the target. Source: brownfield land register
   (planning.data.gov.uk) ÷ London Plan 2021 Table 4.1.
2. **`demand_gap_per_km2`** — WhereToBuild demand-pressure density (Rightmove-derived,
   Warwick CAGE). Fully independent dataset from the brownfield register.
3. **`homes_min_permitted_not_started`** — the raw count of homes sitting on
   permitted-not-started sites. Same underlying register as #1, but the absolute
   number rather than a ratio.

## Why these three and not others

- **`median_permission_age`** — dropped as a scored input. Correlates -0.25 with
  `pct_of_target_pns` (weakens to -0.14 once zero-capacity "ghost" permissions like
  Westminster/Redbridge are excluded, but the negative relationship is real, not
  just noise). Scoring it would pull the ranking against boroughs with the biggest
  stalled-capacity problem. Kept as a per-site annotation only (e.g. map click-through),
  never folded into the composite.
- **`pct_of_target_unpermissioned`** — dropped as a scored input. Correlates 0.60
  with `pct_of_target_pns` (meaningful overlap, not independent), has lower coverage
  (21/33 vs 24/33 boroughs), and measures a qualitatively different kind of
  opportunity (still needs planning approval, vs. already cleared). Kept as a
  separate "future pipeline" toggle layer in the app, not blended into this index.
- **`ten_year_target`** (raw or per-km²) — tried and rejected as the third axis.
  It is the same London Plan data already used as the denominator of
  `pct_of_target_pns`; using it again as an independent axis effectively
  double-counts the London Plan dataset while WhereToBuild (demand) only
  contributes once. It also behaves as a borough-size proxy (correlates -0.55
  with demand density), which structurally penalises small, dense boroughs
  (Kensington and Chelsea — the report's own headline case — drops out of the
  top tier entirely under this framing).
- **`homes_min_permitted_not_started`** was chosen instead specifically because
  it contains *no* target/London Plan information — it's a raw count from the
  brownfield register only. This keeps each of the three datasets contributing
  exactly once: London Plan (via the ratio in #1), brownfield register (via #1
  and #3, two different lenses on the same underlying sites — a ratio and a raw
  count, not a duplicate), and WhereToBuild (via #2).

## Coverage and exclusion

Only the 24 boroughs where `pct_of_target_pns` is non-null are scored. The 9
boroughs with `NO_CAPACITY_PUBLISHED` are shown on the map as insufficient data
(hatched/grey), never assigned a score of zero — consistent with how the
scorecard itself already treats missing capacity.

## Scoring method

Each of the three components is percentile-ranked across the 24 rankable
boroughs. A borough must clear the 50th percentile on **all three** to receive
a score; if it does, the score is the mean of its three percentile ranks
(0–100). This "threshold + average" method was chosen over a strict minimum
because a strict minimum caps a borough's score at its single weakest input,
discarding genuinely exceptional performance on the other two — which would
have demoted Kensington and Chelsea despite it topping two of the three axes
outright.

## Result (as of this data pull)

| Borough | Index |
|---|--:|
| Kensington and Chelsea | 86.1 |
| Camden | 83.3 |
| Wandsworth | 83.3 |
| Lewisham | 73.6 |

All other rankable boroughs fail to clear 50th percentile on at least one axis
and are unscored (shown as low/no score on the map, not excluded from the map
itself).

## Confidence flag

Boroughs carrying `PARTIAL_CAPACITY` or `LOW_SITE_COUNT` in `data_quality_flag`
should be visually marked (border or icon) even if they qualify, since their
underlying counts are less reliable (e.g. City of London, n=2 sites).
