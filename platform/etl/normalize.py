"""Map a detected Dataset onto the canonical fact schema.

Every number in these exports arrives dirty in a platform-specific way:
  '₹ 3,09,832.39' (Indian lakh grouping)   '29.19%'   'NA'   ''   4.35 (percent)
and CTR is a fraction on Amazon but a percent on Flipkart and BigBasket. The unit
is declared per-signature — it is never guessed from the value's magnitude.
"""
from __future__ import annotations

import re
from typing import Optional

import pandas as pd

from etl.cities import canonical as city_name
from etl.ingest import Dataset

STRING_FIELDS = {
    "campaign_id", "campaign_name", "ad_group", "keyword", "match_type",
    "product_id", "product_name", "city", "placement", "status", "ad_type",
}
DATE_FIELDS = {"date"}
NULLISH = {"", "na", "n/a", "-", "--", "none", "null", "nan"}
_NUM_JUNK = re.compile(r"[₹$,\s ]")

OUTPUT_COLUMNS = [
    "row_index", "platform", "sub_platform", "ad_type", "report_type", "entity_type", "is_primary",
    "campaign_id", "campaign_name", "ad_group", "keyword", "match_type",
    "product_id", "product_name", "city", "placement", "category", "status",
    "date", "period_start", "period_end",
    "impressions", "clicks", "spend", "revenue", "direct_revenue", "indirect_revenue",
    "orders", "units", "atc", "new_users", "budget",
    "ctr", "cpc", "cpm", "roas", "conv_rate",
    "ctr_reported", "cpc_reported", "cpm_reported", "roas_reported",
]


def clean_number(value, is_pct: bool = False) -> Optional[float]:
    """'₹ 3,09,832.39' -> 309832.39 ; '29.19%' -> 0.2919 ; 'NA' -> None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if text.lower() in NULLISH:
        return None
    pct = text.endswith("%")
    text = _NUM_JUNK.sub("", text.rstrip("%"))
    if text in ("", "-", "."):
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    # A missing CPC is not a zero CPC — but a real reported 0 stays 0.
    if pct or is_pct:
        number /= 100.0
    return number


def clean_text(value) -> Optional[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = " ".join(str(value).split())
    return None if text.lower() in NULLISH else text


def _safe_div(num, den, scale: float = 1.0) -> Optional[float]:
    if num is None or den in (None, 0) or pd.isna(den) or pd.isna(num):
        return None
    return float(num) / float(den) * scale


def _infer_category(*texts) -> Optional[str]:
    blob = " ".join(t for t in texts if t).lower()
    if "cold" in blob:
        return "Cold Coffee"
    if "filter" in blob or "roast" in blob or "chicory mix 80" in blob:
        return "Filter Coffee"
    if "instant" in blob or "classic" in blob:
        return "Instant Coffee"
    return None


def normalize(ds: Dataset) -> pd.DataFrame:
    """Dataset -> DataFrame matching performance_metrics (minus file_id/id)."""
    sig, df = ds.signature, ds.df
    if sig is None or df is None or df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    # Group source columns by the canonical field they feed. Several sources on one
    # field (Direct + Indirect Sales) are summed; text fields take the first value.
    buckets: dict[str, list[str]] = {}
    lowered = {" ".join(str(c).strip().lower().split()): c for c in df.columns}
    for source_norm, canonical in sig.colmap.items():
        actual = lowered.get(source_norm)
        if actual is not None:
            buckets.setdefault(canonical, []).append(actual)

    out = pd.DataFrame(index=df.index)
    for canonical, sources in buckets.items():
        if canonical in STRING_FIELDS:
            series = None
            for col in sources:
                cleaned = df[col].map(clean_text)
                series = cleaned if series is None else series.fillna(cleaned)
            if canonical == "city" and series is not None:
                # Zepto writes "chennai" and "Bengaluru", Instamart "Chennai" and
                # "Bangalore". Left as-is one city's revenue is reported two or three
                # times over. See etl/cities.py.
                series = series.map(city_name)
            out[canonical] = series
        elif canonical in DATE_FIELDS:
            out[canonical] = pd.to_datetime(df[sources[0]], errors="coerce").dt.date
        else:
            is_pct = canonical in sig.pct_fields
            total = None
            for col in sources:
                values = df[col].map(lambda v: clean_number(v, is_pct))
                total = values if total is None else total.add(values, fill_value=0)
            out[canonical] = total

    for column in OUTPUT_COLUMNS:
        if column not in out.columns:
            out[column] = None

    # Revenue split -> total, where the platform only reports the parts.
    direct = pd.to_numeric(out["direct_revenue"], errors="coerce")
    indirect = pd.to_numeric(out["indirect_revenue"], errors="coerce")
    parts = direct.fillna(0) + indirect.fillna(0)
    has_parts = direct.notna() | indirect.notna()
    out["revenue"] = out["revenue"].where(out["revenue"].notna(), parts.where(has_parts))

    # Flipkart and Blinkit report units sold, not order counts.
    if sig.orders_from_units:
        out["orders"] = out["orders"].where(out["orders"].notna(), out["units"])

    # Derived metrics recomputed from base measures so platforms are comparable.
    out["ctr"] = [_safe_div(c, i) for c, i in zip(out["clicks"], out["impressions"])]
    out["cpc"] = [_safe_div(s, c) for s, c in zip(out["spend"], out["clicks"])]
    out["cpm"] = [_safe_div(s, i, 1000.0) for s, i in zip(out["spend"], out["impressions"])]
    out["roas"] = [_safe_div(r, s) for r, s in zip(out["revenue"], out["spend"])]
    out["conv_rate"] = [_safe_div(o, c) for o, c in zip(out["orders"], out["clicks"])]

    # Grain / provenance
    out["platform"] = sig.platform
    out["report_type"] = sig.report_type
    out["entity_type"] = sig.entity_type
    out["is_primary"] = False  # set after ingestion, once we know what the feed contains
    out["sub_platform"] = ds.sub_platform
    if sig.ad_type:
        out["ad_type"] = out["ad_type"].where(out["ad_type"].notna(), sig.ad_type)
    if ds.campaign_name_hint:
        out["campaign_name"] = out["campaign_name"].where(
            out["campaign_name"].notna(), ds.campaign_name_hint)

    out["category"] = [
        ds.category or _infer_category(cn, pn, kw)
        for cn, pn, kw in zip(out["campaign_name"], out["product_name"], out["keyword"])
    ]

    period_start, period_end = ds.period_start, ds.period_end
    dates = pd.Series([d for d in out["date"] if d is not None])
    if period_start is None and not dates.empty:
        period_start, period_end = dates.min(), dates.max()
    out["period_start"] = period_start
    out["period_end"] = period_end
    out["row_index"] = range(len(out))

    return out[OUTPUT_COLUMNS]
