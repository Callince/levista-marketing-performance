"""Persist parsed datasets: raw rows verbatim + normalized facts + audit trail."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import delete, func, insert, select, text

from db.models import audit_log, performance_metrics, platforms, raw_records, uploaded_files
from etl.ingest import Dataset

KNOWN_PLATFORMS = ["Amazon", "Flipkart", "Instamart", "Zepto", "BigBasket", "Blinkit"]


def log(conn, stage: str, level: str, message: str, file_id: int | None = None):
    conn.execute(insert(audit_log).values(
        ts=datetime.now(), stage=stage, level=level, message=message, file_id=file_id))


def seed_platforms(conn):
    existing = {r[0] for r in conn.execute(platforms.select().with_only_columns(platforms.c.name))}
    for name in KNOWN_PLATFORMS:
        if name not in existing:
            conn.execute(insert(platforms).values(name=name, display_name=name))


def lock_period(conn, period_label: str | None):
    """Serialise every run that touches the same month.

    Two runs overlapping is not hypothetical — an upload queues a rebuild, and a
    second upload seconds later queues another. They are separate transactions, so
    one commits new uploaded_files rows between the other's child delete and parent
    delete, and the parent delete then fails on raw_records_file_id_fkey.

    An in-process lock cannot cover this: the CLI, the API and a second uvicorn
    worker are different processes. A Postgres advisory lock is held for the
    transaction and released automatically, so the second run simply waits.
    SQLite serialises writers already.
    """
    if period_label and conn.dialect.name == "postgresql":
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                     {"key": f"levista-etl:{period_label}"})


def reset(conn, period_label: str | None = None):
    """Clear the slice this run is about to rewrite.

    With a period label, only that month is removed, so previously loaded months
    survive and re-running the same month replaces it rather than duplicating it.
    Without one, everything goes — the original full-reload behaviour.
    """
    if period_label is None:
        for table in (performance_metrics, raw_records, uploaded_files, audit_log):
            conn.execute(delete(table))
        return

    # raw_records has no label of its own; it is reached through its file. The id
    # list must stay a live subquery rather than a list read into Python first —
    # a concurrent run committing new files between the read and the delete left
    # children behind and the parent delete then failed on the foreign key
    # (raw_records_file_id_fkey). The subquery is evaluated at delete time, so a
    # row that appears mid-flight is still covered.
    doomed = select(uploaded_files.c.id).where(uploaded_files.c.period_label == period_label)
    removed = conn.execute(
        select(func.count()).select_from(uploaded_files)
        .where(uploaded_files.c.period_label == period_label)).scalar()

    conn.execute(delete(raw_records).where(raw_records.c.file_id.in_(doomed)))
    conn.execute(delete(performance_metrics).where(
        (performance_metrics.c.period_label == period_label)
        | performance_metrics.c.file_id.in_(doomed)))
    conn.execute(delete(uploaded_files)
                 .where(uploaded_files.c.period_label == period_label))
    return removed


def mark_primary(conn, period_label: str | None = None) -> set[tuple]:
    """Flag the rows that constitute each platform's total, once we know what the
    feed actually contained this run. See signatures.primary_report_types.

    Scoped to one period: which report type is primary depends on what that month's
    feed contained, and a month missing a campaign export must fall back to its
    product export without August's files voting in that decision.
    """
    from sqlalchemy import distinct, select, update

    from etl.signatures import primary_report_types

    scope = (performance_metrics.c.period_label == period_label
             if period_label is not None else True)
    rows = conn.execute(
        select(distinct(performance_metrics.c.platform),
               performance_metrics.c.sub_platform,
               performance_metrics.c.report_type).where(scope)
    ).all()
    available: dict[tuple, set] = {}
    for platform, sub_platform, report_type in rows:
        available.setdefault((platform, sub_platform), set()).add(report_type)

    primary = primary_report_types(available)
    for platform, sub_platform, report_type in primary:
        clause = ((performance_metrics.c.platform == platform)
                  & (performance_metrics.c.report_type == report_type))
        clause = clause & (performance_metrics.c.sub_platform.is_(None)
                           if sub_platform is None
                           else performance_metrics.c.sub_platform == sub_platform)
        conn.execute(update(performance_metrics).where(clause & scope).values(is_primary=True))
    return primary


def _nullify(frame: pd.DataFrame) -> list[dict]:
    """NaN -> None so the DB stores NULL, not the float nan."""
    return frame.astype(object).where(pd.notna(frame), None).to_dict("records")


def load_dataset(conn, ds: Dataset, normalized: pd.DataFrame,
                 period_label: str | None = None) -> int:
    sig = ds.signature
    result = conn.execute(insert(uploaded_files).values(
        filename=ds.filename,
        path=str(ds.path),
        sha256=ds.sha256,
        # Fall back to what the uploader declared so an unrecognised export is
        # still attributable to a platform on the Data page.
        platform=sig.platform if sig else ds.declared_platform,
        sub_platform=ds.sub_platform,
        report_type=sig.report_type if sig else None,
        sheet_name=ds.sheet_name,
        signature_key=sig.key if sig else None,
        category=ds.category,
        period_start=ds.period_start,
        period_end=ds.period_end,
        period_label=period_label,
        row_count=0 if normalized is None else len(normalized),
        processing_status=ds.status,
        error=ds.error,
        upload_date=datetime.now(),
    ))
    file_id = result.inserted_primary_key[0]

    if ds.status != "ok" or ds.df is None:
        log(conn, "ingest", "warn" if ds.status != "failed" else "error",
            f"{ds.filename} [{ds.sheet_name}]: {ds.status} — {ds.error}", file_id)
        return file_id

    # Raw rows verbatim — nothing from the source is ever lost.
    raw_payloads = [
        {"file_id": file_id, "row_index": i, "payload": {k: (None if pd.isna(v) else v)
                                                         for k, v in row.items()}}
        for i, row in enumerate(ds.df.astype(object).to_dict("records"))
    ]
    if raw_payloads:
        conn.execute(insert(raw_records), raw_payloads)

    if normalized is not None and not normalized.empty:
        records = _nullify(normalized)
        for record in records:
            record["file_id"] = file_id
            record["period_label"] = period_label
        conn.execute(insert(performance_metrics), records)

    log(conn, "ingest", "info",
        f"{ds.filename} [{ds.sheet_name}] -> {sig.key}: {len(normalized)} rows", file_id)
    return file_id
