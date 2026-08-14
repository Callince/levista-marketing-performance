"""ETL entry point.

    python -m etl.run                       # uses INPUT_DIR from .env
    python -m etl.run "C:\\path\\to\\exports"  # or an explicit folder
"""
from __future__ import annotations

import sys
import tempfile
from collections import Counter
from pathlib import Path

from sqlalchemy import func, select, text

import config
from db.models import get_engine, init_db, performance_metrics, uploaded_files
from etl.ingest import (declared_ad_types, declared_categories, declared_dates,
                        declared_platforms, declared_sub_platforms, discover, parse_file)
from etl.load import (load_dataset, lock_period, log, mark_primary, reset,
                      seed_platforms)
from etl.normalize import normalize


def derive_period(datasets) -> str | None:
    """The month this batch of files is about, as 'YYYY-MM'.

    Taken from the most common period_start across the files that state one.
    Amazon, Zepto and Blinkit exports carry no period at all — roughly a third of
    the feed — so the label is a property of the run, applied to every file in it,
    rather than something each file can be trusted to supply.
    """
    months = Counter(
        f"{ds.period_start:%Y-%m}" for ds in datasets
        if getattr(ds, "period_start", None) is not None
    )
    return months.most_common(1)[0][0] if months else None


def run(input_dir: Path | str | None = None, echo: bool = True,
        period: str | None = None, replace_all: bool = False) -> dict:
    """Load one month.

    Only the rows carrying this run's period label are replaced, so previously
    loaded months stay put and re-running a month is still idempotent. Pass
    replace_all=True for the old wipe-everything behaviour.
    """
    input_dir = Path(input_dir or config.INPUT_DIR)
    if not input_dir.exists():
        raise SystemExit(f"Input folder not found: {input_dir}")

    engine = get_engine()
    init_db(engine)

    counts = Counter()
    with tempfile.TemporaryDirectory(prefix="levista_zip_") as tmp:
        files = discover(input_dir, Path(tmp))
        if echo:
            print(f"Found {len(files)} data files under {input_dir}")

        declared = declared_platforms(input_dir)
        declared_cat = declared_categories(input_dir)
        declared_sub = declared_sub_platforms(input_dir)
        declared_ad = declared_ad_types(input_dir)
        declared_date = declared_dates(input_dir)
        seen_hashes: dict = {}
        # Parse everything first: the period label has to be known before the first
        # row is written, and it is derived from the batch as a whole.
        parsed = []
        for path in files:
            for ds in parse_file(path, seen_hashes, declared.get(path.resolve()),
                                 declared_cat.get(path.resolve()),
                                 declared_sub.get(path.resolve()),
                                 declared_ad.get(path.resolve()),
                                 declared_date.get(path.resolve())):
                frame = normalize(ds) if ds.status == "ok" else None
                parsed.append((ds, frame))

        label = period or derive_period(ds for ds, _ in parsed)
        if label is None and not replace_all:
            raise SystemExit(
                "No file in this folder states a reporting period, so the month cannot "
                "be inferred.\nRe-run with an explicit label, e.g.:\n"
                '    python -m etl.run --period 2026-09')
        if echo:
            print(f"Loading as period {label}"
                  + ("  (replacing everything)" if replace_all else
                     "  (replacing only this period)"))

        with engine.begin() as conn:
            lock_period(conn, label)      # waits out any concurrent run
            removed = reset(conn, None if replace_all else label)
            seed_platforms(conn)
            log(conn, "run", "info",
                f"ETL start: {input_dir} ({len(files)} files) period={label}")
            if removed:
                log(conn, "run", "info", f"replaced {removed} existing files for {label}")

            for ds, frame in parsed:
                load_dataset(conn, ds, frame, period_label=label)
                counts[ds.status] += 1
                if ds.status == "ok":
                    counts["rows"] += 0 if frame is None else len(frame)

            primary = mark_primary(conn, label)
            log(conn, "run", "info",
                "primary grain: " + ", ".join(sorted(f"{p}/{s or '-'}/{r}" for p, s, r in primary)))
            log(conn, "run", "info", f"ETL done: {dict(counts)}")

    counts["period"] = label
    if echo:
        _report(engine, counts)
    return dict(counts)


def _report(engine, counts):
    print("\n--- Ingestion ---")
    for status in ("ok", "duplicate", "needs_review", "failed"):
        if counts.get(status):
            print(f"  {status:13} {counts[status]}")
    print(f"  {'fact rows':13} {counts.get('rows', 0)}")

    with engine.connect() as conn:
        print("\n--- Rows per platform / report type ---")
        query = (select(performance_metrics.c.platform, performance_metrics.c.report_type,
                        func.count().label("n"), func.sum(performance_metrics.c.spend),
                        func.sum(performance_metrics.c.revenue))
                 .group_by(performance_metrics.c.platform, performance_metrics.c.report_type)
                 .order_by(performance_metrics.c.platform, performance_metrics.c.report_type))
        if counts.get("period"):
            query = query.where(performance_metrics.c.period_label == counts["period"])
        rows = conn.execute(query).all()
        for platform, report_type, n, spend, revenue in rows:
            print(f"  {platform:11} {report_type:10} {n:6}  spend {spend or 0:>12,.0f}"
                  f"  revenue {revenue or 0:>12,.0f}")

        # Scoped to the month just loaded. platform_summary now spans every loaded
        # month, so an unscoped query prints each platform once per period.
        label = counts.get("period")
        print(f"\n--- Platform totals for {label or 'all periods'} (de-duplicated) ---")
        for row in conn.execute(text(
            "SELECT platform, spend, revenue, orders, roas FROM platform_summary "
            + ("WHERE period_label = :p " if label else "")
            + "ORDER BY revenue DESC"), ({"p": label} if label else {})).all():
            platform, spend, revenue, orders, roas = row
            print(f"  {platform:11} spend {spend or 0:>11,.0f}  revenue {revenue or 0:>12,.0f}"
                  f"  orders {orders or 0:>7,.0f}  ROAS {roas or 0:>6.2f}")

        flagged = conn.execute(
            select(uploaded_files.c.filename, uploaded_files.c.processing_status,
                   uploaded_files.c.error)
            .where(uploaded_files.c.processing_status.in_(("needs_review", "failed")))
        ).all()
        if flagged:
            print("\n--- Needs attention ---")
            for name, status, error in flagged:
                print(f"  [{status}] {name}: {error}")

        # Loaded fine, but the filing looks wrong (folder/upload platform != columns).
        misfiled = conn.execute(
            select(uploaded_files.c.filename, uploaded_files.c.error)
            .where(uploaded_files.c.processing_status == "ok")
            .where(uploaded_files.c.error.isnot(None))
        ).all()
        if misfiled:
            print("\n--- Review filing (loaded by columns) ---")
            for name, error in misfiled:
                print(f"  [flag] {name}: {error}")

    if config.USING_FALLBACK_DB:
        print(f"\nNOTE: no DATABASE_URL set — wrote to SQLite at {config.DATABASE_URL}."
              "\n      Copy .env.example to .env and set your Postgres URL to use Postgres.")


if __name__ == "__main__":
    args = sys.argv[1:]
    period = None
    if "--period" in args:
        i = args.index("--period")
        period = args[i + 1]
        del args[i:i + 2]
    replace_all = "--replace-all" in args
    if replace_all:
        args.remove("--replace-all")
    run(args[0] if args else None, period=period, replace_all=replace_all)
