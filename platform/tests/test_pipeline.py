"""One runnable check for the parts that would silently produce wrong numbers.

    python -m tests.test_pipeline

Plain asserts, no framework. Runs the real pipeline over the real input folder.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

from sqlalchemy import func, select, text

import config
from analytics import metrics
from db.models import get_engine, performance_metrics, uploaded_files
from etl.ingest import parse_file
from etl.normalize import clean_number

ROOT = config.INPUT_DIR

# Files whose folder says one thing and whose columns say another. Getting these
# wrong is the failure mode this whole design exists to prevent.
MISFILED = [
    (r"Zepto\PLA\keywords performance\Instant Coffee\report_139244357.xlsx",
     "Zepto", "product"),
    (r"Zepto\PCA\Keywords Report\instant coffee\report_717410614 (1).xlsx",
     "Zepto", "city"),
    (r"Zepto\PLA\Citywise performance\Instant Coffee\report_230995773.xlsx",
     "Zepto", "keyword"),
    (r"Flipkart\Filpkart National\Campaign Report\zr8scxkwk8k.csv",
     "Flipkart", "keyword"),
    (r"Flipkart\Filpkart National\keywords report\m9cqvyocf58.csv",
     "Flipkart", "placement"),
    (r"BigBasket\product performance\report_102877594.xlsx",
     "Zepto", "city"),
]

AMAZON_CAMPAIGNS = r"Amazon\Campaign Report\Amazon Campaign performance aug 1 - 10.csv"

checks = 0


def check(condition, message):
    global checks
    assert condition, f"FAILED: {message}"
    checks += 1
    print(f"  ok  {message}")


def test_detection_ignores_folder_names():
    print("\n[1] report type comes from columns, not the folder name")
    for relative, platform, report_type in MISFILED:
        path = ROOT / relative
        results = [d for d in parse_file(path, {}) if d.signature]
        check(results, f"{Path(relative).name} matched a signature")
        signature = results[0].signature
        check(signature.platform == platform and signature.report_type == report_type,
              f"{Path(relative).parent.name}/{Path(relative).name} -> "
              f"{signature.platform} {signature.report_type} (folder says otherwise)")


def test_duplicates_collapse(engine):
    """Scoped to one month: duplicates are counted per load, so several months of
    the same feed would otherwise sum together."""
    print("\n[2] byte-identical files are counted once")
    period = metrics.latest_period(engine)
    with engine.connect() as conn:
        rows = conn.execute(
            select(uploaded_files.c.sha256, func.count(), uploaded_files.c.processing_status)
            .group_by(uploaded_files.c.sha256, uploaded_files.c.processing_status)).all()
        duplicates = conn.execute(
            select(func.count()).select_from(uploaded_files)
            .where(uploaded_files.c.processing_status == "duplicate")
            .where(uploaded_files.c.period_label == period)).scalar()
        # every hash must contribute at most one non-duplicate, fact-bearing entry
        loaded = conn.execute(
            select(uploaded_files.c.sha256, func.count())
            .where(uploaded_files.c.processing_status == "ok")
            .group_by(uploaded_files.c.sha256)).all()
    # Not a fixed count: uploading through the app adds files to the input folder, so
    # any number is legitimate. What must hold is that every duplicate is genuinely
    # byte-identical to something already loaded, and no content is loaded twice.
    with engine.connect() as conn:
        loaded_hashes = {h for (h,) in conn.execute(
            select(uploaded_files.c.sha256)
            .where(uploaded_files.c.processing_status == "ok")
            .where(uploaded_files.c.period_label == period))}
        duplicate_hashes = [h for (h,) in conn.execute(
            select(uploaded_files.c.sha256)
            .where(uploaded_files.c.processing_status == "duplicate")
            .where(uploaded_files.c.period_label == period))]

    check(duplicates >= 10,
          f"{duplicates} duplicate files detected and skipped in {period}")
    orphans = [h for h in duplicate_hashes if h not in loaded_hashes]
    check(not orphans,
          f"every duplicate matches a loaded file (found {len(orphans)} that do not)")
    # One workbook legitimately yields several rows — Blinkit ships five differently
    # shaped sheets in a single file, so they share a hash. The pair that must stay
    # unique is (content, sheet).
    with engine.connect() as conn:
        repeated = conn.execute(
            select(uploaded_files.c.sha256, uploaded_files.c.sheet_name, func.count())
            .where(uploaded_files.c.processing_status == "ok")
            .where(uploaded_files.c.period_label == period)
            .group_by(uploaded_files.c.sha256, uploaded_files.c.sheet_name)
            .having(func.count() > 1)).all()
    check(not repeated,
          f"no (content, sheet) pair was loaded twice (found {len(repeated)})")


def test_amazon_spend_matches_source(engine):
    """Scoped to the newest month — July's figures share this table now."""
    print("\n[3] loaded totals equal the raw file")
    period = metrics.latest_period(engine)
    with open(ROOT / AMAZON_CAMPAIGNS, encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    expected = sum(clean_number(r["Total cost"]) or 0 for r in rows)
    with engine.connect() as conn:
        actual = conn.execute(
            select(func.sum(performance_metrics.c.spend))
            .where(performance_metrics.c.platform == "Amazon")
            .where(performance_metrics.c.report_type == "campaign")
            .where(performance_metrics.c.period_label == period)).scalar()
    check(abs(expected - actual) < 0.01,
          f"Amazon campaign spend {actual:,.2f} == raw CSV {expected:,.2f}")
    check(len(rows) == conn_count(engine, "Amazon", "campaign", period),
          f"{len(rows)} campaign rows loaded, none dropped")


def conn_count(engine, platform, report_type, period=None) -> int:
    query = (select(func.count()).select_from(performance_metrics)
             .where(performance_metrics.c.platform == platform)
             .where(performance_metrics.c.report_type == report_type))
    if period:
        query = query.where(performance_metrics.c.period_label == period)
    with engine.connect() as conn:
        return conn.execute(query).scalar()


def test_ctr_units(engine):
    """CTR arrives as a fraction on Amazon and as a percent on Flipkart/BigBasket.

    A range check is not enough here: Instamart genuinely reports 200% on rows with
    1 impression and 2 clicks, so the real invariant is that each platform's declared
    unit was applied. These assert exact known values from the source files.
    """
    print("\n[4] CTR unit conversion is right per platform")
    cases = [
        # (where clause, source value in the file, expected stored value)
        ("platform='Flipkart' AND keyword='Levista' AND ctr_reported IS NOT NULL",
         "12.6603%", 0.126603),
        ("platform='BigBasket' AND keyword='cothas' AND match_type='PHRASE'",
         "4.35 (percent)", 0.0435),
        ("platform='Amazon' AND report_type='campaign' "
         "AND campaign_name LIKE 'AT-Filter%'", "0.0062 (fraction)", 0.0062),
    ]
    period = metrics.latest_period(engine)
    for where, source, expected in cases:
        with engine.connect() as conn:
            got = conn.execute(text(
                f"SELECT ctr_reported FROM performance_metrics WHERE {where} "
                f"AND period_label = '{period}' LIMIT 1")).scalar()
        check(got is not None and abs(got - expected) < 1e-6,
              f"{source} -> {got} (expected {expected})")

    # A whole-platform unit mistake would push the bulk of a platform's rows above 1.
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT platform, "
            "  SUM(CASE WHEN ctr_reported > 1 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) "
            "FROM performance_metrics WHERE ctr_reported IS NOT NULL "
            f"AND period_label = '{period}' GROUP BY platform")).all()
    for platform, share in rows:
        check(share < 0.05,
              f"{platform}: {share * 100:.1f}% of rows above 100% CTR (source outliers only)")


def test_totals_are_not_double_counted(engine):
    print("\n[5] platform totals count each rupee once")
    period = metrics.latest_period(engine)
    table = metrics.platform_comparison(engine, period)
    blinkit = table[table["platform"] == "Blinkit"]
    check(not blinkit.empty, "Blinkit present in the platform summary")
    with engine.connect() as conn:
        claimables = conn.execute(text(
            "SELECT SUM(spend) FROM performance_metrics "
            f"WHERE platform='Blinkit' AND report_type='budget' "
            f"AND period_label = '{period}'")).scalar()
    total = float(blinkit.iloc[0]["spend"])
    # Blinkit's four ad formats must reconcile with its own MTD budget sheet.
    check(abs(total - claimables) < 1.0,
          f"Blinkit primary spend {total:,.0f} reconciles with its budget sheet "
          f"{claimables:,.0f}")

    with engine.connect() as conn:
        naive = conn.execute(text(
            "SELECT SUM(spend) FROM performance_metrics WHERE platform='Instamart' "
            f"AND period_label = '{period}'")).scalar()
    instamart = float(table[table["platform"] == "Instamart"].iloc[0]["spend"])
    check(naive > instamart * 2.5,
          f"Instamart guarded against triple counting ({naive:,.0f} raw vs "
          f"{instamart:,.0f} de-duplicated)")


def test_period_scoping(engine):
    """Months must coexist, and growth must be arithmetic — not a guess.

    August is loaded again as a synthetic month with revenue halved, so every
    platform's revenue growth has to come out at exactly +100%. The synthetic month
    is removed again at the end.
    """
    print("\n[7] months load side by side and compare correctly")
    from etl.run import run

    before = metrics.periods(engine)
    check("2026-08" in before, f"August is loaded to start with: {before}")
    august = metrics.platform_comparison(engine, "2026-08")["revenue"].sum()

    try:
        run(period="1999-01", echo=False)
        with engine.begin() as conn:
            conn.execute(text("UPDATE performance_metrics SET revenue = revenue * 0.5 "
                              "WHERE period_label = '1999-01'"))

        check("1999-01" in metrics.periods(engine) and "2026-08" in metrics.periods(engine),
              "both months present after the second load")
        check(abs(metrics.platform_comparison(engine, "2026-08")["revenue"].sum() - august) < 1,
              "loading another month left August's totals untouched")
        check(metrics.prior_period(engine, "2026-08") in ("1999-01", "2026-07"),
              "August has an earlier month to compare against")

        table = metrics.platform_comparison(engine, "2026-08", compare_to="1999-01")
        check(len(table) == 6, "all six platforms still present")
        for _, row in table.iterrows():
            check(abs(row["revenue_growth"] - 1.0) < 1e-9,
                  f"{row['platform']}: revenue growth +100% against a halved copy")
        check(all(abs(row["orders_growth"]) < 1e-9 for _, row in table.iterrows()),
              "orders unchanged, so orders growth is 0%")

        # Entity views must scope too, not just the platform summary.
        check(len(metrics.campaigns(engine, period="1999-01")) > 0
              and len(metrics.campaigns(engine, period="2026-08")) > 0,
              "campaign view returns rows for each month independently")

        # Re-running a month replaces it rather than doubling it.
        run(period="1999-01", echo=False)
        check(metrics.periods(engine).count("1999-01") == 1,
              "re-running the synthetic month did not create a duplicate period")
        july_rows = _count_period(engine, "1999-01")
        august_rows = _count_period(engine, "2026-08")
        check(july_rows == august_rows,
              f"synthetic month reloaded to {july_rows} rows, same as August's {august_rows} — no duplication")
    finally:
        with engine.begin() as conn:
            conn.execute(text(
                "DELETE FROM raw_records WHERE file_id IN "
                "(SELECT id FROM uploaded_files WHERE period_label = '1999-01')"))
            conn.execute(text("DELETE FROM performance_metrics WHERE period_label = '1999-01'"))
            conn.execute(text("DELETE FROM uploaded_files WHERE period_label = '1999-01'"))
    check("1999-01" not in metrics.periods(engine), "synthetic month removed again")


def _count_period(engine, label) -> int:
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT COUNT(*) FROM performance_metrics WHERE period_label = :p"),
            {"p": label}).scalar()


def test_uneven_periods(engine):
    """A 10-day month against a 31-day one must not be compared on totals."""
    print("\n[8] months of different lengths compare per day, not on totals")
    if "2026-07" not in metrics.periods(engine):
        print("  -- July not loaded, skipping")
        return

    july_days = metrics.period_days(engine, "2026-07")
    august_days = metrics.period_days(engine, "2026-08")
    check(july_days == 31 and august_days == 10,
          f"July covers {july_days} days, August {august_days}")

    table = metrics.platform_comparison(engine, "2026-08", compare_to="2026-07")
    check(table["growth_basis"].iloc[0] == "per day",
          "uneven spans switch growth onto a per-day basis")

    # The headline must follow the daily rate, not the totals.
    now = table["revenue"].sum()
    before = table["prev_revenue"].sum()
    check(now < before,
          f"August total revenue is below July's ({now:,.0f} < {before:,.0f})")
    check(now / august_days > before / july_days,
          "but August's daily revenue is higher — which is what the report must say")

    scale = august_days / july_days
    for _, row in table.iterrows():
        if row["prev_revenue"] and row["prev_revenue"] > 0:
            expected = (row["revenue"] - row["prev_revenue"] * scale) / (row["prev_revenue"] * scale)
            check(abs(row["revenue_growth"] - expected) < 1e-9,
                  f"{row['platform']}: growth normalised by period length")

    # July's own totals must match the source workbook exactly.
    july = metrics.platform_comparison(engine, "2026-07", compare_to=None)
    check(abs(july["spend"].sum() - 2_431_502) < 1,
          f"July spend {july['spend'].sum():,.0f} matches the source workbook")
    check(abs(july["revenue"].sum() - 7_670_890) < 1,
          f"July revenue {july['revenue'].sum():,.0f} matches the source workbook")
    check(len(july) == 6, "all six platforms present in July")


def test_currency_parsing():
    print("\n[6] dirty numbers parse correctly")
    cases = [("₹ 3,09,832.39", 309832.39), ("₹ 1,000.00", 1000.0), ("29.19%", 0.2919),
             ("NA", None), ("-", None), ("", None), ("0", 0.0), ("4.35", 4.35)]
    for raw, expected in cases:
        got = clean_number(raw)
        check(got == expected or (got is None and expected is None),
              f"{raw!r} -> {got!r}")
    check(clean_number("4.35", is_pct=True) == 0.0435, "'4.35' as percent -> 0.0435")


def main():
    if not ROOT.exists():
        sys.exit(f"Input folder not found: {ROOT}")
    from etl.run import run

    print("Running the ETL over the real input folder...")
    run(echo=False)
    engine = get_engine()

    test_detection_ignores_folder_names()
    test_duplicates_collapse(engine)
    test_amazon_spend_matches_source(engine)
    test_ctr_units(engine)
    test_totals_are_not_double_counted(engine)
    test_period_scoping(engine)
    test_uneven_periods(engine)
    test_currency_parsing()
    print(f"\nAll {checks} checks passed.")


if __name__ == "__main__":
    main()
