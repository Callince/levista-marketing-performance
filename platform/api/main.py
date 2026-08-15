"""FastAPI backend for the Levista dashboard.

    uvicorn api.main:app --reload --port 8000

Every endpoint reads through analytics.metrics / analytics.insights — the same
code that builds the Excel and PowerPoint — so a number can never disagree
between the dashboard and the deck.
"""
from __future__ import annotations

import io
import json
import shutil
import threading
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import (BackgroundTasks, FastAPI, Form, HTTPException, Query,
                     UploadFile)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select, text

import config
from analytics import insights as ai
from analytics import metrics
from db.models import (alerts, anomalies, get_engine, insights as insights_table,
                       recommendations, uploaded_files)

app = FastAPI(title="Levista Marketing Performance Intelligence", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"], allow_headers=["*"],
)

UPLOADS = config.INPUT_DIR / "_uploads"
ALLOWED_SUFFIXES = {".csv", ".xlsx", ".xls", ".zip"}

# ponytail: single-process job state. A queue only earns its keep with >1 worker.
JOB = {"status": "idle", "message": "", "finished_at": None}

# Two rebuilds at once corrupt each other: each wipes the period the other is
# writing, and the loser dies on a foreign key. One at a time.
REBUILD_LOCK = threading.Lock()


def engine():
    return get_engine()


def records(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> JSON-safe records. NaN/NaT become null, not the string 'NaN'."""
    if df is None or df.empty:
        return []
    return df.replace({np.nan: None, pd.NaT: None}).to_dict(orient="records")


def _filtered(fetch, entity: str, platform, category, search, sort, limit, period="latest",
              city=None, keyword=None, campaign=None, date=None):
    """Global filters are applied where the dimension exists on that table.

    A city filter cannot mean anything to the campaign table — campaign rows carry no
    city — so it is ignored there rather than silently returning nothing.
    """
    df = fetch(engine(), platform=platform, category=category, period=period, date=date)
    if df.empty:
        return []
    df = metrics.collapse(df, entity, ["platform"] if not platform else None)
    for value, column in ((city, "city"), (keyword, "keyword"), (campaign, "campaign_name")):
        if value and column in df.columns:
            df = df[df[column].astype(str).str.lower() == value.lower()]
    if search:
        needle = search.lower()
        text_cols = [c for c in ("campaign_name", "product_name", "keyword", "city",
                                 "product_id", "match_type") if c in df.columns]
        mask = pd.Series(False, index=df.index)
        for col in text_cols:
            mask |= df[col].astype(str).str.lower().str.contains(needle, na=False)
        df = df[mask]
    if sort and sort in df.columns:
        df = df.sort_values(sort, ascending=False, na_position="last")
    return records(df.head(limit))


# ---------------------------------------------------------------- meta

@app.get("/api/health")
def health():
    eng = engine()
    with eng.connect() as conn:
        rows = conn.execute(text("SELECT COUNT(*) FROM performance_metrics")).scalar()
    # Report the real dialect — the URL may set sqlite explicitly, not just as a fallback.
    db = eng.dialect.name + (" (fallback)" if config.USING_FALLBACK_DB else "")
    return {"status": "ok", "fact_rows": rows, "database": db, "job": JOB}


@app.get("/api/periods")
def periods_list():
    """Months loaded, plus which one is shown by default and what it compares to."""
    available = metrics.periods(engine())
    latest = available[-1] if available else None
    return {
        "periods": available,
        "latest": latest,
        "prior": metrics.prior_period(engine(), latest),
        "comparable": len(available) > 1,
    }


@app.get("/api/period")
def period(period: str | None = None):
    start, end = metrics.reporting_period(engine(), period)
    with engine().connect() as conn:
        periods = conn.execute(text(
            "SELECT DISTINCT period_start, period_end FROM performance_metrics "
            "WHERE period_start IS NOT NULL ORDER BY period_start")).all()
    return {
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "available": [{"start": str(s), "end": str(e)} for s, e in periods],
        # One period loaded means nothing to compare against yet — the UI says so
        # rather than showing an empty growth column.
        "comparable": len(periods) > 1,
    }


@app.get("/api/days")
def days(period: str | None = None):
    """The distinct report dates in a month — the options for the day filter."""
    scope = " WHERE period_start IS NOT NULL" + (" AND period_label = :period" if period else "")
    with engine().connect() as conn:
        rows = conn.execute(
            text(f"SELECT DISTINCT period_start FROM performance_metrics{scope} ORDER BY period_start"),
            ({"period": period} if period else {})).all()
    return {"days": [str(r[0]) for r in rows if r[0] is not None]}


@app.get("/api/filters")
def filters(platform: str | None = None, category: str | None = None,
            period: str | None = None):
    """Options for the filter bar.

    Campaigns are scoped to the platform/product/month already chosen, so picking
    "Zepto" leaves only Zepto's campaigns to choose from instead of every campaign
    across every platform. Platforms and products stay unscoped — narrowing them by
    each other would make a chosen value vanish from its own list.
    """
    where, params = ["COALESCE(campaign_name, campaign_id) IS NOT NULL"], {}
    if platform:
        where.append("platform = :platform")
        params["platform"] = platform
    if category:
        where.append("category = :category")
        params["category"] = category
    if period:
        where.append("period_label = :period")
        params["period"] = period

    with engine().connect() as conn:
        platforms = [r[0] for r in conn.execute(text(
            "SELECT DISTINCT platform FROM performance_metrics ORDER BY platform")).all()]
        categories = [r[0] for r in conn.execute(text(
            "SELECT DISTINCT category FROM performance_metrics "
            "WHERE category IS NOT NULL ORDER BY category")).all()]
        campaigns = [
            {"name": r[0], "platform": r[1], "spend": float(r[2] or 0)}
            for r in conn.execute(text(
                "SELECT COALESCE(campaign_name, campaign_id) AS name, "
                "       MIN(platform) AS platform, SUM(spend) AS spend "
                "FROM performance_metrics WHERE " + " AND ".join(where) +
                " GROUP BY COALESCE(campaign_name, campaign_id) "
                # Biggest spenders first: with hundreds of campaigns the ones worth
                # filtering to are at the top rather than wherever the alphabet puts them.
                " ORDER BY SUM(spend) DESC NULLS LAST"
                if engine().dialect.name == "postgresql" else
                "SELECT COALESCE(campaign_name, campaign_id) AS name, "
                "       MIN(platform) AS platform, SUM(spend) AS spend "
                "FROM performance_metrics WHERE " + " AND ".join(where) +
                " GROUP BY COALESCE(campaign_name, campaign_id) "
                " ORDER BY SUM(spend) IS NULL, SUM(spend) DESC"), params).all()
        ]
    return {"platforms": platforms, "categories": categories, "campaigns": campaigns}


# ---------------------------------------------------------------- dashboards

@app.get("/api/kpis")
def kpis(platform: str | None = None, period: str | None = None,
         compare: str | None = "auto", category: str | None = None,
         date: str | None = None, campaign: str | None = None,
         city: str | None = None, keyword: str | None = None):
    data = metrics.overall_kpis(engine(), period, category, date=date,
                                campaign=campaign, city=city, keyword=keyword)
    if platform:
        table = metrics.platform_comparison(engine(), period, compare, category, date=date,
                                            campaign=campaign, city=city, keyword=keyword)
        row = table[table["platform"] == platform]
        if row.empty:
            raise HTTPException(404, f"No data for platform {platform}")
        row = row.iloc[0]
        data = {"revenue": row["revenue"], "spend": row["spend"], "orders": row["orders"],
                "roas": row["roas"], "ctr": row["ctr"], "conv_rate": row["conv_rate"],
                "roi": (row["revenue"] - row["spend"]) / row["spend"] if row["spend"] else None,
                "impressions": row["impressions"], "clicks": row["clicks"],
                "revenue_growth": row.get("revenue_growth"),
                "spend_growth": row.get("spend_growth"),
                "roas_change": row.get("roas_change")}
    return {k: (None if v is None or (isinstance(v, float) and pd.isna(v)) else v)
            for k, v in data.items()}


@app.get("/api/platforms")
def platforms(period: str | None = None, compare: str | None = "auto",
              category: str | None = None, date: str | None = None,
              campaign: str | None = None, city: str | None = None,
              keyword: str | None = None):
    return records(metrics.platform_comparison(
        engine(), period, compare, category, date=date,
        campaign=campaign, city=city, keyword=keyword))


@app.get("/api/campaigns")
def campaigns(platform: str | None = None, category: str | None = None,
              search: str | None = None, sort: str = "revenue",
              period: str | None = "latest",
              city: str | None = None, keyword: str | None = None,
              campaign: str | None = None, date: str | None = None,
              limit: int = Query(200, le=2000)):
    return _filtered(metrics.campaigns, "campaign", platform, category, search, sort,
                     limit, period, city, keyword, campaign, date)


@app.get("/api/products")
def products(platform: str | None = None, category: str | None = None,
             search: str | None = None, sort: str = "revenue",
             period: str | None = "latest",
             city: str | None = None, keyword: str | None = None,
             campaign: str | None = None, date: str | None = None,
             limit: int = Query(200, le=2000)):
    return _filtered(metrics.products, "product", platform, category, search, sort,
                     limit, period, city, keyword, campaign, date)


@app.get("/api/keywords")
def keywords(platform: str | None = None, category: str | None = None,
             search: str | None = None, sort: str = "revenue",
             period: str | None = "latest",
             city: str | None = None, keyword: str | None = None,
             campaign: str | None = None, date: str | None = None,
             limit: int = Query(300, le=2000)):
    return _filtered(metrics.keywords, "keyword", platform, category, search, sort,
                     limit, period, city, keyword, campaign, date)


@app.get("/api/cities")
def cities(platform: str | None = None, category: str | None = None,
           search: str | None = None, sort: str = "revenue",
           period: str | None = "latest",
           city: str | None = None, keyword: str | None = None,
           campaign: str | None = None, date: str | None = None,
           limit: int = Query(300, le=2000)):
    return _filtered(metrics.cities, "city", platform, category, search, sort,
                     limit, period, city, keyword, campaign, date)


@app.get("/api/keywords/buckets")
def keyword_buckets(platform: str | None = None):
    """Best / worst / costly / wasted, as the brief asks for."""
    df = metrics.collapse(metrics.keywords(engine(), platform=platform), "keyword", ["platform"])
    if df.empty:
        return {"best": [], "worst": [], "high_cost": [], "wasted": []}
    spend = pd.to_numeric(df["spend"], errors="coerce").fillna(0)
    spending = df[spend >= config.MIN_SPEND_FOR_ALERT]
    losing = pd.to_numeric(spending["roas"], errors="coerce").fillna(0) < config.BREAKEVEN_ROAS
    return {
        "best": records(spending.sort_values("roas", ascending=False).head(15)),
        "worst": records(spending[losing].sort_values("spend", ascending=False).head(15)),
        "high_cost": records(df.sort_values("spend", ascending=False).head(15)),
        "wasted": records(metrics.wasted_spend(df, config.MIN_SPEND_FOR_ALERT).head(15)),
    }


@app.get("/api/trend")
def trend(platform: str | None = None, category: str | None = None):
    """Per-month series. Includes per-day columns because the loaded months are
    different lengths and only the daily rate is comparable."""
    return records(metrics.trend(engine(), platform, category))


@app.get("/api/funnel")
def funnel(period: str | None = None, platform: str | None = None,
           category: str | None = None):
    return metrics.funnel(engine(), period, platform, category)


@app.get("/api/segment")
def segment(category: str, period: str | None = None, platform: str | None = None):
    return metrics.segment(engine(), category, period, platform=platform)


@app.get("/api/locations/coverage")
def location_coverage(period: str | None = None):
    """Which platforms report a city at all, and what share of spend that is."""
    return metrics.city_coverage(engine(), period)


@app.get("/api/highlights")
def highlights(period: str | None = None):
    return ai.highlights(engine(), period)


# ---------------------------------------------------------------- intelligence

@app.get("/api/insights")
def get_insights():
    return records(ai.load(engine(), insights_table))


@app.get("/api/recommendations")
def get_recommendations(priority: str | None = None, platform: str | None = None,
                        limit: int = Query(200, le=1000)):
    df = ai.load(engine(), recommendations)
    if df.empty:
        return []
    if priority:
        df = df[df["priority"] == priority]
    if platform:
        df = df[df["platform"] == platform]
    df["_order"] = df["priority"].map(ai.PRIORITY_ORDER).fillna(9)
    df = df.sort_values(["_order", "impact_value"], ascending=[True, False]).drop(columns="_order")
    return records(df.head(limit))


@app.get("/api/alerts")
def get_alerts():
    df = ai.load(engine(), alerts)
    if not df.empty:
        df["_order"] = df["severity"].map(ai.PRIORITY_ORDER).fillna(9)
        df = df.sort_values("_order").drop(columns="_order")
    return records(df)


@app.get("/api/anomalies")
def get_anomalies():
    df = ai.load(engine(), anomalies)
    if not df.empty:
        df = df.reindex(df["z_score"].abs().sort_values(ascending=False).index)
    return records(df)


# ---------------------------------------------------------------- files

@app.get("/api/files")
def files():
    with engine().connect() as conn:
        df = pd.read_sql(uploaded_files.select(), conn)
    if not df.empty and "upload_date" in df:
        df["upload_date"] = df["upload_date"].astype(str)
    return records(df)


@app.post("/api/inspect")
def inspect(files: list[UploadFile]):
    """Read the staged files' columns and say what each is — WITHOUT loading anything.

    This powers the "identify before you upload" step: platform, report type,
    sub-platform, and the ad types actually present (so a file carrying both PLA and
    PCA rows shows both). Zips are expanded; duplicates and unknown shapes are flagged.
    """
    import tempfile
    from etl.ingest import discover, parse_file
    from etl.normalize import normalize

    tmp = Path(tempfile.mkdtemp(prefix="levista_inspect_"))
    out, seen = [], {}
    try:
        for item in files:
            if Path(item.filename).suffix.lower() not in ALLOWED_SUFFIXES:
                out.append({"filename": item.filename, "status": "rejected",
                            "note": f"unsupported file type {Path(item.filename).suffix or '(none)'}"})
                continue
            with (tmp / Path(item.filename).name).open("wb") as fh:
                shutil.copyfileobj(item.file, fh)
        for path in discover(tmp, tmp):          # expands zips
            for ds in parse_file(path, seen):
                row = {"filename": path.name, "sheet": ds.sheet_name or None, "note": ds.error}
                if ds.status == "duplicate":
                    out.append({**row, "status": "duplicate"}); continue
                if ds.signature is None:
                    out.append({**row, "status": "needs_review"}); continue
                ad_types = []
                try:
                    ad_types = sorted({str(a) for a in normalize(ds)["ad_type"].dropna() if a})
                except Exception:
                    pass
                out.append({**row, "status": ds.status,
                            "platform": ds.signature.platform,
                            "report_type": ds.signature.report_type,
                            "sub_platform": ds.sub_platform,
                            "ad_types": ad_types,
                            "category": ds.category,
                            "rows": int(len(ds.df)) if ds.df is not None else 0})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"files": out}


def _describe_upload(path: Path, platform, category, report_type):
    """What this file is, for naming: the uploader's choice wins, else its columns.

    Only reads the columns when something is missing — the same detection the ETL
    will do, so the name on disk matches how the file is actually loaded.
    """
    if path.suffix.lower() == ".zip":
        return platform, report_type, category      # a zip holds many, don't guess
    try:
        from etl.ingest import parse_file
        for ds in parse_file(path, {}):
            if ds.signature:
                # Columns decide how the file loads, so they decide its name too.
                # Declaring "campaign" for a file whose columns are a product report
                # produced Instamart_campaign_....csv loaded as a product report.
                return (ds.signature.platform or platform,
                        ds.signature.report_type or report_type,
                        category or ds.category)
    except Exception:
        pass                                        # naming must never fail an upload
    return platform, report_type, category


def _rename_upload(path: Path, platform, category, report_type, date) -> Path:
    """-> Zepto_city_Instant-Coffee_2026-08-01.xlsx (omitting whatever is unknown)."""
    plat, report, cat = _describe_upload(path, platform, category, report_type)
    parts = [str(p).strip().replace(" ", "-").replace("_", "-")
             for p in (plat, report, cat, date) if p]
    if not parts:
        return path                                 # nothing known — keep the original
    suffix = path.suffix.lower()
    stem = "_".join(parts)
    target = path.with_name(f"{stem}{suffix}")
    n = 2
    while target.exists():                          # several files of the same kind
        target = path.with_name(f"{stem}-{n}{suffix}")
        n += 1
    try:
        path.rename(target)
        return target
    except OSError:
        return path


@app.post("/api/upload")
def upload(background: BackgroundTasks, files: list[UploadFile],
           period: str | None = Form(None),
           platform: str | None = Form(None),
           category: str | None = Form(None),
           sub_platform: str | None = Form(None),
           report_type: str | None = Form(None),
           ad_type: str | None = Form(None),
           date: str | None = Form(None)):
    """Save the exports, then rebuild everything from the full input folder.

    A full rebuild (rather than an incremental append) is deliberate: de-duplication
    and primary-grain selection are decided across the whole set, so appending one
    file in isolation could double-count it.
    """
    UPLOADS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = UPLOADS / stamp
    destination.mkdir()

    saved, rejected, renames = [], [], []
    for item in files:
        suffix = Path(item.filename).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            rejected.append({"filename": item.filename,
                             "reason": f"unsupported file type {suffix or '(none)'}"})
            continue
        # Path() strips any directory component a client might send.
        target = destination / Path(item.filename).name
        with target.open("wb") as handle:
            shutil.copyfileobj(item.file, handle)
        # Platform exports arrive named things like "report_102877594.xlsx" or
        # "uy350fowetb.csv". Rename to what the file actually is, so the Data page and
        # the folder on disk are both readable a month later.
        final = _rename_upload(target, platform, category, report_type, date)
        if final.name != target.name:
            renames.append({"from": target.name, "to": final.name})
        saved.append(final.name)

    if not saved:
        destination.rmdir()
        raise HTTPException(400, {"message": "No usable files uploaded", "rejected": rejected})

    # A dated daily upload also fixes the month it loads into, so the day and the month
    # always agree without the user setting both.
    if date and not period and len(date) >= 7:
        period = date[:7]

    # Record what the uploader said about these files. The ETL rescans the whole input
    # folder, so the declaration has to sit on disk next to the files. Column signatures
    # still decide what each file actually is; this fills the gaps (date, product, …).
    if platform or category or sub_platform or report_type or ad_type or date:
        (destination / "_manifest.json").write_text(
            json.dumps({"platform": platform, "category": category,
                        "sub_platform": sub_platform, "report_type": report_type,
                        "ad_type": ad_type, "date": date, "period": period, "files": saved}, indent=1),
            encoding="utf-8")

    background.add_task(_rebuild, period)
    JOB.update(status="running",
               message=f"Processing {len(saved)} file(s)"
                       + (f" as {period}" if period else ""), finished_at=None)
    return {"saved": saved, "rejected": rejected, "renamed": renames,
            "platform": platform, "category": category,
            "sub_platform": sub_platform, "job": JOB}


@app.post("/api/data/clear")
def clear_data(confirm: str = Form(...)):
    """Empty the database and move the input files aside, for a fresh start.

    Destructive, so it requires confirm == "CLEAR". Source files are MOVED to a
    backup folder (not deleted), and every data/intelligence table is emptied — so
    after this the app is blank and ready for uploads through this page.
    """
    if confirm != "CLEAR":
        raise HTTPException(400, "Send confirm=CLEAR to clear all data.")

    backup = config.INPUT_DIR.parent / "_backup_input_cleared"
    backup.mkdir(exist_ok=True)
    moved = 0
    for item in list(config.INPUT_DIR.iterdir()):
        if item.name == "_uploads":
            shutil.rmtree(item, ignore_errors=True)   # clear prior uploads too
            continue
        dest = backup / item.name
        if dest.exists():
            dest = backup / f"{item.name}_{datetime.now():%H%M%S}"
        shutil.move(str(item), str(dest))
        moved += 1

    tables = ["raw_records", "performance_metrics", "insights",
              "recommendations", "alerts", "anomalies", "uploaded_files", "audit_log"]
    with engine().begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))

    # The billed totals are data too. Left behind, they become the headline the moment
    # any month with a matching key is loaded — so a "cleared" app showed ₹2,13,127 of
    # revenue against a freshly uploaded file that tracked ₹2,972. Kept as a .bak so
    # the figures can be restored, since they were typed in by hand.
    overrides = Path(metrics.__file__).resolve().parent.parent / "overrides.json"
    cleared_overrides = False
    if overrides.exists():
        try:
            current = json.loads(overrides.read_text(encoding="utf-8"))
        except ValueError:
            current = {}
        if any(k for k in current if not k.startswith("_")):
            overrides.with_suffix(".json.bak").write_text(
                json.dumps(current, indent=1), encoding="utf-8")
            overrides.write_text(
                json.dumps({"_comment": current.get("_comment", "")}, indent=1),
                encoding="utf-8")
            cleared_overrides = True

    JOB.update(status="done",
               message=f"All data cleared ({moved} source items moved to {backup.name}"
                       + (", billed totals reset" if cleared_overrides else "")
                       + "). Upload your files to begin.",
               finished_at=datetime.now().isoformat())
    return {"cleared": True, "moved": moved, "backup": str(backup),
            "overrides_cleared": cleared_overrides}


@app.get("/api/uploads")
def uploads():
    """Files sitting in the app's _uploads folder — exactly what Remove can delete.

    Listed from disk rather than the uploaded_files table because that table records
    the *extracted* contents of a zip (with throwaway temp paths), while the thing on
    disk to remove is the uploaded file itself.
    """
    if not UPLOADS.exists():
        return []
    out = []
    for p in sorted(UPLOADS.rglob("*")):
        if p.is_file() and p.name != "_manifest.json":
            out.append({"filename": p.name, "path": str(p),
                        "batch": p.parent.name,
                        "size_kb": round(p.stat().st_size / 1024, 1)})
    return out


@app.get("/api/reconciliation")
def reconciliation(period: str | None = None):
    """Per platform: billed total (overrides.json) vs what the uploaded reports sum to.

    The 'tracked' side is the raw platform_summary (campaign primary), pre-override,
    so the gap shows how much billed spend the uploaded exports do not account for.
    """
    from analytics import metrics
    eng = engine()
    period = period or metrics.latest_period(eng)
    with eng.connect() as conn:
        raw = {r[0]: (r[1] or 0, r[2] or 0) for r in conn.execute(text(
            "SELECT platform, spend, revenue FROM platform_summary WHERE period_label = :p"),
            {"p": period}).all()}
    billed = metrics._overrides().get(period or "", {})
    out = []
    for p in sorted(set(raw) | set(billed)):
        ts, tr = raw.get(p, (0, 0))
        b = billed.get(p, {})
        bs, br = b.get("spend"), b.get("revenue")
        out.append({
            "platform": p,
            "tracked_spend": ts, "tracked_revenue": tr,
            "billed_spend": bs, "billed_revenue": br,
            "gap_spend": None if bs is None else bs - ts,
            "gap_revenue": None if br is None else br - tr,
        })
    return {"period": period, "rows": out}


@app.post("/api/files/remove")
def remove_file(background: BackgroundTasks, path: str = Form(...)):
    """Delete a file that was uploaded through the app, then rebuild.

    Uploads-only: the target must live under the app's _uploads folder. Original
    source exports in the input folder are never touched. The database is rebuilt
    from what remains on disk, so the removed file's rows go with it.
    """
    target = Path(path).resolve()
    uploads = UPLOADS.resolve()
    if not target.is_relative_to(uploads):
        raise HTTPException(400, "Only files uploaded through the app can be removed.")
    if target.exists():
        target.unlink()
    # If its upload batch is now empty, drop the folder (and its stale manifest) too.
    folder = target.parent
    if folder != uploads and folder.is_relative_to(uploads):
        if not [p for p in folder.iterdir() if p.name != "_manifest.json"]:
            shutil.rmtree(folder, ignore_errors=True)

    background.add_task(_rebuild, None)
    JOB.update(status="running", message=f"Removing {target.name}", finished_at=None)
    return {"removed": target.name, "job": JOB}


@app.post("/api/rebuild")
def rebuild(background: BackgroundTasks, period: str | None = Form(None)):
    background.add_task(_rebuild, period)
    JOB.update(status="running", message="Rebuilding from input folder", finished_at=None)
    return {"job": JOB}


def _rebuild(period: str | None = None):
    """Reload one month. Other months in the database are untouched.

    Guarded by REBUILD_LOCK: uploading several times in quick succession used to
    start overlapping runs that deleted each other's rows mid-write.
    """
    from etl.run import run
    from reports import excel, ppt

    if not REBUILD_LOCK.acquire(blocking=False):
        JOB.update(status="running",
                   message="Another rebuild is already running; this request was skipped.")
        return
    try:
        counts = run(echo=False, period=period)
        eng = get_engine()
        ai.generate(eng)
        loaded = (f"{counts.get('ok', 0)} files loaded as "
                  f"{counts.get('period') or 'unlabelled'}, "
                  f"{counts.get('rows', 0)} rows, "
                  f"{counts.get('duplicate', 0)} duplicates skipped")

        # Writing the workbook and deck is a separate concern from loading the
        # data. If someone has the .xlsx open, Windows locks it — that must not be
        # reported as a failed import when every row landed correctly.
        try:
            excel.build(eng)
            ppt.build(eng)
            JOB.update(status="done", message=loaded,
                       finished_at=datetime.now().isoformat(timespec="seconds"))
        except PermissionError as exc:
            name = Path(getattr(exc, "filename", "") or "the report").name
            JOB.update(status="done",
                       message=f"{loaded}. The dashboard is up to date, but {name} "
                               "could not be rewritten — it is open in another "
                               "program. Close it and press Rebuild to refresh the file.",
                       finished_at=datetime.now().isoformat(timespec="seconds"))
    except Exception as exc:                                  # surfaced in the UI
        JOB.update(status="error", message=str(exc),
                   finished_at=datetime.now().isoformat(timespec="seconds"))
    finally:
        REBUILD_LOCK.release()


@app.get("/api/job")
def job():
    return JOB


# ---------------------------------------------------------------- exports

FETCHERS = {"campaigns": (metrics.campaigns, "campaign"),
            "products": (metrics.products, "product"),
            "keywords": (metrics.keywords, "keyword"),
            "cities": (metrics.cities, "city")}


@app.get("/api/export/table/{entity}")
def export_table(entity: str, fmt: str = "csv", platform: str | None = None,
                 category: str | None = None, search: str | None = None,
                 period: str | None = "latest", city: str | None = None,
                 keyword: str | None = None, campaign: str | None = None,
                 limit: int = Query(5000, le=50000)):
    """Export exactly what the table is showing, filters and all."""
    if entity not in FETCHERS:
        raise HTTPException(404, f"Unknown table {entity}")
    fetch, kind = FETCHERS[entity]
    rows = _filtered(fetch, kind, platform, category, search, "revenue", limit,
                     period, city, keyword, campaign)
    frame = pd.DataFrame(rows)
    stamp = period if period and period != "latest" else metrics.latest_period(engine())
    name = f"levista_{entity}_{stamp or 'all'}"

    buffer = io.BytesIO()
    if fmt == "xlsx":
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            frame.to_excel(writer, index=False, sheet_name=entity[:31])
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"{name}.xlsx"
    else:
        buffer.write(frame.to_csv(index=False).encode("utf-8-sig"))
        media, filename = "text/csv", f"{name}.csv"
    buffer.seek(0)
    return StreamingResponse(
        buffer, media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/export/{kind}")
def export(kind: str):
    names = {"excel": "Levista_Performance_Report.xlsx",
             "ppt": "Levista_Performance_Report.pptx"}
    if kind not in names:
        raise HTTPException(404, "Unknown export type")
    path = config.OUTPUT_DIR / names[kind]
    if not path.exists():
        raise HTTPException(404, f"{names[kind]} has not been generated yet — run a rebuild")
    return FileResponse(path, filename=names[kind])
