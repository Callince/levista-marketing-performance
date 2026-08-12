"""Rule-based executive intelligence: what happened, why, what to do next.

Deliberately deterministic rather than an LLM call — the same data must produce
the same board pack every month, it has to be explainable to a category manager,
and it costs nothing to re-run. Language is plain business English, no jargon.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import delete, insert, select

import config
from analytics import metrics
from db.models import alerts, anomalies, get_engine, insights, recommendations, uploaded_files

# What a complete monthly feed looks like. Anything missing becomes a data-gap alert
# and a "No source data" banner on the matching Excel sheet.
EXPECTED_REPORTS = {
    "Amazon": {"campaign", "product", "keyword"},
    "Flipkart": {"campaign", "product", "keyword"},
    "Instamart": {"campaign", "product", "city", "keyword"},
    "Zepto": {"campaign", "product", "keyword", "city"},
    "BigBasket": {"product", "keyword"},
    "Blinkit": {"product", "keyword"},
}


def inr(value) -> str:
    """Indian-format rupees: 454747 -> '₹4,54,747'."""
    if value is None or pd.isna(value):
        return "—"
    value = round(float(value))
    sign, digits = ("-", str(abs(value))) if value < 0 else ("", str(value))
    if len(digits) <= 3:
        return f"{sign}₹{digits}"
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return f"{sign}₹{','.join(parts)},{tail}"


def pct(value) -> str:
    return "—" if value is None or pd.isna(value) else f"{float(value) * 100:.2f}%"


# A keyword row also carries its campaign name, so the entity's own field has to
# win — otherwise every keyword recommendation is labelled with its campaign.
_LABEL_FIELDS = {
    "keyword": ("keyword", "campaign_name"),
    "product": ("product_name", "product_id", "campaign_name"),
    "city": ("city", "campaign_name"),
    "campaign": ("campaign_name",),
}


def _label(row, entity_type: str | None = None) -> str:
    fields = _LABEL_FIELDS.get(entity_type or "", ())
    for field in (*fields, "campaign_name", "product_name", "keyword", "city"):
        if field in row and pd.notna(row.get(field)):
            return str(row[field])
    return "(unnamed)"


# ---------------------------------------------------------------- narrative

def platform_narratives(engine) -> list[dict]:
    """One what/why/next story per platform, in business language."""
    table = metrics.platform_comparison(engine)
    if table.empty:
        return []

    median_ctr = table["ctr"].median()
    median_conv = table["conv_rate"].median()
    median_cpc = table["cpc"].median()
    out = []

    for _, row in table.iterrows():
        platform, roas = row["platform"], row["roas"]
        share = row["revenue_share"]

        happened = (
            f"{platform} spent {inr(row['spend'])} and brought in {inr(row['revenue'])} "
            f"from {int(row['orders'] or 0):,} orders. That is ₹{roas:.2f} back for every "
            f"₹1 spent, and {pct(share)} of all revenue across platforms."
        )

        reasons = []
        if pd.notna(row["ctr"]) and pd.notna(median_ctr):
            if row["ctr"] < median_ctr * 0.7:
                reasons.append(
                    f"shoppers click the ads far less often here ({pct(row['ctr'])} versus "
                    f"{pct(median_ctr)} typical), so the listing or the keywords are not matching "
                    "what people are searching for")
            elif row["ctr"] > median_ctr * 1.3:
                reasons.append(
                    f"the ads attract clicks unusually well ({pct(row['ctr'])} versus "
                    f"{pct(median_ctr)} typical), so visibility is working")
        if pd.notna(row["conv_rate"]) and pd.notna(median_conv):
            if row["conv_rate"] < median_conv * 0.7:
                reasons.append(
                    "shoppers who click are not buying — usually a price, rating, image or "
                    "out-of-stock problem on the product page")
            elif row["conv_rate"] > median_conv * 1.3:
                reasons.append("shoppers who click buy readily, so the product pages convert well")
        if pd.notna(row["cpc"]) and pd.notna(median_cpc) and row["cpc"] > median_cpc * 1.3:
            reasons.append(
                f"each click costs more than elsewhere ({inr(row['cpc'])} versus "
                f"{inr(median_cpc)} typical), which eats into the return")
        if pd.isna(row.get("ctr")) and pd.isna(row.get("cpc")):
            reasons.append("this platform's export does not report clicks for most of its "
                           "spend, so click-through and cost-per-click cannot be compared "
                           "against the other platforms")
        elif not reasons:
            reasons.append("click rates, conversion and click costs are all close to the "
                           "average across platforms, so performance is being driven by "
                           "budget size rather than efficiency")

        if roas is None or pd.isna(roas):
            action = "Confirm revenue tracking is switched on — no return figures came through."
        elif roas < config.BREAKEVEN_ROAS:
            action = (f"Money is being lost here: {inr(row['spend'])} of spend returned only "
                      f"{inr(row['revenue'])}. Pause the weakest campaigns, cut bids on the "
                      "keywords with spend but no sales, and hold budget until the return "
                      "passes ₹1 per ₹1 spent.")
        elif roas < config.HEALTHY_ROAS:
            action = ("Keep the budget flat and fix efficiency first — trim the keywords that "
                      "spend without converting and shift that money to the best sellers.")
        else:
            action = (f"This is the strongest use of budget available. Increase spend here and "
                      f"extend the winning campaigns to more products.")

        out.append({
            "platform": platform,
            "scope": "platform",
            "what_happened": happened,
            "why_it_happened": "Because " + "; and ".join(reasons) + ".",
            "what_to_do_next": action,
        })
    return out


# ---------------------------------------------------------------- recommendations

def _priority(impact: float | None) -> str:
    """Rank by the money at stake.

    A priority column where every row says High tells nobody what to do first, so
    the band comes from the rupees involved rather than from which rule fired.
    """
    amount = abs(impact or 0)
    if amount >= config.HIGH_IMPACT:
        return "High"
    if amount >= config.MEDIUM_IMPACT:
        return "Medium"
    return "Low"


def entity_recommendations(engine) -> list[dict]:
    recs = []
    sources = [
        ("campaign", metrics.campaigns(engine)),
        ("product", metrics.products(engine)),
        ("keyword", metrics.keywords(engine)),
        ("city", metrics.cities(engine)),
    ]
    for entity_type, table in sources:
        if table.empty:
            continue
        for platform, group in table.groupby("platform"):
            for _, row in metrics.wasted_spend(group, config.MIN_SPEND_FOR_ALERT).head(15).iterrows():
                recs.append(dict(
                    platform=platform, entity_type=entity_type, entity_name=_label(row, entity_type),
                    action="Pause", priority=_priority(row["spend"]),
                    impact_value=row["spend"],
                    rationale=(f"{inr(row['spend'])} spent with no sales at all. "
                               "Pausing this frees the budget immediately with nothing lost."),
                ))
            for _, row in metrics.underperformers(group, config.MIN_SPEND_FOR_ALERT).head(15).iterrows():
                if (row["revenue"] or 0) <= 0:
                    continue  # already covered by the wasted-spend rule above
                recs.append(dict(
                    platform=platform, entity_type=entity_type, entity_name=_label(row, entity_type),
                    action="Reduce spend",
                    priority=_priority((row["spend"] or 0) - (row["revenue"] or 0)),
                    impact_value=(row["spend"] or 0) - (row["revenue"] or 0),
                    rationale=(f"Returns ₹{row['roas']:.2f} for every ₹1 spent, so every rupee "
                               f"here loses money. {inr(row['spend'])} spent, {inr(row['revenue'])} "
                               "earned."),
                ))
            for _, row in metrics.scaling_candidates(group).head(10).iterrows():
                recs.append(dict(
                    platform=platform, entity_type=entity_type, entity_name=_label(row, entity_type),
                    action="Increase budget", priority=_priority(row["revenue"]),
                    impact_value=row["revenue"],
                    rationale=(f"Returns ₹{row['roas']:.2f} per ₹1 spent on only "
                               f"{inr(row['spend'])} of budget — the cheapest growth available."),
                ))
            if entity_type == "keyword" and "ctr" in group:
                seen = group[(group["impressions"].fillna(0) > 1000) & group["ctr"].notna()]
                # The 20th percentile across all keywords is 0.00 whenever plenty of
                # them got no clicks, and "ctr < 0" matches nothing. Take the
                # percentile over keywords that did earn a click, and treat a
                # well-shown keyword with zero clicks as the worst case outright.
                clicked = seen.loc[seen["ctr"] > 0, "ctr"]
                floor = clicked.quantile(0.2) if len(clicked) >= 5 else 0.0
                weak = seen[(seen["ctr"] == 0) | (seen["ctr"] < floor)]
                weak = weak.sort_values("impressions", ascending=False)
                for _, row in weak.head(10).iterrows():
                    recs.append(dict(
                        platform=platform, entity_type=entity_type, entity_name=_label(row, entity_type),
                        action="Improve keyword", priority=_priority(row["spend"]),
                        impact_value=row["spend"],
                        rationale=(f"Shown {int(row['impressions']):,} times but barely clicked "
                                   f"({pct(row['ctr'])}). The keyword is not matching shopper "
                                   "intent — narrow the match type or replace it."),
                    ))
    return recs


# ---------------------------------------------------------------- alerts + anomalies

def build_alerts(engine) -> list[dict]:
    out = []
    table = metrics.platform_comparison(engine)

    # Comparing months of different lengths is the easiest way to draw exactly the
    # wrong conclusion, so it is stated as an alert rather than left in a footnote.
    if not table.empty and table["compare_to"].iloc[0]:
        days = table["days"].iloc[0]
        before = table["compare_days"].iloc[0]
        if table["growth_basis"].iloc[0] == "per day":
            out.append(dict(
                platform="All", severity="Medium", alert_type="Uneven periods",
                entity_name=f"{table['period_label'].iloc[0]} vs {table['compare_to'].iloc[0]}",
                value=None,
                message=(
                    f"This period covers {days} days and the one it is compared with covers "
                    f"{before}. All growth figures are therefore per day, not totals — on raw "
                    f"totals the shorter period would look far worse than it is.")))
    for _, row in table.iterrows():
        if pd.notna(row["roas"]) and row["roas"] < config.BREAKEVEN_ROAS:
            out.append(dict(
                platform=row["platform"], severity="High", alert_type="Losing money",
                entity_name=row["platform"], value=row["roas"],
                message=(f"{row['platform']} is below break-even: {inr(row['spend'])} spent "
                         f"returned {inr(row['revenue'])} (₹{row['roas']:.2f} per ₹1)."),
            ))

    for entity_type, data in (("campaign", metrics.campaigns(engine)),
                              ("keyword", metrics.keywords(engine)),
                              ("product", metrics.products(engine))):
        if data.empty:
            continue
        leak = metrics.wasted_spend(data, config.MIN_SPEND_FOR_ALERT)
        if not leak.empty:
            out.append(dict(
                platform="All", severity="High", alert_type="Budget leakage",
                entity_name=f"{len(leak)} {entity_type}s", value=leak["spend"].sum(),
                message=(f"{inr(leak['spend'].sum())} went to {len(leak)} {entity_type}s that "
                         "produced no sales at all."),
            ))

    # Data-gap alerts: what the feed should have contained but didn't. Scoped to the
    # month being reported — an earlier month having supplied a report says nothing
    # about whether this month's feed did.
    current = metrics.latest_period(engine)
    with engine.connect() as conn:
        query = (select(uploaded_files.c.platform, uploaded_files.c.report_type)
                 .where(uploaded_files.c.processing_status == "ok"))
        if current:
            query = query.where(uploaded_files.c.period_label == current)
        loaded = conn.execute(query).all()
    have: dict[str, set] = {}
    for platform, report_type in loaded:
        have.setdefault(platform, set()).add(report_type)
    for platform, expected in EXPECTED_REPORTS.items():
        missing = expected - have.get(platform, set())
        for report_type in sorted(missing):
            out.append(dict(
                platform=platform, severity="Medium", alert_type="Missing report",
                entity_name=f"{platform} {report_type} report", value=None,
                message=(f"No {platform} {report_type} report was found in this month's files, "
                         f"so the {platform} {report_type} analysis could not be produced."),
            ))
    return out


def build_anomalies(engine) -> list[dict]:
    """Outliers within each platform+entity cohort.

    # ponytail: z-score across the current period's cohort, not a time series.
    # Upgrade to a rolling window once three or more months are loaded.
    """
    out = []
    for entity_type, table in (("campaign", metrics.campaigns(engine)),
                               ("product", metrics.products(engine)),
                               ("keyword", metrics.keywords(engine))):
        if table.empty:
            continue
        for (platform,), group in table.groupby(["platform"]):
            if len(group) < 5:
                continue
            for metric in ("spend", "roas"):
                values = pd.to_numeric(group[metric], errors="coerce")
                mean, std = values.mean(), values.std()
                if not std or pd.isna(std):
                    continue
                z = (values - mean) / std
                for idx in z[abs(z) >= 2.5].index:
                    out.append(dict(
                        platform=platform, entity_type=entity_type,
                        entity_name=_label(group.loc[idx], entity_type), metric=metric,
                        value=float(values[idx]), cohort_mean=float(mean),
                        z_score=float(z[idx]),
                        direction="above" if z[idx] > 0 else "below",
                    ))
    return out


# ---------------------------------------------------------------- persistence

def _native(rows: list[dict]) -> list[dict]:
    """Plain Python values for the driver.

    These dicts are built straight from DataFrame.iterrows(), so their numbers are
    numpy scalars. psycopg2 has no adapter for np.float64 and stringifies it into
    the SQL as 'np.float64(...)', which Postgres reads as a schema reference;
    SQLite's converter accepted them, so this only appears on Postgres.
    (etl/load.py avoids it a different way, via .astype(object).)
    """
    def clean(value):
        if hasattr(value, "item"):          # numpy scalar -> int/float/bool
            value = value.item()
        try:
            return None if pd.isna(value) else value
        except (TypeError, ValueError):     # not a scalar pandas understands
            return value

    return [{k: clean(v) for k, v in row.items()} for row in rows]


def generate(engine=None) -> dict:
    engine = engine or get_engine()
    period_start, period_end = metrics.reporting_period(engine)
    now = datetime.now()

    narratives = platform_narratives(engine)
    recs = entity_recommendations(engine)
    alert_rows = build_alerts(engine)
    anomaly_rows = build_anomalies(engine)

    with engine.begin() as conn:
        for table in (insights, recommendations, alerts, anomalies):
            conn.execute(delete(table))
        if narratives:
            conn.execute(insert(insights), _native([
                {**n, "period_start": period_start, "period_end": period_end,
                 "generated_at": now} for n in narratives]))
        if recs:
            conn.execute(insert(recommendations),
                         _native([{**r, "generated_at": now} for r in recs]))
        if alert_rows:
            conn.execute(insert(alerts),
                         _native([{**a, "generated_at": now} for a in alert_rows]))
        if anomaly_rows:
            conn.execute(insert(anomalies),
                         _native([{**a, "generated_at": now} for a in anomaly_rows]))

    return {"insights": len(narratives), "recommendations": len(recs),
            "alerts": len(alert_rows), "anomalies": len(anomaly_rows)}


PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def load(engine, table) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(select(table), conn)


if __name__ == "__main__":
    print(generate())


# ---------------------------------------------------------------- highlights

def _best_worst(frame, label_field, min_spend=None):
    """Top and bottom by return, ignoring rows too small to judge."""
    if frame.empty:
        return None, None
    frame = frame.copy()
    frame["spend"] = pd.to_numeric(frame["spend"], errors="coerce").fillna(0)
    frame["roas"] = pd.to_numeric(frame["roas"], errors="coerce")
    judged = frame[frame["spend"] >= (min_spend or config.MIN_SPEND_FOR_ALERT)]
    if judged.empty:
        return None, None
    best = judged.sort_values("roas", ascending=False).iloc[0]
    worst = judged.sort_values("roas", na_position="last").iloc[0]

    def pack(row):
        return {"name": row.get(label_field), "platform": row.get("platform"),
                "revenue": row.get("revenue"), "spend": row.get("spend"),
                "roas": row.get("roas"), "orders": row.get("orders")}

    return pack(best), pack(worst)


def highlights(engine=None, period: str | None = None) -> dict:
    """The answers the dashboard exists to give, in one payload.

    Product / platform / location / keyword: who is winning, who is losing, and
    where the next rupee should go.
    """
    engine = engine or get_engine()
    period = period or metrics.latest_period(engine)
    table = metrics.platform_comparison(engine, period)

    products = metrics.collapse(metrics.products(engine, period=period), "product", ["platform"])
    keywords = metrics.collapse(metrics.keywords(engine, period=period), "keyword", ["platform"])
    cities = metrics.collapse(metrics.cities(engine, period=period), "city", ["platform"])

    out = {"period": period, "product": {}, "platform": {}, "location": {}, "keyword": {}}

    if not products.empty:
        total = products["revenue"].sum()
        top = products.sort_values("revenue", ascending=False).iloc[0]
        best, worst = _best_worst(products, "product_name")
        out["product"] = {
            "highest_revenue": {"name": top["product_name"], "platform": top["platform"],
                                "revenue": top["revenue"],
                                "share": (top["revenue"] / total) if total else None},
            "best_return": best, "worst_return": worst,
            "count": int(len(products)),
        }

    if not table.empty:
        by_roas = table.sort_values("roas", ascending=False)
        with_cpc = table[table["cpc"].notna()]
        with_conv = table[table["conv_rate"].notna()]
        out["platform"] = {
            "highest_revenue": {"name": table.iloc[0]["platform"],
                                "revenue": table.iloc[0]["revenue"],
                                "share": table.iloc[0]["revenue_share"]},
            "highest_roas": {"name": by_roas.iloc[0]["platform"], "roas": by_roas.iloc[0]["roas"]},
            "lowest_roas": {"name": by_roas.iloc[-1]["platform"], "roas": by_roas.iloc[-1]["roas"]},
            "lowest_cpc": ({"name": with_cpc.sort_values("cpc").iloc[0]["platform"],
                            "cpc": with_cpc.sort_values("cpc").iloc[0]["cpc"]}
                           if not with_cpc.empty else None),
            "highest_conversion": ({"name": with_conv.sort_values("conv_rate", ascending=False).iloc[0]["platform"],
                                    "conv_rate": with_conv.sort_values("conv_rate", ascending=False).iloc[0]["conv_rate"]}
                                   if not with_conv.empty else None),
            # Stated because four of the six platforms report no clicks for most of
            # their spend, so CPC and conversion rankings cover part of the business.
            "cpc_coverage": int(len(with_cpc)), "platform_count": int(len(table)),
        }

    coverage = metrics.city_coverage(engine, period)
    if not cities.empty:
        total = cities["revenue"].sum()
        top = cities.sort_values("revenue", ascending=False).iloc[0]
        best, worst = _best_worst(cities, "city")
        out["location"] = {
            "highest_revenue": {"name": top["city"], "platform": top["platform"],
                                "revenue": top["revenue"],
                                "share": (top["revenue"] / total) if total else None},
            "best_return": best, "worst_return": worst,
            "count": int(len(cities)), "coverage": coverage,
        }
    else:
        out["location"] = {"coverage": coverage}

    if not keywords.empty:
        spending = keywords[pd.to_numeric(keywords["spend"], errors="coerce").fillna(0)
                            >= config.MIN_SPEND_FOR_ALERT]
        converting = keywords[pd.to_numeric(keywords["orders"], errors="coerce").fillna(0) > 0]
        wasted = metrics.wasted_spend(keywords, config.MIN_SPEND_FOR_ALERT)
        best, worst = _best_worst(keywords, "keyword")
        # Big spend, poor return: the clearest place to stop losing money.
        leaking = spending[pd.to_numeric(spending["roas"], errors="coerce").fillna(0)
                           < config.BREAKEVEN_ROAS].sort_values("spend", ascending=False)
        out["keyword"] = {
            "top_converting": converting.sort_values("orders", ascending=False)
                              .head(5)[["keyword", "platform", "orders", "roas"]]
                              .to_dict("records"),
            "high_spend_low_conversion": leaking.head(5)[["keyword", "platform", "spend", "roas"]]
                                         .to_dict("records"),
            "opportunities": (spending.sort_values("roas", ascending=False)
                              .head(5)[["keyword", "platform", "spend", "roas"]]
                              .to_dict("records")),
            "wasted_spend": float(wasted["spend"].sum()) if not wasted.empty else 0.0,
            "wasted_count": int(len(wasted)),
            "best_return": best, "worst_return": worst,
        }

    return _json_safe(out)


def _json_safe(value):
    """numpy/pandas scalars and NaN -> plain JSON types."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):
        value = value.item()
    try:
        return None if pd.isna(value) else value
    except (TypeError, ValueError):
        return value
