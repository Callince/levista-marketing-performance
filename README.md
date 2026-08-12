# Levista Marketing Performance

Ingests raw ad exports from Amazon, Flipkart, Instamart, Zepto, BigBasket and
Blinkit, stores them in a database, and serves an executive dashboard plus an
Excel/PowerPoint report pack.

## Layout

- `platform/` — Python ETL + FastAPI backend (ingest → Postgres/SQLite → analytics → reports/API).
- `dashboard/` — Next.js dashboard that reads the API.

## Run it

Backend:

```bash
cd platform
pip install -r requirements.txt
cp .env.example .env            # set DATABASE_URL (SQLite works with no server)
python run_all.py               # ingest + build reports
uvicorn api.main:app --port 8000
```

Frontend:

```bash
cd dashboard
npm install
npm run dev                     # http://localhost:3000, reads NEXT_PUBLIC_API (default :8000)
```

## Notes

- `.env`, the raw report files, the database, and `overrides.json` (per-platform
  billed totals) are gitignored — supply your own.
- The `campaign` report is a platform's billed total; `product`/`keyword`/`city`/
  `placement` are partial breakdowns. When a campaign report is unavailable, set the
  authoritative total in `platform/overrides.json`.
