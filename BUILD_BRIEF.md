# BUILD BRIEF — London Land Ledger

**Hackathon:** House London #0, Newspeak House, 1 August 2026 · Brief DB
**Deliverable window:** code freeze 17:00, demo 17:30, **3 minutes on stage**
**Audience:** policy campaigners and local councillors — not economists

---

## 1. What we are building

A borough-level scorecard, backed by a map, answering one question:

> **How much land has each London borough itself identified as suitable for housing, how many homes could go on it, how much of it already has permission — and how does that compare to the borough's ten-year housing target?**

The headline we are trying to earn:

> *"Borough X's own brownfield register lists N hectares with capacity for M homes — Y% of its ten-year target — and Z% of it has no permission."*

These are the council's own published numbers. That is the entire point. We are not estimating anything they haven't already told us.

**Primary deliverable:** a ranked borough table (CSV + on-screen).
**Secondary deliverable:** an interactive map of sites, filterable by permission status.

Build them in that order. The table is the finding; the map is the packaging. If the map isn't working by 16:00, cut it and ship the table.

---

## 2. Hard rules

1. **Download everything to `data/raw/` on first run and cache it.** Venue wifi is shared with ~160 people. Nothing may re-fetch on a later run. If a file exists on disk, use it.
2. **No secrets, no accounts, no logins.** Every source below is open, no auth. If something needs an account, we're not using it today.
3. **`wheretobuild_msoa_stats.csv` is under a data use agreement — event-only.** Add it to `.gitignore` immediately. Do not commit it, do not publish derived record-level output from it, do not push it to a public repo. Aggregated borough-level figures derived from it should not be posted publicly without asking the organisers.
4. **Every number on screen must be traceable to a source column.** No modelled estimates, no interpolation, no "roughly". If we can't source it, we don't show it.
5. Commit working increments. Do not refactor after 16:00.

---

## 3. Step 0 — Viability gate (do this before anything else)

Download the brownfield register, filter to the 33 London boroughs, and **count sites per borough**.

```
https://files.planning.data.gov.uk/dataset/brownfield-land.csv
```

Print a 33-row table: borough, site count, total hectares, total max-net-dwellings.

**Stop and report before continuing.** If a large share of London boroughs have zero or near-zero rows, the analysis needs rescoping and a human decides how. Do not silently proceed with partial coverage.

Expected: coverage is known to be uneven. That's fine — we report it. Silent gaps are what kills us.

---

## 4. Data sources

### 4.1 Brownfield land register — the spine

`https://files.planning.data.gov.uk/dataset/brownfield-land.csv`

Open Government Licence, no auth. Also available as GeoJSON and Parquet from `https://www.planning.data.gov.uk/dataset/brownfield-land`.

Confirmed columns:

```
dataset, end-date, entity, entry-date, geojson, geometry, name,
organisation-entity, point, prefix, quality, reference, start-date,
typology, brownfield-land, deliverable, hazardous-substances, hectares,
maximum-net-dwellings, minimum-net-dwellings, notes, organisation,
ownership-status, planning-permission-date, planning-permission-history,
planning-permission-status, planning-permission-type, site, site-address,
site-categories, site-plan-url
```

The fields we care about:

| Field | Meaning | Use |
|---|---|---|
| `hectares` | Site area | The land measure |
| `minimum-net-dwellings` / `maximum-net-dwellings` | Council's own capacity estimate | Homes measure. **Use minimum as the headline, maximum as the upper bound. Show both.** |
| `planning-permission-status` | `permissioned` / `not-permissioned` / `pending-decision` | The core segmentation |
| `planning-permission-type` | e.g. `full-planning-permission`, `outline-planning-permission` | Secondary detail |
| `planning-permission-date` | When granted | Age of permission — see §5.3 |
| `deliverable` | `yes` = residential development expected within 5 years | Filter for the credible subset |
| `ownership-status` | Includes `owned-by-a-public-authority` | Strong secondary story |
| `point` | `POINT(lon lat)` WKT | Map + spatial joins |
| `end-date` | Populated when the site is archived | **Critical, see below** |
| `organisation-entity` | Numeric LPA id | Borough join key |
| `site-address`, `site-plan-url`, `planning-permission-history` | Human detail | Map popups |

**The `end-date` rule.** Sites are archived (given an `end-date`) when they're completed or no longer suitable. So:

- `end-date` empty + `planning-permission-status = permissioned` → **permitted and not completed.** This is our proxy for "permission granted, homes not delivered."
- `end-date` empty + `not-permissioned` → **identified but not permitted.** Often the more interesting number.
- `end-date` populated → exclude from live totals.

Filter to live sites (`end-date` empty) for all headline figures. State this in the README.

**Borough join:** `organisation-entity` is a numeric id, not a name. Get the lookup from the organisation dataset on planning.data.gov.uk (check the dataset page for the exact download URL — do not guess it). If the lookup is awkward, fall back to a spatial join of `point` against borough boundaries. Either is fine; pick whichever works in ten minutes.

### 4.2 Borough boundaries

Local planning authority boundaries as GeoJSON from `https://www.planning.data.gov.uk/dataset/local-planning-authority`, or ONS Open Geography Portal borough boundaries. **Simplify the geometry aggressively** before rendering — full-resolution Thames and coastline will make the map crawl and adds nothing at this zoom.

### 4.3 Ten-year housing targets

London Plan borough housing targets. 33 rows. **Type them into a hardcoded lookup file — `data/reference/borough_targets.csv` — do not spend time hunting for a machine-readable version.** Include a `source` column with the London Plan table reference.

Optional cross-check: MHCLG Housing Delivery Test gives a percentage-delivered-against-requirement per borough, with statutory thresholds at 95% / 85% / 75%. Latest measurement is 2023 (published Dec 2024), so it lags — label it clearly if used.

### 4.4 Demand overlay — optional, DUA-restricted

`Data Warehouse/wheretobuild_msoa_stats.csv` from the hackathon Drive.

Columns: `msoa_code, area_km2, gap, tightness, gap_per_km2`

Join path: site `point` → MSOA (ONS lookup) → `gap_per_km2`. Then aggregate to borough.

This produces the quadrant chart in §6.3. **Only attempt after §5 and §6.1 are complete and committed.**

### 4.5 Optional upgrade — site polygons

The GLA publishes a London brownfield register with **polygon** boundaries on the London Datastore (`data.london.gov.uk/dataset/brownfield-register-2og9g`). If the national register's points look thin on the map, polygons make it far more convincing. Treat as a stretch item, not a dependency. Note their caveat: sites below 0.25ha may not appear, and boundaries are indicative.

---

## 5. Pipeline

Write as discrete, re-runnable scripts. Each writes to `data/processed/` and prints a summary. No notebook-only logic — we need to re-run things at 16:30 under pressure.

### 5.1 `ingest.py`
Download to `data/raw/` if absent. Parse `point` WKT to lat/lon. Cast numerics, coercing bad values to null and **logging how many failed per column**.

### 5.2 `filter_london.py`
Restrict to the 33 London boroughs + City of London. Restrict to live sites (`end-date` empty). Emit a rejected-rows report with reasons.

### 5.3 `aggregate.py`

Per borough, produce:

- `sites_total`, `hectares_total`
- `dwellings_min_total`, `dwellings_max_total`
- Same three, split by `planning-permission-status` (permissioned / not-permissioned / pending-decision)
- Same three, restricted to `deliverable = yes`
- `pct_of_target_min` = `dwellings_min_total` ÷ ten-year target
- `pct_of_target_unpermissioned` = unpermissioned min dwellings ÷ target
- `pct_public_owned` — share of hectares in public ownership
- `median_permission_age_years` — from `planning-permission-date` where permissioned. **Old permissions on unbuilt sites are a genuine finding; surface it.**
- `data_quality_flag` — set where site count is below threshold or key fields are largely null

Write `data/processed/borough_scorecard.csv`.

### 5.4 Suppression rules
- Flag boroughs below a minimum site count (start at 10) rather than dropping them silently. Grey them on the map, footnote them in the table.
- **City of London** will be an outlier on every per-capita or per-target measure. Keep it in the table, exclude it from map colour scales, say why.

---

## 6. Output

### 6.1 The scorecard table — build first

Sortable, 33 rows. Default sort: unpermissioned capacity as a share of ten-year target, descending.

Columns: Borough · Sites · Hectares · Homes (min–max) · % permissioned · % of 10-yr target · Median permission age · Flag

Export button to CSV. This table alone is a valid submission.

### 6.2 The map — build second

Leaflet or MapLibre. Site points (or polygons if §4.5 lands), coloured by permission status, sized by dwelling capacity. Borough boundaries overlaid, click to filter the table.

Popup per site: address, hectares, min–max dwellings, permission status and date, links to `site-plan-url` and `planning-permission-history`.

Filters: permission status, `deliverable` yes/no, ownership status, minimum size.

**Keep it simple.** Clustering, heatmaps, and animated transitions are not worth the risk. A clean point map with working filters beats a clever one that stutters during the demo.

### 6.3 The quadrant chart — only if time

Scatter: x = demand pressure (`gap_per_km2`, borough mean), y = unpermissioned capacity as share of target. One dot per borough, labelled. The top-right quadrant is the argument: high demand, identified land, no permission.

This is the single most legible artefact if it lands. It is also the most DUA-restricted. Do not publish it without asking the organisers.

---

## 7. Stack

Python for the pipeline: pandas, geopandas, shapely, requests. Vite + React + Leaflet for the front end, or a single static HTML file if that's faster — no one is grading the architecture.

Static build, no server, no database. The whole thing must run from a local file with wifi off.

---

## 8. Honesty requirements

These must appear in the README **and** on a slide. Encode them, don't bolt them on at 16:55.

1. **This is not "all available land in London."** It is land each borough has itself assessed as suitable for housing and published on its brownfield register. Greenfield, green belt, and unassessed land are absent.
2. **Inclusion threshold:** sites must be ≥0.25ha or capable of ≥5 dwellings. Small infill is invisible.
3. **Registers update annually** and LPA coverage is incomplete. Report our measured coverage per borough — don't hand-wave it.
4. **Capacity figures are the council's own estimates**, not independent assessments.
5. **Register inclusion does not mean permission would be granted.**
6. `end-date` archiving is our completion proxy and depends on LPA diligence. It is a proxy, and we call it one.

---

## 9. Definition of done

**Minimum (must ship):** borough scorecard CSV with hectares, min–max dwellings, permission split, and share of ten-year target. Coverage report. README with §8.

**Target:** the above plus interactive map with working filters, and the ranked table on screen.

**Stretch:** quadrant chart against WhereToBuild demand; polygon boundaries; public-ownership and permission-age breakdowns.

---

## 10. Do not

- Do not build a backend, auth, or a database.
- Do not scrape planit.org.uk — it's rate-limited to roughly one request per minute and run by one volunteer. Everything we need is in bulk downloads.
- Do not estimate dwelling capacity where the register leaves it blank. Leave it null and count the nulls.
- Do not commit `wheretobuild_msoa_stats.csv` or anything derived from it at record level.
- Do not refactor for elegance after 16:00.
- Do not add a feature that needs explaining. Three minutes.
