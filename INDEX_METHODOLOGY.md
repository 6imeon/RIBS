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

## Scoring method — two outputs, deliberately kept separate

Each of the three components is percentile-ranked across the 24 rankable
boroughs. Combining them into a single gated score (must clear the 50th
percentile on all three, only then averaged) produced just 4–5 scored boroughs
and left the other ~20 rankable boroughs blank — unworkable for a full
choropleth. The fix is to give the map and the headline claim two different
numbers rather than forcing one number to do both jobs:

1. **`opportunity_index` (0–100, continuous)** — the mean of the three
   percentile ranks, computed for **all 24 rankable boroughs**, no gating.
   This drives the map fill, so the choropleth reads as a gradient rather than
   mostly grey.
2. **`all_three_high` (boolean)** — True only if the borough *also*
   independently clears the 50th percentile on every one of the three
   components. This is the stricter "genuinely strong on every axis at once"
   claim, rendered as a badge on top of the fill, never as the fill itself.

This keeps both things intact: a fully populated map, and a defensible narrower
claim about boroughs exceptional on every axis rather than merely averaging well.

**Why the separation matters.** Barking and Dagenham scores 69.4 — fifth of 24 —
on the strength of the highest absolute stalled homes in London (100th percentile)
and near-top capacity (96th). Its demand sits at the 12th percentile. The average
alone would present it as a top-five priority; the badge is what stops it from
reading that way.

## Mean vs median demand — the app departs from `score_index.py`

`score_index.py` ranks on `demand_gap_per_km2`, the **mean** of `gap_per_km2`
across a borough's MSOAs. The **Priority index** view in `app/index.html` ranks on
`demand_gap_per_km2_median` instead.

This is deliberate. London's `gap_per_km2` distribution is badly skewed — the
London-wide mean is 606 against a median of 383, a 58% overstatement — so the rest
of the app standardised on medians when the demand lens was built. Ranking the index
on the mean while every comparison sentence beside it used the median would let the
two disagree about the same borough on the same screen.

It changes who earns `all_three_high`: **Waltham Forest** sits at exactly the
0.500 demand percentile on medians and 0.458 on means, so it clears the badge
under one and not the other. It is the single case that flips, and it sits
precisely on the threshold — it would drop out under any stricter cut. The app
labels it as provisional rather than presenting it as settled.

The handoff doc's expected output ("4 clear all three") was computed on means.
On medians it is **5**, with Waltham Forest added. Everything else matches.

## Result (as of this data pull)

24/24 rankable boroughs receive a continuous `opportunity_index`; 5 clear
`all_three_high`:

| Borough | Index | All three |
|---|--:|:--:|
| Kensington and Chelsea | 86.1 | ✓ |
| Wandsworth | 84.7 | ✓ |
| Camden | 83.3 | ✓ |
| Lewisham | 75.0 | ✓ |
| Barking and Dagenham | 69.4 | |
| Greenwich | 66.7 | |
| Barnet | 63.9 | |
| Waltham Forest | 61.1 | ✓ |
| … remaining 16 rankable boroughs score 13.9–54.2 | | |

The 9 boroughs with `NO_CAPACITY_PUBLISHED` remain unscored (None) throughout —
insufficient data, never zero.

## Confidence flag

Boroughs carrying `PARTIAL_CAPACITY` or `LOW_SITE_COUNT` in `data_quality_flag`
should be visually marked (border or icon) even if they qualify, since their
underlying counts are less reliable (e.g. City of London, n=2 sites).
