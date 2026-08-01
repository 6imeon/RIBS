# UI Changes Spec — WhereToBuild Politician Tool

## Context

This tool helps a local politician focused on housing/development:
1. Spot the highest-priority areas for new housing
2. See how their borough compares to other London boroughs
3. (Future scope, not this pass) Identify stalled/"problem-child" projects and brownfield opportunities — this needs data we don't have loaded yet (GLA pipeline data, brownfield register), so skip building UI for it this round

Data files available in the project folder:
- `wheretobuild_msoa_regions.csv` — 8,598 MSOAs across England/Scotland/Wales, with columns: msoa_code, area_km2, gap, tightness, gap_per_km2, lad_code, lad_name, region
- `london_borough_summary.csv` — 33 London boroughs aggregated, with columns: lad_name, median gap, median tightness, median gap_per_km2, MSOA count, % surplus MSOAs

Key numbers already calculated (use these, don't recalculate):
- London median gap_per_km2 = **387**
- London mean gap_per_km2 = 613 (do NOT use this for the headline insight — it's skewed by one extreme outlier, City of London, and will overstate typical pressure)

---

## Feature 1: Headline insight sentence

When a user selects a place (borough or MSOA) on the map or in a card/pane, show one of these two sentences depending on the active mode (see Feature 2):

- **Scale mode:** "[Place] has a housing shortfall about [X]x bigger than a typical London area of the same size."
  - X = that place's `gap_per_km2` ÷ 387 (London median), rounded to 1 decimal place
- **Scarcity mode:** "In [Place], available homes are stretched about [X]x tighter than a typical London area."
  - X = that place's `tightness` ÷ London median tightness (calculate this median from wheretobuild_msoa_regions.csv, London rows only)

Display location: left-side pane or the expanding card (whichever is architecturally simpler given the current UI — dev's call).

Rounding/edge case: if a place's gap is negative (surplus), do not use the "shortfall" language above — instead show: "[Place] currently has more supply than demand relative to a typical London area" (no multiplier, since a shortfall multiplier doesn't make sense for a surplus).

## Feature 2: Scale / Scarcity toggle

Add a two-state toggle, default to Scale mode.

- **Scale mode** — map colouring and rankings driven by `gap_per_km2`. This is the default and primary lens, since it directly answers "where is the biggest priority problem."
- **Scarcity mode** — map colouring and rankings driven by `tightness`. Secondary lens, "how squeezed does this market feel."

Switching the toggle should update: the map's colour scale, any sorted list/leaderboard, and the headline insight sentence (Feature 1) simultaneously.

## Feature 3: Borough comparison / leaderboard

New view or panel: a ranked list of London's 33 boroughs using `london_borough_summary.csv`, sorted by median gap_per_km2 (Scale mode) or median tightness (Scarcity mode), matching whichever toggle state is active.

Exclusion: **exclude City of London from this specific ranked list.** It's a single-MSOA outlier, not a meaningful "borough" for comparison purposes (Claude Code flagged it as a data oddity, not a real policy-comparable area). It's fine to leave it visible on the underlying map/data, just filter it out of the borough leaderboard specifically. Add a one-line footnote wherever the leaderboard appears: "City of London excluded — single-MSOA area not comparable to other boroughs."

Surplus highlight: London is almost uniformly under pressure — only Havering (1 of 30 MSOAs) and Hillingdon (2 of 32 MSOAs) have any surplus areas at all, every other borough is 0% surplus. Surface this as a callout or stat somewhere near the leaderboard, e.g. "31 of 33 London boroughs have zero areas of housing surplus" — it's a strong, simple headline stat for the presentation and worth having live in the product too.

## Feature 4: Visual distinction for surplus areas

On the main map, MSOAs with negative `gap` (322 of them, supply exceeds demand) should be visually distinct from shortage areas — a different colour (e.g. a cool colour like blue/teal) rather than just the palest shade of the shortage gradient. A politician glancing at the map should be able to tell "this area is fine" apart from "this area has mild pressure" at a glance.

---

## Out of scope for this pass

- "Problem-child" stalled projects and brownfield opportunities — needs additional datasets not yet loaded (GLA pipeline/completions data, brownfield land register). Flag as a "coming next" note in the product if there's a natural place for it, but don't build functionality for it now.
- "Similarly pressured peer group" comparison — the current leaderboard (Feature 3) shows a full ranking, which is sufficient; grouping boroughs into pressure-similarity clusters is a nice-to-have, not required this round.
