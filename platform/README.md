# Levista Marketing Performance Intelligence Platform

Ingests the raw ad exports from Amazon, Flipkart (National + Minutes), Instamart,
Zepto (PLA + PCA), BigBasket and Blinkit; stores everything in Postgres; and
generates the executive Excel workbook and PowerPoint deck that were previously
assembled by hand each month.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # then put your own Postgres credentials in .env
python run_all.py
```

Outputs land in `OUTPUT_DIR` (default `D:\levista\output`):

- `Levista_Performance_Report.xlsx` — 25 sheets
- `Levista_Performance_Report.pptx` — 21 slides

Run the pieces separately if you prefer:

```bash
python -m etl.run              # ingest + load one month
python -m analytics.insights   # insights, recommendations, alerts, anomalies
python -m reports.excel
python -m reports.ppt
python -m tests.test_pipeline  # 66 checks against the real input files
```

Run commands from inside the `platform` folder. (The folder is deliberately not a
Python package — a `platform/__init__.py` would shadow the standard library's
`platform` module.)

## Database

### Switching to Postgres

Three instances are running on this machine. Ports confirmed from each
`postgresql.conf`:

| Service | Port |
|---|---|
| `postgresql-x64-17` | **5432** (recommended) |
| `postgresql-x64-16` | 5433 |
| `postgresql-x64-13` | 5434 |

All three use `scram-sha-256`, so a password is required.

```bash
cp .env.example .env
```

Put your own password in the `DATABASE_URL` line of `.env`, then:

```bash
python setup_postgres.py
```

That creates the `levista` database if it does not exist, applies the schema and
all 14 views, and reports what it built. `python setup_postgres.py --check` tests
the connection without changing anything. Then run the pipeline as normal:

```bash
python run_all.py
```

There is no data migration to do — the pipeline rebuilds from the source exports
on every run, so pointing it at Postgres and re-running is the whole switch. The
old `levista.db` can be deleted once you are happy.

`.env` is gitignored. The setup script masks the password in everything it prints.

### Fallback

With no `DATABASE_URL` set, the pipeline uses a local SQLite file so it runs
before credentials exist. SQLAlchemy makes the two interchangeable; the run prints
a notice whenever the fallback is in use.

Two places genuinely differ between the engines, both handled in `db/models.py`:

- `raw_records.payload` is **JSONB** on Postgres and plain JSON on SQLite, so the
  raw payload stays queryable.
- `DROP VIEW` gets a **CASCADE** on Postgres. `campaign_summary` is built on
  `campaigns`, and Postgres refuses to drop a view another view depends on;
  SQLite tracks no dependencies and rejects the keyword outright.

Tables: `platforms`, `uploaded_files`, `raw_records`, `performance_metrics`,
`insights`, `recommendations`, `alerts`, `anomalies`, `audit_log`.

`campaigns`, `keywords`, `products`, `cities`, `sales`, `orders`, the four
`*_summary` tables and `daily/weekly/monthly_metrics` are **views** over
`performance_metrics` (`db/views.sql`). They are all `GROUP BY` on the same facts,
so a number can only ever have one definition. Every source row is also kept
verbatim in `raw_records.payload`, so nothing from the original files is lost.

## Loading months and comparing them

Each run loads **one month** and replaces only that month. Previously loaded months
stay put, so re-running a month is still idempotent while history accumulates.

```bash
python -m etl.run                    # detects the month from the files
python -m etl.run --period 2026-09   # label the batch explicitly
python -m etl.run --replace-all      # wipe every period first (rarely wanted)
```

**Why the month is a property of the run, not the file:** Amazon, Zepto and Blinkit
exports state no reporting period anywhere — 28 of the 58 files in the August feed.
Only BigBasket, Instamart and Flipkart do. If the label came from file contents,
September's Zepto export would be indistinguishable from August's and would silently
overwrite it. So the label is derived from the most common period across the files
that *do* state one, and applied to the whole batch. When no file states a period,
the run stops and asks for `--period` rather than guessing.

Everything downstream defaults to the newest month: the dashboard, the workbook and
the deck. Once a second month exists, the platform tables gain **Revenue Growth**,
**Spend Growth** and **ROAS Change** columns, and the dashboard sidebar gains a month
selector. With one month loaded those columns are absent rather than showing 0%.

On the dashboard's Data & Uploads page, the "Month to load as" field does the same
job as `--period`. Leave it blank to auto-detect; set it when uploading exports that
carry no dates of their own.

```sql
-- what is loaded
SELECT period_label, COUNT(*) FROM performance_metrics GROUP BY 1 ORDER BY 1;
```

### Importing a hand-built report workbook

Months from before the pipeline existed can be back-loaded from the report workbook
the team assembled by hand:

```bash
python -m etl.report_import "..\Levista Overall Campaign Report July Report.xlsx" --period 2026-07
```

`etl/report_import.py` is deliberately separate from the signature registry. That
registry reads raw platform exports — one table per file. The workbook is the
*output* artifact: category blocks stacked down the page, two blocks side by side on
some sheets, headers repeated per block, campaign names filled only on the first row
of each group, and blank rows between groups. The importer splits on empty columns,
scans for banner/header rows, and forward-fills campaign names.

Only base measures are taken; CTR/CPC/CPM/ROAS are recomputed from them exactly as
for raw exports, so an imported month stays comparable. July reconciles to the rupee
with the workbook's own Overall Campaign Report sheet (₹24,31,502 spend,
₹76,70,890 revenue) — that sheet is treated as the authority for platform totals.

### Comparing months of different lengths

**This matters more than anything else in the comparison logic.** July covers 31 days;
the August feed covers 1–10 August only. On raw totals August revenue is **−44.5%**
against July. Per day it is **+72.1%** — the opposite conclusion from the same data.

So when two periods differ in length by more than 5%, growth is computed **per day**
and labelled as such: the Excel column reads "Revenue Growth per day vs 2026-07", the
dashboard says so in the header and on each KPI, and a Medium alert states the day
counts. ROAS is a ratio and needs no adjustment, so it is compared directly.

Load a full month against a full month and the basis reverts to plain totals.

## The location map

`components/LocationMap.tsx` draws a real geographic map: India's 34 state outlines
with one bubble per city, sized by revenue (or spend/orders) and coloured by return
on the same green/amber/red bands used everywhere else.

Both data files are generated, small, and committed — the map needs no network and
no mapping library:

- `lib/city-coords.json` (4 KB) — real coordinates for 109 of the 110 cities in the
  data, matched against an open cities dataset. Not guessed. The one unmatched entry
  is "Central Goa", a district rather than a point; the map names it rather than
  dropping it silently.
- `lib/india-states.json` (60 KB) — state boundaries reduced from 13 MB with
  Douglas-Peucker at ~4 km tolerance.

Projection is equirectangular with a standard parallel at 23°N; without that cosine
term India comes out visibly stretched east-to-west. Bubble **area** tracks the
value, not radius, so a city with twice the revenue gets twice the ink.

### City names are canonicalised first

`etl/cities.py` maps renamed and alternate spellings to one official name. Without
it the same place is counted several times over: Zepto writes "chennai" and
"Bengaluru" where Instamart writes "Chennai" and "Bangalore", and both Bangalore and
Bengaluru appeared in the top five as separate cities. Canonicalising took 117
"cities" down to 110 real ones.

## How detection works

Folder names in the source exports are unreliable and cannot be trusted:

| File | Folder says | Actually is |
|---|---|---|
| `Zepto\PLA\keywords performance\Instant Coffee\report_139244357.xlsx` | Zepto keyword | Zepto **product** |
| `Zepto\PCA\Keywords Report\instant coffee\report_717410614 (1).xlsx` | Zepto keyword | Zepto **city** |
| `Flipkart\Filpkart National\Campaign Report\zr8scxkwk8k.csv` | Flipkart campaign | Flipkart **keyword** |
| `BigBasket\product performance\report_102877594.xlsx` | BigBasket product | **Zepto** city |

So platform and report type come from the **column signature** (`etl/signatures.py`),
never the path. The path contributes only the coffee-category hint
(Instant / Filter / Cold), which genuinely is not inside the files.

The pipeline also:

- **de-duplicates by SHA-256** — the August feed contains 10 byte-identical copies
  of other files under different folders; counting them would inflate every metric;
- **sniffs the header row** — Flipkart CSVs carry 2–4 preamble lines, Instamart 6,
  BigBasket product exports put the campaign name above the header, Blinkit ships
  one workbook with five differently-shaped sheets;
- **flags rather than fails** — an unrecognised export is recorded as
  `needs_review` in `uploaded_files` and named in the run summary. The rest of the
  run completes.

### Supporting a new export

Add one `Signature` to `etl/signatures.py`. Nothing else changes.

## How the numbers are made comparable

- Currency strings (`₹ 3,09,832.39`, Indian lakh grouping) parse to floats.
- Percentages are converted using the **unit declared per signature**, never guessed
  from the value. CTR is a fraction on Amazon (`0.0062`) and a percentage on
  Flipkart (`12.6603`), BigBasket (`4.35`) and Zepto (`1.01`).
- `NA`, `-` and blanks become NULL, not 0 — a missing CPC is not a zero CPC.
- CTR, CPC, CPM, ROAS and conversion rate are **recomputed** from impressions,
  clicks, spend, orders and revenue. The platform's own figure is kept alongside as
  `*_reported` for audit. (This is what caught Zepto reporting CTR as a percentage.)

### Counting each rupee once

Every platform ships the same money at several grains (campaign, product, keyword,
city), so summing all rows would multiply the spend. For each
(platform, sub-platform) the pipeline marks one report type as `is_primary`, taking
the first available from that platform's priority list, and all totals filter on it.

Blinkit is the cross-check: its four ad formats sum to ₹4,01,596, which reconciles
exactly with its own MTD Claimables sheet.

Flipkart National has no campaign-level export this month, so its product report is
used; if one appears next month it is picked up automatically with no code change.

## Known data limitations

These are properties of the source feed, not of the code:

- **Only Blinkit exports a daily grain** (`date_ist`). Every other platform exports a
  pre-aggregated period, so `daily_metrics` is sparse and week/month roll-ups use the
  reporting period. Day-level trending across platforms needs daily exports.
- **Blinkit's keyword, category and product sheets report impressions but no clicks**,
  covering only ~25% of its spend. Platform-level CTR, CPC and conversion rate are
  therefore suppressed for Blinkit rather than shown as a misleading number. BigBasket
  reports no clicks at all.
- **Growth % is empty** until a second month is loaded — see "Loading months and
  comparing them" above. It stays empty rather than showing a fake 0%.
- **Missing reports** (no Amazon or Instamart keyword export this month) produce a
  "No source data" banner on the relevant sheet plus a data-gap alert, rather than a
  silently blank sheet.
- **Native Excel PivotTables** cannot be produced by openpyxl. The pivot-style sheets
  are pre-aggregated, formatted, auto-filtered summary tables — the same thing the
  hand-built July workbook contained. A live pivot cache would need Excel COM automation.

## Layout

```
platform/
  config.py              settings + .env loader
  run_all.py             ETL -> insights -> Excel -> PPT
  etl/signatures.py      column-signature registry (add new exports here)
  etl/ingest.py          discover, dedupe, unzip, header sniffing
  etl/normalize.py       cleaning, unit conversion, derived metrics
  etl/load.py            persistence + audit + primary-grain marking
  etl/run.py             ETL entry point
  analytics/metrics.py   aggregations, comparisons, leaderboards
  analytics/insights.py  what happened / why / what next, rule-based
  reports/excel.py       25-sheet workbook
  reports/ppt.py         21-slide deck
  db/models.py           schema (portable Postgres/SQLite)
  db/views.sql           the analytics layer
  tests/test_pipeline.py 37 checks against the real files
```

## Dashboard

Two processes. Backend, from the `platform` folder:

```bash
uvicorn api.main:app --port 8000
```

Frontend, from `D:\levista\dashboard`:

```bash
npm run dev
```

Then open http://localhost:3000. The frontend reads `NEXT_PUBLIC_API` from
`.env.local` (defaults to `http://localhost:8000`).

**Pages** — Executive, Product Segments, Platforms, Campaigns, Products, Keywords,
Cities, Insights, and Data & Uploads.

A filter bar on every page sets platform, product category, city, keyword and
campaign at once, and the month comes from the sidebar picker. A dimension a table
does not carry is ignored by that table rather than emptying it — a city filter
cannot mean anything to the campaign table, because campaign rows carry no city.

Every table sorts on any column, searches, paginates, and exports **exactly what is
on screen** (filters included) to CSV or Excel. The full workbook and deck download
from the header buttons.

**Endpoints** — `/api/health`, `/api/period`, `/api/filters`, `/api/kpis`,
`/api/platforms`, `/api/campaigns`, `/api/products`, `/api/keywords`,
`/api/cities`, `/api/keywords/buckets`, `/api/periods`, `/api/trend`, `/api/funnel`,
`/api/segment`, `/api/highlights`, `/api/locations/coverage`, `/api/insights`,
`/api/recommendations`, `/api/alerts`, `/api/anomalies`, `/api/files`, `/api/upload`,
`/api/rebuild`, `/api/job`, `/api/export/table/{entity}`, `/api/export/{excel|ppt}`.

Every endpoint reads through `analytics/metrics.py` and `analytics/insights.py` —
the same code that builds the workbook and the deck — so a number cannot disagree
between the dashboard and the board pack.

Uploads reload **one whole month** rather than appending single files:
de-duplication and primary-grain selection are decided across a month's complete
file set, so appending one file in isolation could double-count it. Other months in
the database are untouched. The job runs in the background and the Data page polls
until it finishes.

### What the data cannot answer

These are properties of the exports, and the dashboard says so on screen rather
than drawing something that looks authoritative:

- **There is no date-range picker, because there are no dates.** Only Blinkit ships a
  daily grain (861 of 4,094 August rows). Everything else is a pre-aggregated period,
  so filtering to "12–18 August" would silently exclude 95% of the spend. The filter
  is by month instead.
- **Location covers 23% of spend.** Only Zepto and Instamart report a city at all;
  Amazon, Flipkart, BigBasket and Blinkit ship no location dimension. Every location
  view states that share, including the map.
- **The conversion funnel uses a consistent cohort.** Amazon reports no add-to-cart
  and BigBasket no clicks, so mixing all six platforms produced more purchases than
  baskets — a "117% conversion". The funnel is built only from platforms reporting
  every stage (43% of spend) and names them. Its last step can still exceed the one
  above it, because quick commerce attributes indirect orders with no ad-driven cart
  event; that is labelled where it happens.
- **"Total Sales" is the same number as revenue.** No export reports a sales value
  distinct from ad revenue, so the KPI says so rather than inventing a second figure.
- **Product segments exist for August only.** The July workbook records platform
  totals without splitting them by coffee type.

### Known limitations of the dashboard

- **Period comparison is inert until a second month is loaded.** `/api/periods`
  reports `comparable: false` and the UI says so rather than showing an empty
  growth column.
- **Job state is a single in-process dict**, which is correct for one uvicorn
  worker. Running multiple workers needs the state moved into the database.
- **No authentication.** It binds to localhost and assumes a trusted network. Put
  it behind your own auth before exposing it.
