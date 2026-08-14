"""Aggregations the reports and (phase 2) the API read from.

Everything here is a thin pandas wrapper over the SQL views, so a number shown in
Excel, in PowerPoint and on the dashboard can only ever come from one definition.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from db.models import get_engine

PLATFORM_ORDER = ["Amazon", "Flipkart", "Instamart", "Zepto", "BigBasket", "Blinkit"]


def _overrides() -> dict:
    """Authoritative platform totals from overrides.json (see that file's _comment).

    Read fresh each call so editing the file takes effect on the next request; it is
    tiny, so the cost is nil.
    """
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "overrides.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _apply_overrides(df: pd.DataFrame, period: str | None) -> pd.DataFrame:
    """Replace summed spend/revenue with the billed total where one is configured.

    Only whole-platform totals are overridden (no category split), and ROAS is
    recomputed from them. Orders/impressions/clicks stay as loaded — the billing
    dashboards give spend and revenue only.
    """
    table = _overrides().get(period or "", {})
    for i, platform in df["platform"].items():
        o = table.get(platform)
        if not o:
            continue
        if "spend" in o:
            df.at[i, "spend"] = o["spend"]
        if "revenue" in o:
            df.at[i, "revenue"] = o["revenue"]
        spend = df.at[i, "spend"]
        df.at[i, "roas"] = (df.at[i, "revenue"] / spend) if spend else None
    return df


def _read(engine, sql: str, **params) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)


def facts(engine=None) -> pd.DataFrame:
    return _read(engine or get_engine(), "SELECT * FROM performance_metrics")


def periods(engine=None) -> list[str]:
    """Loaded months, oldest first."""
    df = _read(engine or get_engine(),
               "SELECT DISTINCT period_label FROM performance_metrics "
               "WHERE period_label IS NOT NULL ORDER BY period_label")
    return df["period_label"].tolist() if not df.empty else []


def latest_period(engine=None) -> str | None:
    found = periods(engine)
    return found[-1] if found else None


def prior_period(engine=None, period: str | None = None) -> str | None:
    """The month loaded immediately before this one, if any."""
    found = periods(engine)
    period = period or (found[-1] if found else None)
    if period in found:
        index = found.index(period)
        return found[index - 1] if index > 0 else None
    return None


def period_days(engine=None, period: str | None = None) -> int | None:
    """How many days a loaded month actually covers.

    Not always a whole month: the August feed covers 1–10 August only. Comparing a
    31-day month against a 10-day one without saying so is how a good month gets
    reported as a collapse.
    """
    start, end = reporting_period(engine, period)
    return (end - start).days + 1 if start and end else None


def reporting_period(engine=None, period: str | None = None) -> tuple:
    scope = " AND period_label = :period" if period else ""
    df = _read(engine or get_engine(),
               "SELECT DISTINCT period_start AS s, period_end AS e "
               "FROM performance_metrics WHERE period_start IS NOT NULL" + scope,
               **({"period": period} if period else {}))
    if df.empty:
        return None, None

    # SQLite hands dates back as strings; normalize both backends to date objects.
    def _as_date(value):
        if value is None or pd.isna(value):
            return None
        return pd.to_datetime(value).date()

    starts = [d for d in map(_as_date, df["s"]) if d]
    ends = [d for d in map(_as_date, df["e"]) if d]
    # Exports carry mixed, sometimes-misparsed dates. When a month is selected, keep only
    # the dates that actually fall inside it, so one stray value can't distort the span.
    if period and "-" in period:
        starts = [d for d in starts if d.strftime("%Y-%m") == period] or starts
        ends = [d for d in ends if d.strftime("%Y-%m") == period] or ends
    return (min(starts) if starts else None, max(ends) if ends else None)


def _scope(period=None, platform=None, category=None, primary=True, date=None) -> tuple[str, dict]:
    where, params = [], {}
    if primary:
        where.append("is_primary")
    # A specific day narrows on period_start; otherwise scope to the month label.
    if date:
        where.append("period_start = :date")
        params["date"] = date
    elif period:
        where.append("period_label = :period")
        params["period"] = period
    if platform:
        where.append("platform = :platform")
        params["platform"] = platform
    if category:
        where.append("category = :category")
        params["category"] = category
    return (" WHERE " + " AND ".join(where) if where else ""), params


# Day-level tables come straight from the fact table (the summary views collapse a
# whole month). Each entry mirrors one summary view's grain and filters.
_DAY_METRICS = """SUM(impressions) AS impressions, SUM(clicks) AS clicks,
       SUM(spend) AS spend, SUM(revenue) AS revenue, SUM(orders) AS orders, SUM(units) AS units,
       CASE WHEN SUM(spend) > 0 THEN SUM(revenue)/SUM(spend) END AS roas,
       CASE WHEN SUM(impressions) > 0 THEN SUM(clicks)*1.0/SUM(impressions) END AS ctr,
       CASE WHEN SUM(clicks) > 0 THEN SUM(spend)/SUM(clicks) END AS cpc,
       CASE WHEN SUM(impressions) > 0 THEN SUM(spend)/SUM(impressions)*1000 END AS cpm,
       CASE WHEN SUM(clicks) > 0 THEN SUM(orders)*1.0/SUM(clicks) END AS conv_rate"""

_DAY_CFG = {
    "campaign_summary": dict(primary=True, presence="COALESCE(campaign_name, campaign_id) IS NOT NULL",
        dims="platform, sub_platform, ad_type, category, COALESCE(campaign_name, campaign_id) AS campaign_name",
        group="platform, sub_platform, ad_type, category, COALESCE(campaign_name, campaign_id)"),
    "product_summary": dict(primary=False, presence="COALESCE(product_name, product_id) IS NOT NULL",
        dims="platform, category, COALESCE(product_name, product_id) AS product_name, MAX(product_id) AS product_id",
        group="platform, category, COALESCE(product_name, product_id)"),
    "keyword_summary": dict(primary=False, presence="keyword IS NOT NULL",
        dims="platform, category, keyword, match_type, MAX(campaign_name) AS campaign_name",
        group="platform, category, keyword, match_type"),
    "city_summary": dict(primary=False, presence="city IS NOT NULL",
        dims="platform, category, city",
        group="platform, category, city"),
}


def day_entity(engine, view, date, platform=None, category=None) -> pd.DataFrame:
    cfg = _DAY_CFG[view]
    clause, params = _scope(platform=platform, category=category, primary=cfg["primary"], date=date)
    sql = (f"SELECT {cfg['dims']}, {_DAY_METRICS} FROM performance_metrics{clause} "
           f"AND {cfg['presence']} GROUP BY {cfg['group']}")
    return _read(engine or get_engine(), sql, **params)


PLATFORM_TOTALS_SQL = """
    SELECT platform,
           SUM(impressions) AS impressions, SUM(clicks) AS clicks,
           SUM(spend) AS spend, SUM(revenue) AS revenue,
           SUM(orders) AS orders, SUM(units) AS units,
           CASE WHEN SUM(spend) > 0 THEN SUM(revenue) / SUM(spend) END AS roas,
           CASE WHEN SUM(impressions) > 0 THEN SUM(clicks) / SUM(impressions) END AS ctr,
           CASE WHEN SUM(clicks) > 0 THEN SUM(spend) / SUM(clicks) END AS cpc,
           CASE WHEN SUM(clicks) > 0 THEN SUM(orders) / SUM(clicks) END AS conv_rate
    FROM performance_metrics{clause}
    GROUP BY platform
"""


def _finish_platforms(engine, df, period, date=None) -> pd.DataFrame:
    """Shares, partial flag and ranks — the single-day path's tail (no growth)."""
    if df.empty:
        return df
    from etl.signatures import PRIMARY_PRIORITY
    total_revenue = df["revenue"].sum()
    total_spend = df["spend"].sum()
    df["revenue_share"] = df["revenue"] / total_revenue if total_revenue else None
    df["spend_share"] = df["spend"] / total_spend if total_spend else None
    df["period_label"] = period
    for col in ("compare_to", "revenue_growth", "spend_growth", "orders_growth",
                "roas_change", "days", "compare_days", "growth_basis", "clicks_coverage"):
        df[col] = None
    prim = _read(engine, "SELECT platform, report_type FROM performance_metrics "
                 "WHERE is_primary = 1 AND period_start = :date", date=date)
    got = prim.groupby("platform")["report_type"].apply(set).to_dict() if not prim.empty else {}
    df["primary_report"] = df["platform"].map(lambda p: ", ".join(sorted(got.get(p, set()))))
    df["partial"] = df["platform"].map(
        lambda p: bool(PRIMARY_PRIORITY.get(p)) and PRIMARY_PRIORITY[p][0] not in got.get(p, set()))
    df["rank_revenue"] = df["revenue"].rank(ascending=False, method="min").astype(int)
    df["rank_roas"] = df["roas"].rank(ascending=False, method="min")
    return df.sort_values("revenue", ascending=False).reset_index(drop=True)


def platform_comparison(engine=None, period: str | None = None,
                        compare_to: str | None = "auto",
                        category: str | None = None, date: str | None = None) -> pd.DataFrame:
    """Platform league table with contribution share, rank and month-on-month growth.

    `period` defaults to the most recently loaded month. `compare_to="auto"` uses
    the month before it; pass None to skip the comparison, or an explicit label.
    `category` narrows to one coffee type — the platform_summary view has no category
    column, so that case is computed from the fact table with the same definitions.
    `date` narrows to a single day (period_start); growth is skipped in that case.
    """
    engine = engine or get_engine()
    period = period or latest_period(engine)
    scope = " WHERE period_label = :period" if period else ""
    params = {"period": period} if period else {}

    if date:
        clause, dparams = _scope(category=category, date=date)
        df = _read(engine, PLATFORM_TOTALS_SQL.format(clause=clause), **dparams)
        return _finish_platforms(engine, df, period, date=date)
    if category:
        clause, params = _scope(period, None, category)
        df = _read(engine, PLATFORM_TOTALS_SQL.format(clause=clause), **params)
    else:
        df = _read(engine, "SELECT * FROM platform_summary" + scope, **params)
    if df.empty:
        return df
    # Some exports report impressions but no clicks (Blinkit's keyword, category and
    # product sheets). Averaging CTR/CPC/conversion over partial click data produces
    # numbers that look real and are not, so they are suppressed below 80% coverage.
    cov_clause, cov_params = _scope(period, None, category)
    coverage = _read(engine, f"""
        SELECT platform,
               SUM(CASE WHEN clicks IS NOT NULL THEN spend ELSE 0 END) AS covered,
               SUM(spend) AS total
        FROM performance_metrics{cov_clause} GROUP BY platform""", **cov_params)
    df = df.merge(coverage[["platform", "covered"]], on="platform", how="left")
    df["tracked_spend"] = df["spend"]
    df["tracked_revenue"] = df["revenue"]

    # Billed totals win over summed breakdowns where the exports were incomplete.
    # Not applied to a category slice — the billing figures are whole-platform only.
    if not category:
        df = _apply_overrides(df, period)
    df["overridden"] = df["spend"] != df["tracked_spend"]

    # Two different coverage questions, and conflating them is what produced the
    # contradictory CPCs (₹125 on the KPI card, ₹8 in the platform table):
    #   clicks_coverage — of the spend the exports DO track, how much reports clicks.
    #                     This is the original rule: it decides whether a rate is
    #                     representative enough to show at all.
    #   billed_coverage — how much of the billed total the exports track. Below 1 the
    #                     billed figure comes from the billing dashboard while the
    #                     efficiency metrics can only describe the tracked part.
    df["clicks_coverage"] = df["covered"] / df["tracked_spend"].replace(0, None)
    df["billed_coverage"] = df["tracked_spend"] / df["spend"].replace(0, None)
    # Cost per click is spend ÷ clicks on ONE base. Clicks are tracked-only, so the
    # numerator must be tracked spend too — never the billed override.
    df["cpc"] = df["tracked_spend"] / df["clicks"].replace(0, None)
    partial = df["clicks_coverage"].fillna(0) < 0.8
    df.loc[partial, ["ctr", "cpc", "conv_rate"]] = None
    df = df.drop(columns=["covered"])

    total_revenue = df["revenue"].sum()
    total_spend = df["spend"].sum()
    df["revenue_share"] = df["revenue"] / total_revenue if total_revenue else None
    df["spend_share"] = df["spend"] / total_spend if total_spend else None
    df["period_label"] = period

    # Growth needs a prior month in the database. With one month loaded these stay
    # empty rather than showing a fake 0%.
    baseline = prior_period(engine, period) if compare_to == "auto" else compare_to
    df["compare_to"] = baseline
    for column in ("revenue_growth", "spend_growth", "orders_growth", "roas_change"):
        df[column] = None
    days = period_days(engine, period)
    df["days"] = days
    df["compare_days"] = None
    df["growth_basis"] = None

    if baseline:
        if category:
            prev_clause, prev_params = _scope(baseline, None, category)
            previous = _read(engine, PLATFORM_TOTALS_SQL.format(clause=prev_clause),
                             **prev_params)
        else:
            previous = _read(engine, "SELECT * FROM platform_summary WHERE period_label = :p",
                             p=baseline)
        if not previous.empty:
            baseline_days = period_days(engine, baseline)
            df["compare_days"] = baseline_days
            # Two months of different lengths cannot be compared on totals. August
            # covers 10 days and July 31: on totals revenue "fell" 44%, while the
            # daily rate actually rose 72%. When the spans differ, growth is computed
            # per day and labelled as such rather than quietly misleading.
            uneven = bool(days and baseline_days and
                          abs(days - baseline_days) / max(days, baseline_days) > 0.05)
            scale = (days / baseline_days) if uneven else 1.0
            df["growth_basis"] = "per day" if uneven else "total"

            previous = previous[["platform", "revenue", "spend", "orders", "roas"]].add_prefix("prev_")
            df = df.merge(previous, left_on="platform", right_on="prev_platform", how="left")
            for measure, column in (("revenue", "revenue_growth"), ("spend", "spend_growth"),
                                    ("orders", "orders_growth")):
                # what the earlier month would have produced over this month's span
                before = df[f"prev_{measure}"] * scale
                # A platform absent last month has no growth figure — not +100%.
                df[column] = (df[measure] - before) / before.where(before > 0)
            # ROAS is a ratio, so it needs no length adjustment.
            df["roas_change"] = df["roas"] - df["prev_roas"]
            df = df.drop(columns=["prev_platform"])

    # Partial-total flag: a platform's headline should be its campaign report. When
    # that report is absent the primary grain falls through to product/keyword, so the
    # total under-reports — mark it so the dashboard can say "partial" instead of
    # showing a quietly-low number as if it were complete.
    from etl.signatures import PRIMARY_PRIORITY
    prim_scope = " WHERE is_primary = 1" + (" AND period_label = :period" if period else "")
    prim = _read(engine, f"SELECT platform, report_type FROM performance_metrics{prim_scope}",
                 **({"period": period} if period else {}))
    got = (prim.groupby("platform")["report_type"].apply(set).to_dict()
           if not prim.empty else {})
    df["primary_report"] = df["platform"].map(lambda p: ", ".join(sorted(got.get(p, set()))))
    df["partial"] = df["platform"].map(
        lambda p: bool(PRIMARY_PRIORITY.get(p)) and PRIMARY_PRIORITY[p][0] not in got.get(p, set()))

    df["rank_revenue"] = df["revenue"].rank(ascending=False, method="min").astype(int)
    df["rank_roas"] = df["roas"].rank(ascending=False, method="min")
    return df.sort_values("revenue", ascending=False).reset_index(drop=True)


def overall_kpis(engine=None, period: str | None = None,
                 category: str | None = None, date: str | None = None) -> dict:
    df = platform_comparison(engine, period, category=category, date=date)
    if df.empty:
        return {}
    spend = df["spend"].sum()
    revenue = df["revenue"].sum()
    clicks = df["clicks"].sum()
    impressions = df["impressions"].sum()
    orders = df["orders"].sum()
    tracked_spend = df["tracked_spend"].sum() if "tracked_spend" in df else spend
    # Cost per click must use the same base as the clicks it divides — tracked spend,
    # never the billed override. Using billed spend here is what put ₹125 on the KPI
    # card beside ₹8 in the platform table.
    comparable = bool(df["cpc"].notna().any()) if "cpc" in df else True
    return {
        "spend": spend,
        "revenue": revenue,
        "orders": orders,
        "impressions": impressions,
        "clicks": clicks,
        "roas": revenue / spend if spend else None,
        "roi": (revenue - spend) / spend if spend else None,
        "ctr": clicks / impressions if impressions else None,
        "cpc": (tracked_spend / clicks if clicks else None) if comparable else None,
        "conv_rate": orders / clicks if clicks else None,
        "tracked_spend": tracked_spend,
        "tracked_revenue": df["tracked_revenue"].sum() if "tracked_revenue" in df else revenue,
        "billed_override": bool(df["overridden"].any()) if "overridden" in df else False,
        "billed_coverage": (tracked_spend / spend) if spend else None,
        "platforms": len(df),
        "best_platform": df.iloc[0]["platform"],
        "best_roas_platform": df.sort_values("roas", ascending=False).iloc[0]["platform"],
    }


def _view(engine, view: str, platform: str | None, category: str | None,
          order_by: str = "revenue", period: str | None = "latest",
          date: str | None = None) -> pd.DataFrame:
    engine = engine or get_engine()
    # A specific day is computed from the fact table, not the month-collapsed view.
    if date and view in _DAY_CFG:
        df = day_entity(engine, view, date, platform, category)
        return (df.sort_values(order_by, ascending=False).reset_index(drop=True)
                if not df.empty and order_by in df.columns else df)
    sql = f"SELECT * FROM {view}"
    where, params = [], {}
    # "latest" (the default) scopes to the newest loaded month; None means every
    # month at once, which is only right for explicit cross-period queries.
    if period == "latest":
        period = latest_period(engine)
    if period:
        where.append("period_label = :period")
        params["period"] = period
    if platform:
        where.append("platform = :platform")
        params["platform"] = platform
    if category:
        where.append("category = :category")
        params["category"] = category
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {order_by} DESC"
    return _read(engine, sql, **params)


def campaigns(engine=None, platform=None, category=None,
          period: str | None = "latest", date: str | None = None) -> pd.DataFrame:
    return _view(engine, "campaign_summary", platform, category, period=period, date=date)


def products(engine=None, platform=None, category=None,
          period: str | None = "latest", date: str | None = None) -> pd.DataFrame:
    return _view(engine, "product_summary", platform, category, period=period, date=date)


def keywords(engine=None, platform=None, category=None,
          period: str | None = "latest", date: str | None = None) -> pd.DataFrame:
    return _view(engine, "keyword_summary", platform, category, period=period, date=date)


def cities(engine=None, platform=None, category=None,
          period: str | None = "latest", date: str | None = None) -> pd.DataFrame:
    return _view(engine, "city_summary", platform, category, period=period, date=date)


def categories_for(df: pd.DataFrame) -> list:
    """Coffee categories present, in a stable presentation order."""
    order = ["Instant Coffee", "Filter Coffee", "Cold Coffee"]
    present = [c for c in order if c in set(df["category"].dropna())]
    if df["category"].isna().any():
        present.append(None)
    return present or [None]


SUM_FIELDS = ["impressions", "clicks", "spend", "revenue", "orders", "units", "atc"]
ENTITY_KEYS = {
    "campaign": ["campaign_name"],
    "product": ["product_name"],
    "keyword": ["keyword", "match_type"],
    "city": ["city"],
}


def collapse(df: pd.DataFrame, entity: str, extra_keys: list | None = None) -> pd.DataFrame:
    """One row per entity.

    The views key on sub_platform, so a Zepto city appears once for PLA and once
    for PCA — which reads as a duplicate on a city sheet. Roll those together and
    recompute the ratios from the summed base measures.
    """
    keys = (extra_keys or []) + [k for k in ENTITY_KEYS[entity] if k in df.columns]
    if df.empty or not keys:
        return df

    present = [f for f in SUM_FIELDS if f in df.columns]
    for field in present:
        df[field] = pd.to_numeric(df[field], errors="coerce")
    grouped = df.groupby(keys, dropna=False, as_index=False)[present].sum(min_count=1)

    # carry through descriptive columns that are constant per entity
    for column in ("platform", "category", "product_id", "campaign_name", "ad_type"):
        if column in df.columns and column not in keys:
            first = df.groupby(keys, dropna=False, as_index=False)[column].first()
            grouped = grouped.merge(first, on=keys, how="left")

    grouped["roas"] = grouped["revenue"] / grouped["spend"].replace(0, pd.NA)
    if "clicks" in grouped:
        grouped["ctr"] = grouped["clicks"] / grouped["impressions"].replace(0, pd.NA)
        grouped["cpc"] = grouped["spend"] / grouped["clicks"].replace(0, pd.NA)
        grouped["conv_rate"] = grouped["orders"] / grouped["clicks"].replace(0, pd.NA)
    grouped["cpm"] = grouped["spend"] / grouped["impressions"].replace(0, pd.NA) * 1000
    return grouped.sort_values("revenue", ascending=False, na_position="last")


def wasted_spend(df: pd.DataFrame, min_spend: float = 100.0) -> pd.DataFrame:
    """Rows burning money: real spend, no return."""
    if df.empty:
        return df
    mask = (df["spend"].fillna(0) >= min_spend) & (df["revenue"].fillna(0) <= 0)
    return df[mask].sort_values("spend", ascending=False)


def underperformers(df: pd.DataFrame, min_spend: float = 100.0,
                    roas_floor: float = 1.0) -> pd.DataFrame:
    """Spending above the floor but returning less than break-even."""
    if df.empty:
        return df
    mask = (df["spend"].fillna(0) >= min_spend) & (df["roas"].fillna(0) < roas_floor)
    return df[mask].sort_values("spend", ascending=False)


def scaling_candidates(df: pd.DataFrame, quantile: float = 0.75) -> pd.DataFrame:
    """Strong ROAS on modest spend — the cheapest growth available."""
    if df.empty or df["roas"].dropna().empty:
        return df.head(0)
    roas_cut = df["roas"].quantile(quantile)
    spend_cut = df["spend"].median()
    mask = (df["roas"] >= roas_cut) & (df["spend"] <= spend_cut) & (df["revenue"].fillna(0) > 0)
    return df[mask].sort_values("roas", ascending=False)


# ---------------------------------------------------------------- dashboard views

FUNNEL_STEPS = [("impressions", "Seen"), ("clicks", "Clicked"),
                ("atc", "Added to cart"), ("orders", "Bought")]


def trend(engine=None, platform=None, category=None) -> pd.DataFrame:
    """Revenue/spend/orders per loaded month, normalised to a daily rate.

    The months are different lengths (July 31 days, August 10), so the per-day
    columns are the only ones that can honestly be plotted side by side.
    """
    engine = engine or get_engine()
    clause, params = _scope(platform=platform, category=category)
    df = _read(engine, f"""
        SELECT period_label,
               SUM(impressions) AS impressions, SUM(clicks) AS clicks,
               SUM(spend) AS spend, SUM(revenue) AS revenue,
               SUM(orders) AS orders, SUM(atc) AS atc
        FROM performance_metrics{clause}
        GROUP BY period_label ORDER BY period_label""", **params)
    if df.empty:
        return df
    df["days"] = df["period_label"].map(lambda p: period_days(engine, p) or 1)
    for column in ("revenue", "spend", "orders", "impressions", "clicks"):
        df[f"{column}_per_day"] = df[column] / df["days"]
    df["roas"] = df["revenue"] / df["spend"].where(df["spend"] > 0)
    df["ctr"] = df["clicks"] / df["impressions"].where(df["impressions"] > 0)
    df["conv_rate"] = df["orders"] / df["clicks"].where(df["clicks"] > 0)
    return df


def funnel(engine=None, period=None, platform=None, category=None) -> list[dict]:
    """Seen -> clicked -> added to cart -> bought, with drop-off at each step."""
    engine = engine or get_engine()
    period = period or latest_period(engine)
    clause, params = _scope(period, platform, category)
    df = _read(engine, f"SELECT SUM(spend) AS spend FROM performance_metrics{clause}",
               **params)
    total_spend = float(df.iloc[0]["spend"] or 0) if not df.empty else 0

    # A funnel is only interpretable over rows that report every stage. Amazon ships
    # no add-to-cart, BigBasket and Blinkit no clicks — mixing them produced more
    # purchases than baskets (a "117% conversion"). So the funnel is built from the
    # consistent cohort only, and says which platforms and how much spend that is.
    complete_rows = "clicks IS NOT NULL AND atc IS NOT NULL AND orders IS NOT NULL"
    cohort = _read(engine, f"""
        SELECT SUM(impressions) AS impressions, SUM(clicks) AS clicks,
               SUM(atc) AS atc, SUM(orders) AS orders, SUM(spend) AS spend
        FROM performance_metrics{clause} AND {complete_rows}""", **params)
    included = _read(engine, f"""
        SELECT DISTINCT platform FROM performance_metrics{clause} AND {complete_rows}
        ORDER BY platform""", **params)
    if cohort.empty or not cohort.iloc[0]["impressions"]:
        return []

    row = cohort.iloc[0]
    cohort_spend = float(row["spend"] or 0)
    steps, previous = [], None
    for field, label in FUNNEL_STEPS:
        value = row.get(field)
        value = None if value is None or pd.isna(value) else float(value)
        rate = (value / previous) if value and previous else None
        steps.append({
            "step": label, "field": field, "value": value,
            "of_previous": rate,
            "of_impressions": (value / row["impressions"]) if value and row["impressions"] else None,
            "platforms": included["platform"].tolist(),
            "spend_share": (cohort_spend / total_spend) if total_spend else None,
            # Quick commerce attributes indirect orders — a halo purchase of another
            # SKU — with no ad-driven cart event, so this step can legitimately exceed
            # the one above it. Said plainly instead of quietly capped at 100%.
            "note": ("Exceeds the step above because indirect orders are attributed "
                     "without an ad-driven cart event.") if rate and rate > 1 else None,
        })
        if value:
            previous = value
    return steps


def json_records(frame: pd.DataFrame) -> list[dict]:
    """DataFrame -> JSON-safe records.

    .where(notna, None) leaves a float column float, so the nulls stay NaN and the
    JSON encoder refuses them. Casting to object first is what actually converts.
    """
    if frame is None or frame.empty:
        return []
    return frame.astype(object).where(pd.notna(frame), None).to_dict("records")


def json_scalar(value):
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    try:
        return None if pd.isna(value) else value
    except (TypeError, ValueError):
        return value


def segment(engine=None, category=None, period=None, top=8, platform=None) -> dict:
    """Everything one coffee category needs on a page, optionally for one platform."""
    engine = engine or get_engine()
    period = period or latest_period(engine)
    clause, params = _scope(period, platform, category)
    totals = _read(engine, f"""
        SELECT SUM(impressions) AS impressions, SUM(clicks) AS clicks,
               SUM(spend) AS spend, SUM(revenue) AS revenue,
               SUM(orders) AS orders, SUM(atc) AS atc
        FROM performance_metrics{clause}""", **params)
    summary = {} if totals.empty else {k: json_scalar(v)
                                       for k, v in totals.iloc[0].to_dict().items()}

    def ratio(numerator: str, denominator: str, factor: float = 1.0):
        """Both operands must be real numbers — BigBasket's Cold Coffee has
        impressions but no clicks, so guarding only the denominator is not enough."""
        top, bottom = summary.get(numerator), summary.get(denominator)
        if top is None or not bottom:
            return None
        return top / bottom * factor

    summary["roas"] = ratio("revenue", "spend")
    summary["conv_rate"] = ratio("orders", "clicks")
    summary["cpc"] = ratio("spend", "clicks")
    summary["ctr"] = ratio("clicks", "impressions")

    platforms = _read(engine, f"""
        SELECT platform, SUM(spend) AS spend, SUM(revenue) AS revenue,
               SUM(orders) AS orders
        FROM performance_metrics{clause}
        GROUP BY platform ORDER BY SUM(revenue) DESC""", **params)
    if not platforms.empty:
        platforms["roas"] = platforms["revenue"] / platforms["spend"].where(platforms["spend"] > 0)

    def top_of(fetch, entity):
        frame = fetch(engine, platform=platform, category=category, period=period)
        if frame.empty:
            return []
        return json_records(collapse(frame, entity, ["platform"]).head(top))

    return {
        "category": category, "period": period, "platform": platform,
        "summary": {k: json_scalar(v) for k, v in summary.items()},
        "platforms": json_records(platforms),
        "campaigns": top_of(campaigns, "campaign"),
        "keywords": top_of(keywords, "keyword"),
        "cities": top_of(cities, "city"),
        "products": top_of(products, "product"),
    }


def city_coverage(engine=None, period=None) -> dict:
    """How much of the spend the location analysis can actually see.

    Only Zepto and Instamart report cities; the other four platforms ship no
    location dimension at all, so 'revenue by location' covers part of the business
    and the share is stated rather than implied.
    """
    engine = engine or get_engine()
    period = period or latest_period(engine)
    clause, params = _scope(period)
    total = _read(engine, f"SELECT SUM(spend) AS s, SUM(revenue) AS r "
                          f"FROM performance_metrics{clause}", **params)
    covered = _read(engine, """
        SELECT SUM(spend) AS s, SUM(revenue) AS r,
               COUNT(DISTINCT platform) AS platforms
        FROM performance_metrics
        WHERE city IS NOT NULL AND period_label = :period""", period=period)
    named = _read(engine, """
        SELECT DISTINCT platform FROM performance_metrics
        WHERE city IS NOT NULL AND period_label = :period ORDER BY platform""",
                  period=period)
    total_spend = float(total.iloc[0]["s"] or 0) if not total.empty else 0
    covered_spend = float(covered.iloc[0]["s"] or 0) if not covered.empty else 0
    return {
        "platforms": named["platform"].tolist() if not named.empty else [],
        "spend_share": (covered_spend / total_spend) if total_spend else None,
        "covered_spend": covered_spend, "total_spend": total_spend,
    }
