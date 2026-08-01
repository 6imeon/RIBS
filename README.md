# London Land Ledger

**Where should London actually build? Start with the land it has already said yes to.**

An interactive map and borough scorecard showing land that **already has planning
permission but has not been started**, in hectares and in the council's own dwelling
estimate, measured against each borough's ten-year London Plan target — and overlaid
on demand pressure.

## The finding

> **2,554 hectares of London brownfield land already has planning permission and has
> not been started. That is roughly 171,800 homes — 35% of the 33 boroughs' combined
> ten-year housing target (487,660) — sitting on land councils have already approved.**

Three boroughs have more unstarted permitted capacity than their **whole ten-year target**:

| Borough | Sites | Hectares | Homes (min) | 10-yr target | % of target | Median permission age |
|---|--:|--:|--:|--:|--:|--:|
| Kensington and Chelsea | 47 | 34.2 | 5,867 | 4,480 | **131%** | 9.5 yrs |
| Barking and Dagenham | 35 | 436.2 | 23,251 | 19,440 | **120%** | 6.0 yrs |
| Camden | 138 | 39.6 | 10,973 | 10,380 | **106%** | 8.5 yrs |
| Lewisham | 171 | 89.7 | 16,309 | 16,670 | 98% | 5.1 yrs |
| Wandsworth | 123 | 191.7 | 18,845 | 19,500 | 97% | 3.9 yrs |

Kensington and Chelsea is the sharpest case: it has the **highest demand pressure in
London**, enough permitted-but-unstarted capacity to cover 131% of its ten-year target,
and the median permission has been sitting there for **nine and a half years**.

The argument this supports: in these boroughs the binding constraint is not
identifying land, and not granting permission. Both have already happened.

## Run it

```bash
# 1. one-time setup
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python pandas requests

# 2. pipeline (downloads cache to data/raw/ on first run only)
.venv/bin/python scripts/download.py "https://files.planning.data.gov.uk/dataset/brownfield-land.csv" brownfield-land.csv
.venv/bin/python scripts/download.py "https://files.planning.data.gov.uk/dataset/local-authority.csv" local-authority.csv
.venv/bin/python scripts/download.py "https://files.planning.data.gov.uk/dataset/local-planning-authority.csv" local-planning-authority.csv
.venv/bin/python scripts/build.py          # clean + filter -> london_sites.csv
.venv/bin/python scripts/aggregate.py      # -> borough_scorecard.csv
.venv/bin/python scripts/make_map_data.py  # -> app/data/*.json

# 3. serve (fetch() needs http, not file://)
cd app && python3 -m http.server 8000
```

Then open <http://localhost:8000>. Leaflet is vendored in `app/vendor/`, so the app
works offline apart from basemap tiles. Data layers render with wifi off.

## What's here

| Path | |
|---|---|
| `app/index.html` | The whole front end. Two views: **The finding** (headline, quadrant chart, ranked ledger) and **Explore the map**. No build step |
| `data/processed/borough_scorecard.csv` | **The deliverable.** 33 boroughs, all metrics |
| `data/processed/london_sites.csv` | 5,185 cleaned live London sites |
| `data/processed/status_normalisation_audit.csv` | Every permission-status remap, auditable |
| `data/processed/rejected_rows.csv` | 904 archived rows, with reason |
| `data/reference/borough_targets.csv` | London Plan 2021 Table 4.1, hand-entered |

## Method

**Spine:** national brownfield land register (`planning.data.gov.uk`, Open Government
Licence), 37,485 rows → 6,089 London rows → **5,185 live sites**.

**Borough join:** the register's `organisation-entity` is a numeric id resolving to the
`local-authority` dataset (verified: entity 336 = Teignbridge DC). Joined to the 33
London authorities by ONS `E09*` statistical-geography code, not by name — 33/33 matched.

**"Permitted, not started":** `end-date` empty **and** permission status normalises to
`permissioned`, **excluding** sites the register marks `Started`. `end-date` is populated
when a site is completed or drops off the register, so an empty `end-date` on a
permissioned site means permission exists and the homes are not built.

**Demand:** WhereToBuild MSOA extract → MSOA21 → borough (982/982 London MSOAs matched,
100% coverage). Borough figure is the mean of `gap_per_km2` across its MSOAs.

### Permission status had to be cleaned

The register is specified to hold three values. London rows contain **twelve**, including
free text and typos. Every remap is printed at run time and written to
`status_normalisation_audit.csv`:

| Raw | → | n |
|---|---|--:|
| `permissioned` / `not-permissioned` / `pending-decision` | unchanged | 4,586 |
| *(blank)* | `unknown` | 399 |
| `Submitted`, `application pending` | `pending-decision` | 80 |
| `Site allocation`, `allocation` | `not-permissioned` | 68 |
| `Started`, `full permission`, `full permissioned`, `pemrissioned` | `permissioned` | 52 |

A local-plan *allocation* is not a permission, so those became `not-permissioned`.
Blanks became `unknown` rather than being assumed either way.

## Honesty requirements

Read these before quoting any number.

1. **This is not "all available land in London."** It is land each borough has itself
   assessed as suitable for housing and published on its brownfield register.
   Greenfield, green belt, and unassessed land are absent.
2. **Inclusion threshold:** sites must be ≥0.25 ha or capable of ≥5 dwellings. Small
   infill is invisible.
3. **Registers update annually and coverage is uneven.** We measure it rather than
   hand-wave it — see the coverage caveat below.
4. **Capacity figures are the councils' own estimates**, not independent assessments.
5. **Register inclusion does not mean permission would be granted** — though for the
   headline segment here, permission already *has* been granted.
6. **`end-date` archiving is our completion proxy** and depends on LPA diligence. It is
   a proxy and we call it one. The register's own `Started` flag is only present on 49
   London sites, so "not started" is better read as "not recorded as started".

### The coverage caveat that matters most

**9 of 33 boroughs publish no dwelling capacity for their permitted-but-unstarted
sites** — Bromley, Ealing, Enfield, Harrow, Havering, Hillingdon, Kingston upon Thames,
Sutton, Tower Hamlets. Between them they have 782 live sites and 387 hectares.

This is tested per segment, not just per borough: Sutton publishes capacity on some
sites but none of its permitted-unstarted ones, so it is `n/p` here. Westminster and
Redbridge are the opposite case — their sites do state capacity and it is genuinely
zero, which is a finding rather than a gap. 24 boroughs can be ranked.

They are shown as **`n/p`** (not published), **never as zero**, and are excluded from
every percentage-of-target ranking. A zero there would be missing data masquerading
as a finding. 34% of all live London sites have no dwelling figure.

Other flags carried in `data_quality_flag`: `LOW_SITE_COUNT` (below 10 sites — City of
London only, at 2), `PARTIAL_CAPACITY` (under 60% of sites report capacity).

Additional limits:
- **276 of 5,185 sites (5.3%) have no usable coordinates.** They are counted in every
  table total but cannot appear on the map, so map counts run slightly below table counts.
- **Two Development Corporations are excluded.** London Plan Table 4.1 lists 35 rows,
  including LLDC (21,540) and OPDC (13,670). Their targets sit geographically inside
  boroughs, so including them would double-count. Only the 33 boroughs are scored.
- **The Housing Delivery Test is not used here.** The latest measurement lags by ~2 years.
- Two sites report `minimum > maximum` dwellings; flagged, values left untouched.

## Data sources

- **Brownfield land register** — [planning.data.gov.uk](https://www.planning.data.gov.uk/dataset/brownfield-land), Open Government Licence v3.0
- **Local authority / LPA boundaries** — planning.data.gov.uk, OGL v3.0
- **MSOA→LAD lookup** — ONS Open Geography Portal, OGL v3.0
- **Ten-year housing targets** — [London Plan 2021, Table 4.1](https://www.london.gov.uk/programmes-strategies/planning/london-plan/the-london-plan-2021-online/chapter-4-housing) (net housing completions 2019/20–2028/29)

### WhereToBuild — restricted

> **Source: WhereToBuild project, CAGE, University of Warwick. Data provided by
> Dr Amrita Kulka and Dr Nikhil Datta.**

The demand layer is supplied under a data use agreement. Under its terms:

- **Event use only**; not to be redistributed, uploaded publicly, or shared outside the event.
- **These are research measures.** They must **not** be described as official estimates
  of housing need, housing requirements, or planning targets.
- **Public-facing outputs require approval** from Dr Kulka and Dr Datta before publication
  or wider circulation.
- The data is **deleted after the event**.
- No attempt is made to identify or speculate about any underlying data provider.

The raw extract lives in `data/restricted/` and is **gitignored**, as is every
MSOA-level derivative. Only borough-level aggregates reach `data/processed/`. The app
surfaces the attribution automatically whenever the demand layer is switched on, and
the layer is **off by default** — the tool works and demos without it.
