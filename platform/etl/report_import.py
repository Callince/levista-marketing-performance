"""Import a hand-built Levista report workbook as a historical month.

    python -m etl.report_import "..\\Levista Overall Campaign Report July Report.xlsx" --period 2026-07

This is deliberately separate from the signature registry. That registry reads raw
platform exports — one table per file. This reads the *output* workbook the team
assembled by hand, which is a different artifact: category blocks stacked down the
page, sometimes two blocks side by side, headers repeated per block, and campaign
names filled only on the first row of each group.

Only base measures are taken (impressions, clicks, spend, revenue, orders, units,
add-to-cart). CTR/CPC/CPM/ROAS are recomputed downstream from those, exactly as for
raw exports, so a month imported this way stays comparable with one loaded normally.
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import insert, select

from db.models import get_engine, init_db, performance_metrics, raw_records, uploaded_files
from etl.cities import canonical as city_name
from etl.load import lock_period, log, reset, seed_platforms
from etl.normalize import clean_number

CATEGORIES = {"instant coffee": "Instant Coffee", "filter coffee": "Filter Coffee",
              "cold coffee": "Cold Coffee"}
MONTH_WORDS = ("january", "february", "march", "april", "may", "june", "july",
               "august", "september", "october", "november", "december")

# Header alias -> canonical field. One vocabulary for every sheet; the workbook
# reuses the source platforms' own wording, which is why these overlap so much.
ALIASES = {
    "product name": "product_name", "productname": "product_name",
    "ad name": "product_name", "product_name": "product_name",
    "fsn id": "product_id", "product_id": "product_id", "asin": "product_id",
    "keyword": "keyword", "keywords": "keyword", "keywordname": "keyword",
    "match type": "match_type", "keywordmatchtype": "match_type",
    "campaign name": "campaign_name", "campaignname": "campaign_name",
    "campaign id / name": "campaign_name", "campaign name ": "campaign_name",
    "campaign name(new)": "campaign_name",
    "city": "city", "cityname": "city",
    "impressions": "impressions", "views": "impressions",
    "ad impressions": "impressions", "total_impressions": "impressions",
    "impression": "impressions",
    "clicks": "clicks", "total_clicks": "clicks",
    "spend": "spend", "spends": "spend", "ad spend": "spend",
    "total_budget_burnt": "spend", "total cost (inr)": "spend", "total cost": "spend",
    "revenue": "revenue", "ad revenue": "revenue", "total_gmv": "revenue",
    "gmv": "revenue", "sales": "revenue", "sales (inr)": "revenue",
    "orders": "orders", "purchases": "orders", "total_conversions": "orders",
    "order": "orders",
    "units sold": "units", "sold": "units", "total units sold": "units",
    "atc": "atc", "add to cart": "atc", "total_a2c": "atc",
    "new users": "new_users",
    "ctr": "ctr_reported", "total_ctr": "ctr_reported",
    "roas": "roas_reported", "roi": "roas_reported", "total_roi": "roas_reported",
    "cpc": "cpc_reported", "cpc (inr)": "cpc_reported",
    "cpm": "cpm_reported",
    # present in the workbook but not carried into the fact table
    "product_count": None, "ad type": None, "targeting": None, "month": None,
    "platform": None, "new to brand(p)": None, "share of voice": None,
    "keyword share of voice": None, "most viewed position": None,
}

MEASURES = ["impressions", "clicks", "spend", "revenue", "orders", "units", "atc",
            "new_users"]
REPORTED = ["ctr_reported", "cpc_reported", "cpm_reported", "roas_reported"]
LABELS = ["campaign_name", "product_name", "product_id", "keyword", "match_type", "city"]

# Sheet name -> (platform, sub_platform, report_type). The overall sheet is special:
# it carries its own Platform column.
SHEET_PLATFORMS = [
    ("flipkart national", "Flipkart", "National"),
    ("flipkart minutes", "Flipkart", "Minutes"),
    ("flipkart minuters", "Flipkart", "Minutes"),   # the workbook's own typo
    ("instamart", "Instamart", None),
    ("big basket", "BigBasket", None),
    ("bigbasket", "BigBasket", None),
    ("zepto", "Zepto", None),
    ("blinkit", "Blinkit", None),
    ("amazon", "Amazon", None),
]
PLATFORM_NAMES = {
    "big basket": ("BigBasket", None), "bigbasket": ("BigBasket", None),
    "flipkart minutes": ("Flipkart", "Minutes"),
    "flipkart national": ("Flipkart", "National"),
    "amazon": ("Amazon", None), "zepto": ("Zepto", None),
    "blinkit": ("Blinkit", None), "instamart": ("Instamart", None),
}


def _norm(value) -> str:
    return " ".join(str(value).strip().lower().split()) if pd.notna(value) else ""


def _sheet_identity(name: str):
    low = name.lower()
    platform = sub = None
    for token, plat, sub_platform in SHEET_PLATFORMS:
        if token in low:
            platform, sub = plat, sub_platform
            break
    if "product" in low:
        report = "product"
    elif "keyword" in low:
        report = "keyword"
    elif "city" in low:
        report = "city"
    elif "campaign" in low:
        report = "campaign"
    else:
        report = None
    return platform, sub, report


def _is_marker(row) -> str | None:
    """A category/month banner: the only populated cell in its row."""
    filled = [v for v in row if pd.notna(v) and str(v).strip() != ""]
    if len(filled) != 1:
        return None
    text = _norm(filled[0])
    if text in CATEGORIES:
        return CATEGORIES[text]
    if any(text.startswith(m) for m in MONTH_WORDS):
        return "__month__"
    return None


def _is_header(row) -> bool:
    """A header row: several known column names and no numbers."""
    filled = [v for v in row if pd.notna(v) and str(v).strip() != ""]
    if len(filled) < 3:
        return False
    if any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in filled):
        return False
    known = sum(1 for v in filled if _norm(v) in ALIASES)
    return known >= max(3, len(filled) // 2)


def _column_groups(frame: pd.DataFrame) -> list[list[int]]:
    """Split on fully empty columns — the workbook puts Instant and Filter Coffee
    side by side on some sheets, separated by one blank column."""
    groups, current = [], []
    for index in range(frame.shape[1]):
        if frame.iloc[:, index].isna().all():
            if current:
                groups.append(current)
            current = []
        else:
            current.append(index)
    if current:
        groups.append(current)
    return groups or [list(range(frame.shape[1]))]


def _blocks(frame: pd.DataFrame):
    """Yield (category, header_row_index, data_frame) for each block in a column group."""
    category = None
    row = 0
    while row < len(frame):
        values = frame.iloc[row].tolist()
        marker = _is_marker(values)
        if marker:
            if marker != "__month__":
                category = marker
            row += 1
            continue
        if _is_header(values):
            header = [_norm(v) for v in values]
            start = row + 1
            end = start
            while end < len(frame):
                nxt = frame.iloc[end].tolist()
                # A blank row separates campaign groups inside a block, so it must
                # not end one — the keyword sheets are full of them. Only a banner,
                # a fresh header, or the end of the sheet closes a block.
                if _is_marker(nxt) or _is_header(nxt):
                    break
                end += 1
            data = frame.iloc[start:end].copy()
            data.columns = header
            if not data.empty:
                yield category, data
            row = end
            continue
        row += 1


def _to_facts(data: pd.DataFrame, platform, sub, report, category) -> pd.DataFrame:
    mapped = {}
    for column in data.columns:
        field = ALIASES.get(column)
        if field and field not in mapped:
            mapped[field] = data[column]
    if not mapped:
        return pd.DataFrame()

    out = pd.DataFrame(mapped)
    for field in MEASURES + REPORTED:
        out[field] = (out[field].map(clean_number) if field in out else None)
    for field in LABELS:
        if field in out:
            out[field] = out[field].where(out[field].notna(), None)
        else:
            out[field] = None

    # Campaign names appear once per group and are blank on the rows beneath.
    if "campaign_name" in out:
        out["campaign_name"] = out["campaign_name"].ffill()
    # Same canonicalisation as the ETL, so an imported month and a loaded one agree
    # on what a city is called.
    if "city" in out:
        out["city"] = out["city"].map(city_name)

    # A row with no measure at all is a spacer or a stray total line.
    out = out[out[MEASURES].notna().any(axis=1)]
    # Drop repeated header text that slipped through as data.
    key = {"product": "product_name", "keyword": "keyword", "city": "city",
           "campaign": "campaign_name"}.get(report)
    if key and key in out:
        out = out[out[key].map(lambda v: _norm(v) not in ALIASES if v is not None else True)]

    out["platform"] = platform
    out["sub_platform"] = sub
    out["report_type"] = report
    out["entity_type"] = report
    out["category"] = category
    return out.reset_index(drop=True)


def _overall_sheet(frame: pd.DataFrame) -> pd.DataFrame:
    """The workbook's own cross-platform campaign table; its Platform column wins."""
    header = [_norm(v) for v in frame.iloc[0].tolist()]
    data = frame.iloc[1:].copy()
    data.columns = header
    data = data[data["platform"].notna()]

    rows = []
    for _, record in data.iterrows():
        platform, sub = PLATFORM_NAMES.get(_norm(record.get("platform")),
                                           (str(record.get("platform")).strip(), None))
        row = {"platform": platform, "sub_platform": sub, "report_type": "campaign",
               "entity_type": "campaign", "category": None,
               "ad_type": record.get("ad type"),
               "campaign_name": record.get("campaign id / name")}
        for source, field in (("impressions", "impressions"), ("clicks", "clicks"),
                              ("spends", "spend"), ("orders", "orders"),
                              ("revenue", "revenue"), ("atc", "atc")):
            row[field] = clean_number(record.get(source))
        for source, field in (("ctr", "ctr_reported"), ("roas", "roas_reported"),
                              ("cpc", "cpc_reported"), ("cpm", "cpm_reported")):
            row[field] = clean_number(record.get(source))
        rows.append(row)
    return pd.DataFrame(rows)


def read_workbook(path: Path) -> list[tuple]:
    """-> [(sheet_name, facts DataFrame, raw DataFrame)]"""
    workbook = pd.ExcelFile(path)
    out = []
    for sheet in workbook.sheet_names:
        frame = workbook.parse(sheet, header=None)
        if frame.empty:
            continue
        if _norm(sheet).startswith("overall campaign"):
            facts = _overall_sheet(frame)
            if not facts.empty:
                out.append((sheet, facts, frame))
            continue

        platform, sub, report = _sheet_identity(sheet)
        if not platform or not report:
            continue
        pieces = []
        for columns in _column_groups(frame):
            group = frame.iloc[:, columns].reset_index(drop=True)
            for category, data in _blocks(group):
                facts = _to_facts(data, platform, sub, report, category)
                if not facts.empty:
                    pieces.append(facts)
        if pieces:
            out.append((sheet, pd.concat(pieces, ignore_index=True), frame))
    return out


def derive_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    """Recompute the derived measures from the base ones, as the ETL does."""
    def ratio(numerator, denominator):
        return frame[numerator] / frame[denominator].where(frame[denominator] > 0)

    if "units" in frame and "orders" in frame:
        # Flipkart and Blinkit report units sold rather than order counts.
        frame["orders"] = pd.to_numeric(frame["orders"], errors="coerce").fillna(
            pd.to_numeric(frame["units"], errors="coerce"))
    frame["ctr"] = ratio("clicks", "impressions")
    frame["cpc"] = ratio("spend", "clicks")
    frame["cpm"] = ratio("spend", "impressions") * 1000
    frame["roas"] = ratio("revenue", "spend")
    frame["conv_rate"] = ratio("orders", "clicks")
    return frame


def import_workbook(path: Path, period: str, period_start: date, period_end: date,
                    echo: bool = True) -> dict:
    engine = get_engine()
    init_db(engine)
    sheets = read_workbook(Path(path))
    if not sheets:
        raise SystemExit(f"No importable sheets found in {path}")

    counts = {"sheets": 0, "rows": 0}
    with engine.begin() as conn:
        lock_period(conn, period)
        removed = reset(conn, period)
        seed_platforms(conn)
        log(conn, "import", "info",
            f"report workbook {Path(path).name} -> period {period}"
            + (f" (replaced {removed} files)" if removed else ""))

        for sheet, facts, raw in sheets:
            platform = facts["platform"].dropna().unique()
            result = conn.execute(insert(uploaded_files).values(
                filename=Path(path).name, path=str(path),
                sha256=f"report:{period}:{sheet}"[:64],
                platform=platform[0] if len(platform) == 1 else "Multiple",
                sub_platform=None,
                report_type=facts["report_type"].iloc[0],
                sheet_name=sheet, signature_key="report_workbook",
                category=None, period_start=period_start, period_end=period_end,
                period_label=period, row_count=len(facts),
                processing_status="ok", error=None, upload_date=datetime.now()))
            file_id = result.inserted_primary_key[0]

            conn.execute(insert(raw_records), [
                {"file_id": file_id, "row_index": i,
                 "payload": {str(k): (None if pd.isna(v) else v) for k, v in row.items()}}
                for i, row in enumerate(raw.astype(object).to_dict("records"))
            ])

            facts = derive_metrics(facts)
            facts["file_id"] = file_id
            facts["period_label"] = period
            facts["period_start"] = period_start
            facts["period_end"] = period_end
            records = facts.astype(object).where(pd.notna(facts), None).to_dict("records")
            allowed = set(performance_metrics.c.keys())
            conn.execute(insert(performance_metrics),
                         [{k: v for k, v in r.items() if k in allowed} for r in records])

            counts["sheets"] += 1
            counts["rows"] += len(facts)
            if echo:
                print(f"  {sheet[:38]:40} {len(facts):5} rows")

        # The workbook carries its own cross-platform campaign table, and that is the
        # authority for platform totals — so primary is simply "the campaign rows".
        # mark_primary() must not be used here: its Blinkit rule sums several ad-format
        # report types (right for raw exports, where there is no campaign export) and
        # would count Blinkit's keyword sheet on top of the campaign table.
        conn.execute(
            performance_metrics.update()
            .where(performance_metrics.c.period_label == period)
            .values(is_primary=(performance_metrics.c.report_type == "campaign")))
        primary = {(p, s, "campaign") for p, s in conn.execute(
            select(performance_metrics.c.platform, performance_metrics.c.sub_platform)
            .where(performance_metrics.c.period_label == period)
            .where(performance_metrics.c.report_type == "campaign").distinct())}
        log(conn, "import", "info", f"imported {counts['rows']} rows for {period}")

    if echo:
        print(f"\nImported {counts['sheets']} sheets, {counts['rows']} rows as {period}")
        print("primary grain: " + ", ".join(sorted(f"{p}/{s or '-'}/{r}" for p, s, r in primary)))
    return counts


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    source = Path(args[0])
    period = args[args.index("--period") + 1] if "--period" in args else None
    if not period:
        raise SystemExit("Pass --period YYYY-MM (the workbook does not state one reliably)")
    year, month = (int(x) for x in period.split("-"))
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1) - pd.Timedelta(days=1)
    import_workbook(source, period, start, end.date() if hasattr(end, "date") else end)
