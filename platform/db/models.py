"""Schema. Portable across Postgres and SQLite via SQLAlchemy Core."""
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from config import DATABASE_URL

metadata = MetaData()

platforms = Table(
    "platforms", metadata,
    Column("name", String(50), primary_key=True),
    Column("display_name", String(80)),
)

uploaded_files = Table(
    "uploaded_files", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("filename", String(300), nullable=False),
    Column("path", Text, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("platform", String(50)),
    Column("sub_platform", String(50)),
    Column("report_type", String(50)),
    Column("sheet_name", String(120)),
    Column("signature_key", String(80)),
    Column("category", String(50)),
    Column("period_start", Date),
    Column("period_end", Date),
    # Which monthly load this file belongs to, e.g. "2026-08". Set per run, not
    # per file: Amazon, Zepto and Blinkit exports state no period of their own.
    Column("period_label", String(7), index=True),
    Column("row_count", Integer, default=0),
    Column("processing_status", String(20), default="pending"),  # ok | needs_review | duplicate | failed
    Column("error", Text),
    Column("upload_date", DateTime),
)

# Every source row verbatim — nothing is ever lost.
raw_records = Table(
    "raw_records", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("file_id", Integer, ForeignKey("uploaded_files.id"), index=True),
    Column("row_index", Integer),
    # JSONB on Postgres so the raw payload stays queryable; plain JSON on SQLite.
    Column("payload", JSON().with_variant(JSONB(), "postgresql")),
)

# The single normalized fact table. Every campaigns/keywords/products/cities/
# summary view below is a GROUP BY over this.
performance_metrics = Table(
    "performance_metrics", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("file_id", Integer, ForeignKey("uploaded_files.id"), index=True),
    Column("row_index", Integer),
    # grain
    Column("platform", String(50), index=True),
    Column("sub_platform", String(50)),
    Column("ad_type", String(50)),
    Column("report_type", String(50), index=True),
    Column("entity_type", String(50)),
    # True on the one set of report types that constitutes this platform's total
    # spend/revenue. See PRIMARY_REPORTS in etl/signatures.py.
    Column("is_primary", Boolean, default=False, index=True),
    Column("campaign_id", String(100)),
    Column("campaign_name", String(300)),
    Column("ad_group", String(200)),
    Column("keyword", String(300)),
    Column("match_type", String(50)),
    Column("product_id", String(100)),
    Column("product_name", String(400)),
    Column("city", String(120)),
    Column("placement", String(120)),
    Column("category", String(50)),
    Column("status", String(60)),
    Column("date", Date),
    Column("period_start", Date),
    Column("period_end", Date),
    Column("period_label", String(7), index=True),
    # base measures
    Column("impressions", Float),
    Column("clicks", Float),
    Column("spend", Float),
    Column("revenue", Float),
    Column("direct_revenue", Float),
    Column("indirect_revenue", Float),
    Column("orders", Float),
    Column("units", Float),
    Column("atc", Float),
    Column("new_users", Float),
    Column("budget", Float),
    # derived, recomputed from base measures so platforms are comparable
    Column("ctr", Float),
    Column("cpc", Float),
    Column("cpm", Float),
    Column("roas", Float),
    Column("conv_rate", Float),
    # what the platform itself reported, kept for audit
    Column("ctr_reported", Float),
    Column("cpc_reported", Float),
    Column("cpm_reported", Float),
    Column("roas_reported", Float),
)

insights = Table(
    "insights", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("platform", String(50)),
    Column("scope", String(50)),
    Column("what_happened", Text),
    Column("why_it_happened", Text),
    Column("what_to_do_next", Text),
    Column("period_start", Date),
    Column("period_end", Date),
    Column("generated_at", DateTime),
)

recommendations = Table(
    "recommendations", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("platform", String(50)),
    Column("entity_type", String(50)),
    Column("entity_name", String(400)),
    Column("action", String(80)),
    Column("priority", String(10)),  # High | Medium | Low
    Column("rationale", Text),
    Column("impact_value", Float),
    Column("generated_at", DateTime),
)

alerts = Table(
    "alerts", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("platform", String(50)),
    Column("severity", String(10)),
    Column("alert_type", String(60)),
    Column("message", Text),
    Column("entity_name", String(400)),
    Column("value", Float),
    Column("generated_at", DateTime),
)

anomalies = Table(
    "anomalies", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("platform", String(50)),
    Column("entity_type", String(50)),
    Column("entity_name", String(400)),
    Column("metric", String(40)),
    Column("value", Float),
    Column("cohort_mean", Float),
    Column("z_score", Float),
    Column("direction", String(10)),
    Column("generated_at", DateTime),
)

audit_log = Table(
    "audit_log", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime),
    Column("stage", String(40)),
    Column("level", String(10)),
    Column("message", Text),
    Column("file_id", Integer),
)


def get_engine(url: str | None = None):
    url = url or DATABASE_URL
    connect_args = {}
    kwargs = {}
    # The libsql driver (Turso) wants the token as an auth_token kwarg and breaks if
    # authToken is left in the URL query, so move it out of the URL into connect_args.
    # NullPool: Turso rotates Hrana streams, so a pooled connection goes stale
    # ("generation mismatch") — take a fresh connection each time instead.
    if url.startswith("sqlite+libsql"):
        import urllib.parse as up
        from sqlalchemy.pool import NullPool
        parts = up.urlsplit(url)
        q = up.parse_qs(parts.query)
        token = q.pop("authToken", None)
        if token:
            connect_args["auth_token"] = token[0]
        url = up.urlunsplit(parts._replace(query=up.urlencode(q, doseq=True)))
        kwargs["poolclass"] = NullPool
    return create_engine(url, future=True, connect_args=connect_args, **kwargs)


def _add_missing_columns(engine):
    """Additive migration for tables that already exist.

    create_all() only creates missing *tables*, so a column added to the model
    after a database was built would never appear. Dropping and recreating is not
    an option once more than one month is loaded — that history is the whole point
    of period_label — so declared-but-missing columns are added in place.
    """
    from sqlalchemy import inspect

    inspector = inspect(engine)
    added = []
    for table in metadata.tables.values():
        if not inspector.has_table(table.name):
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            type_sql = column.type.compile(engine.dialect)
            with engine.begin() as conn:
                conn.execute(text(
                    f'ALTER TABLE {table.name} ADD COLUMN {column.name} {type_sql}'))
                if column.index:
                    conn.execute(text(
                        f'CREATE INDEX IF NOT EXISTS ix_{table.name}_{column.name} '
                        f'ON {table.name} ({column.name})'))
            added.append(f"{table.name}.{column.name}")
    return added


def init_db(engine):
    """Create tables, then the analytics views over performance_metrics."""
    metadata.create_all(engine)
    _add_missing_columns(engine)
    from pathlib import Path

    raw = (Path(__file__).resolve().parent / "views.sql").read_text(encoding="utf-8")
    # strip comments first — a ';' inside one would split a statement in half
    body = "\n".join(l for l in raw.splitlines() if not l.lstrip().startswith("--"))
    statements = [s.strip() for s in body.split(";") if s.strip()]

    if engine.dialect.name == "postgresql":
        # campaign_summary is built on campaigns, so a bare DROP VIEW campaigns
        # fails on Postgres ("other objects depend on it"). SQLite tracks no
        # dependencies and rejects the CASCADE keyword outright, so the keyword is
        # added per-dialect here rather than written into the portable .sql file.
        statements = [f"{s} CASCADE" if s.upper().startswith("DROP VIEW") else s
                      for s in statements]

    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
