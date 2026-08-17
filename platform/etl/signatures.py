"""Column-signature registry — the heart of platform/report-type detection.

Folder names in the source exports are demonstrably unreliable (a file under
``Zepto\\PLA\\keywords performance`` is a *product* report; a file under
``BigBasket\\product performance`` is a *Zepto city* report). So detection reads
the columns, never the path. The path contributes only the coffee-category hint,
which genuinely is not present inside the files.

Adding support for a new export = adding one Signature below. Nothing else changes.
"""
from dataclasses import dataclass, field
from typing import Optional

# Canonical fields a signature may map onto. Anything not listed stays in raw_records.
CANONICAL = {
    "campaign_id", "campaign_name", "ad_group", "keyword", "match_type",
    "product_id", "product_name", "city", "placement", "status", "date",
    "impressions", "clicks", "spend", "revenue", "direct_revenue",
    "indirect_revenue", "orders", "units", "atc", "new_users", "budget",
    "ctr_reported", "cpc_reported", "cpm_reported", "roas_reported",
}


def norm(col) -> str:
    """Normalize a raw column header for matching."""
    return " ".join(str(col).strip().lower().split())


@dataclass(frozen=True)
class Signature:
    key: str
    platform: str
    report_type: str
    entity_type: str
    required: frozenset          # normalized column names that MUST all be present
    colmap: dict                 # normalized source column -> canonical field
    pct_fields: frozenset = frozenset()   # canonical fields arriving as 0-100 percent
    ad_type: Optional[str] = None
    # BigBasket product exports carry the campaign name alone in the row above the header
    campaign_name_above_header: bool = False
    # Platforms that report units sold but not order counts
    orders_from_units: bool = False

    def score(self, cols: set) -> float:
        """1.0 only if every required column is present; else 0."""
        return 1.0 if self.required <= cols else 0.0

    def specificity(self, cols: set) -> int:
        """Tie-break: prefer the signature that explains the most of this file."""
        return len(self.required) * 100 + len(set(self.colmap) & cols)


def _m(**kw):
    """colmap helper: canonical=source_column(s). Multiple sources are summed."""
    out = {}
    for canonical, sources in kw.items():
        for s in (sources if isinstance(sources, (list, tuple)) else [sources]):
            out[norm(s)] = canonical
    return out


SIGNATURES: list[Signature] = [
    # ---------------- Amazon ----------------
    Signature(
        key="amazon_campaign", platform="Amazon", report_type="campaign",
        entity_type="campaign", ad_type="Sponsored Product",
        required=frozenset({"campaign name", "impressions", "total cost", "purchases", "sales", "roas"}),
        colmap=_m(
            campaign_name="Campaign name", status="Status", impressions="Impressions",
            clicks="Clicks", ctr_reported="CTR", spend="Total cost", cpc_reported="CPC",
            orders="Purchases", revenue="Sales", roas_reported="ROAS",
            cpm_reported="CPM", budget="Campaign budget amount",
        ),
    ),
    Signature(
        key="amazon_product", platform="Amazon", report_type="product",
        entity_type="product", ad_type="Sponsored Product",
        required=frozenset({"ad name", "asin", "impressions", "total cost (inr)", "sales (inr)"}),
        colmap=_m(
            product_name="Ad name", product_id="ASIN", status="State",
            impressions="Impressions", clicks="Clicks", ctr_reported="CTR",
            spend="Total cost (INR)", cpc_reported="CPC (INR)", orders="Purchases",
            revenue="Sales (INR)", roas_reported="ROAS",
        ),
    ),

    # ---------------- Flipkart ----------------
    Signature(
        key="flipkart_keyword", platform="Flipkart", report_type="keyword",
        entity_type="keyword", orders_from_units=True,
        required=frozenset({"attributed_keyword", "keyword_match_type", "ad spend", "direct revenue"}),
        colmap=_m(
            campaign_id="Campaign ID", campaign_name="Campaign Name", ad_group="AdGroup ID",
            keyword="attributed_keyword", match_type="keyword_match_type",
            impressions="Views", clicks="Clicks", spend="Ad spend",
            units=["Direct Units Sold", "Indirect Units Sold"],
            direct_revenue="Direct Revenue", indirect_revenue="Indirect Revenue",
            roas_reported="ROI", cpc_reported="Average CPC",
            ctr_reported="Click Through Rate in %",
        ),
        pct_fields=frozenset({"ctr_reported"}),
    ),
    Signature(
        key="flipkart_placement", platform="Flipkart", report_type="placement",
        entity_type="placement", orders_from_units=True,
        required=frozenset({"placement", "banner_group_spend", "total revenue"}),
        colmap=_m(
            campaign_name="campaign_name", ad_group="ad_group_name", placement="placement",
            spend="banner_group_spend", impressions="views", clicks="clicks",
            cpc_reported="average_cpc", ctr_reported="CTR", atc="DIRECT ATC",
            units=["DIRECT UNITS", "INDIRECT UNITS"], revenue="Total Revenue",
            direct_revenue="DIRECT REVENUE", indirect_revenue="INDIRECT REVENUE",
        ),
        pct_fields=frozenset({"ctr_reported"}),
    ),
    Signature(
        key="flipkart_product", platform="Flipkart", report_type="product",
        entity_type="product", orders_from_units=True,
        required=frozenset({"advertised fsn id", "advertised product name", "ad spend"}),
        colmap=_m(
            campaign_id="Campaign ID", campaign_name="Campaign Name", ad_group="AdGroup Name",
            product_id="Advertised FSN ID", product_name="Advertised Product Name",
            impressions="Views", clicks="Clicks", ctr_reported="CTR", spend="Ad Spend",
            units=["Units Sold (Direct)", "Units Sold (Indirect)"],
            direct_revenue="Direct Revenue", indirect_revenue="Indirect Revenue",
            roas_reported="ROI (Direct)",
        ),
        pct_fields=frozenset({"ctr_reported"}),
    ),
    Signature(
        # Flipkart Minutes ships a different product export: FSN ID instead of
        # Advertised FSN ID, and Actions/Action Rate in place of Clicks/CTR.
        key="flipkart_product_minutes", platform="Flipkart", report_type="product",
        entity_type="product", orders_from_units=True,
        required=frozenset({"fsn id", "product name", "ad spend", "actions", "action rate"}),
        colmap=_m(
            campaign_id="Campaign ID", campaign_name="Campaign Name", ad_group="AdGroup Name",
            product_id="FSN ID", product_name="Product Name",
            impressions="Views", clicks="Actions", ctr_reported="Action Rate", spend="Ad Spend",
            units=["Units Sold (Direct)", "Units Sold (Indirect)"],
            direct_revenue="Direct Revenue", indirect_revenue="Indirect Revenue",
            roas_reported="ROI (Direct)",
        ),
        pct_fields=frozenset({"ctr_reported"}),
    ),
    Signature(
        key="flipkart_campaign", platform="Flipkart", report_type="campaign",
        entity_type="campaign", orders_from_units=True,
        required=frozenset({"campaign id", "ad spends", "total revenue", "total units sold"}),
        colmap=_m(
            campaign_id="Campaign ID", campaign_name="Name", ad_type="Campaign Type",
            status="campaign_status", budget="Campaign Allocated Budget", spend="Ad Spends",
            impressions="Views", clicks="Clicks", units="Total Units Sold",
            revenue="Total Revenue", roas_reported="ROI", ctr_reported="CTR",
        ),
    ),
    Signature(
        # Flipkart PCA product report: fsn_id/fsn_name product grain with converted
        # revenue and units, but NO ad-spend column (PCA product exports omit spend).
        # Minutes files carry two Start/End-Time preamble rows before this header;
        # _find_header skips them by scanning for the row that matches this signature.
        key="flipkart_product_pca", platform="Flipkart", report_type="product",
        entity_type="product", ad_type="PCA", orders_from_units=True,
        required=frozenset({"fsn_id", "fsn_name", "click_total_converted_revenue", "direct revenue"}),
        colmap=_m(
            campaign_id="campaign_id", campaign_name="campaign_name", date="Date",
            product_id="fsn_id", product_name="fsn_name",
            units=["DIRECT UNITS", "INDIRECT UNITS"], revenue="click_total_converted_revenue",
            direct_revenue="DIRECT REVENUE", indirect_revenue="INDIRECT REVENUE",
        ),
    ),

    # ---------------- Instamart ----------------
    # city / product signatures carry more required columns, so they out-rank the
    # campaign signature on the files that are actually city/product breakdowns.
    Signature(
        # Instamart's most granular export: one row per date x campaign x keyword x
        # product x city. It satisfies instamart_city too (every row has a CITY), and
        # matching that way is how a keyword report came to be filed as a city report.
        # Being stricter (KEYWORD + MATCH_TYPE) makes this win on specificity.
        #
        # Only the keyword dimension is mapped, deliberately. City and product are in
        # the file, but Instamart also ships dedicated city and product reports for the
        # same days — mapping them here would count those days twice in the city and
        # product breakdowns (it inflated Instamart's city spend by 9%). Keywords are
        # the one dimension no other Instamart export provides.
        key="instamart_keyword", platform="Instamart", report_type="keyword",
        entity_type="keyword",
        required=frozenset({"campaign_id", "keyword", "match_type", "total_impressions",
                            "total_budget_burnt", "total_gmv"}),
        colmap=_m(
            campaign_id="CAMPAIGN_ID", campaign_name="CAMPAIGN_NAME", status="CAMPAIGN_STATUS",
            keyword="KEYWORD", match_type="MATCH_TYPE", date="METRICS_DATE",
            impressions="TOTAL_IMPRESSIONS", spend="TOTAL_BUDGET_BURNT",
            budget="TOTAL_BUDGET", clicks="TOTAL_CLICKS", ctr_reported="TOTAL_CTR",
            atc="TOTAL_A2C", revenue="TOTAL_GMV", orders="TOTAL_CONVERSIONS",
            roas_reported="TOTAL_ROI", cpm_reported="eCPM",
        ),
        pct_fields=frozenset({"ctr_reported"}),
    ),
    Signature(
        key="instamart_city", platform="Instamart", report_type="city", entity_type="city",
        required=frozenset({"campaign_id", "city", "total_impressions", "total_budget_burnt", "total_gmv"}),
        colmap=_m(
            campaign_id="CAMPAIGN_ID", campaign_name="CAMPAIGN_NAME", status="CAMPAIGN_STATUS",
            city="CITY", impressions="TOTAL_IMPRESSIONS", spend="TOTAL_BUDGET_BURNT",
            budget="TOTAL_BUDGET", clicks="TOTAL_CLICKS", ctr_reported="TOTAL_CTR",
            atc="TOTAL_A2C", revenue="TOTAL_GMV", orders="TOTAL_CONVERSIONS",
            roas_reported="TOTAL_ROI", cpm_reported="eCPM",
        ),
        pct_fields=frozenset({"ctr_reported"}),
    ),
    Signature(
        key="instamart_product", platform="Instamart", report_type="product", entity_type="product",
        required=frozenset({"campaign_id", "product_id", "product_name", "total_impressions", "total_gmv"}),
        colmap=_m(
            campaign_id="CAMPAIGN_ID", campaign_name="CAMPAIGN_NAME", status="CAMPAIGN_STATUS",
            product_id="PRODUCT_ID", product_name="PRODUCT_NAME",
            impressions="TOTAL_IMPRESSIONS", spend="TOTAL_BUDGET_BURNT", budget="TOTAL_BUDGET",
            clicks="TOTAL_CLICKS", ctr_reported="TOTAL_CTR", atc="TOTAL_A2C",
            revenue="TOTAL_GMV", orders="TOTAL_CONVERSIONS", roas_reported="TOTAL_ROI",
            cpm_reported="eCPM",
        ),
        pct_fields=frozenset({"ctr_reported"}),
    ),
    Signature(
        key="instamart_campaign", platform="Instamart", report_type="campaign", entity_type="campaign",
        required=frozenset({"campaign_id", "campaign_name", "total_impressions", "total_budget_burnt", "total_gmv"}),
        colmap=_m(
            campaign_id="CAMPAIGN_ID", campaign_name="CAMPAIGN_NAME", status="CAMPAIGN_STATUS",
            impressions="TOTAL_IMPRESSIONS", spend="TOTAL_BUDGET_BURNT", budget="TOTAL_BUDGET",
            clicks="TOTAL_CLICKS", ctr_reported="TOTAL_CTR", atc="TOTAL_A2C",
            revenue="TOTAL_GMV", orders="TOTAL_CONVERSIONS", roas_reported="TOTAL_ROI",
            cpm_reported="eCPM",
        ),
        pct_fields=frozenset({"ctr_reported"}),
    ),

    # ---------------- Zepto (PLA carries Cpc, PCA does not) ----------------
    Signature(
        key="zepto_campaign_pla", platform="Zepto", report_type="campaign",
        entity_type="campaign", ad_type="PLA",
        required=frozenset({"campaignname", "campaigntype", "daily_budget", "spend", "revenue", "cpc"}),
        # CampaignType holds Zepto's bid strategy (AUCTION_UP_SELL, …), not PLA/PCA, so
        # it is NOT mapped to ad_type — the signature's ad_type="PLA" stands. It stays in raw_records.
        colmap=_m(
            campaign_name="CampaignName", status="Status",
            atc="Atc", clicks="Clicks", cpc_reported="Cpc", cpm_reported="Cpm",
            budget="Daily_budget", impressions="Impressions", orders="Orders",
            revenue="Revenue", roas_reported="Roas", spend="Spend",
        ),
    ),
    Signature(
        key="zepto_campaign_pca", platform="Zepto", report_type="campaign",
        entity_type="campaign", ad_type="PCA",
        required=frozenset({"campaignname", "campaigntype", "daily_budget", "spend", "revenue"}),
        # CampaignType is the bid strategy, not PLA/PCA — kept out of ad_type (see PLA sig).
        colmap=_m(
            campaign_name="CampaignName", status="Status",
            atc="Atc", clicks="Clicks", cpm_reported="Cpm", budget="Daily_budget",
            impressions="Impressions", orders="Orders", revenue="Revenue",
            roas_reported="Roas", spend="Spend",
        ),
    ),
    Signature(
        key="zepto_keyword_pla", platform="Zepto", report_type="keyword",
        entity_type="keyword", ad_type="PLA",
        required=frozenset({"keywordname", "keywordmatchtype", "spend", "revenue", "cpc"}),
        colmap=_m(
            keyword="KeywordName", match_type="KeywordMatchType", campaign_id="CampaignID",
            campaign_name="CampaignName", atc="Atc", clicks="Clicks", cpc_reported="Cpc",
            cpm_reported="Cpm", ctr_reported="Ctr", impressions="Impressions",
            orders="Orders", revenue="Revenue", roas_reported="Roas", spend="Spend",
        ),
        # Zepto exports Ctr as a percentage (1.01 means 1.01%), unlike Amazon.
        pct_fields=frozenset({"ctr_reported"}),
    ),
    Signature(
        key="zepto_keyword_pca", platform="Zepto", report_type="keyword",
        entity_type="keyword", ad_type="PCA",
        required=frozenset({"keywordname", "keywordmatchtype", "spend", "revenue"}),
        colmap=_m(
            keyword="KeywordName", match_type="KeywordMatchType", campaign_id="CampaignID",
            campaign_name="CampaignName", atc="Atc", clicks="Clicks", cpm_reported="Cpm",
            ctr_reported="Ctr", impressions="Impressions", orders="Orders",
            revenue="Revenue", roas_reported="Roas", spend="Spend",
        ),
        # Zepto exports Ctr as a percentage (1.01 means 1.01%), unlike Amazon.
        pct_fields=frozenset({"ctr_reported"}),
    ),
    Signature(
        key="zepto_city_pla", platform="Zepto", report_type="city",
        entity_type="city", ad_type="PLA",
        required=frozenset({"cityname", "campaignname", "spend", "revenue", "cpc"}),
        colmap=_m(
            city="CityName", campaign_id="CampaignID", campaign_name="CampaignName",
            atc="Atc", clicks="Clicks", cpc_reported="Cpc", cpm_reported="Cpm",
            impressions="Impressions", orders="Orders", revenue="Revenue",
            roas_reported="Roas", spend="Spend",
        ),
    ),
    Signature(
        key="zepto_city_pca", platform="Zepto", report_type="city",
        entity_type="city", ad_type="PCA",
        required=frozenset({"cityname", "campaignname", "spend", "revenue"}),
        colmap=_m(
            city="CityName", campaign_id="CampaignID", campaign_name="CampaignName",
            atc="Atc", clicks="Clicks", cpm_reported="Cpm", impressions="Impressions",
            orders="Orders", revenue="Revenue", roas_reported="Roas", spend="Spend",
        ),
    ),
    Signature(
        key="zepto_product_pla", platform="Zepto", report_type="product",
        entity_type="product", ad_type="PLA",
        required=frozenset({"productid", "productname", "spend", "revenue", "cpc"}),
        colmap=_m(
            product_id="ProductID", product_name="ProductName", campaign_id="Campaign_id",
            campaign_name="Campaign_name", atc="Atc", clicks="Clicks", cpc_reported="Cpc",
            cpm_reported="Cpm", ctr_reported="Ctr", impressions="Impressions",
            orders="Orders", revenue="Revenue", roas_reported="Roas", spend="Spend",
        ),
        # Zepto exports Ctr as a percentage (1.01 means 1.01%), unlike Amazon.
        pct_fields=frozenset({"ctr_reported"}),
    ),
    Signature(
        key="zepto_product_pca", platform="Zepto", report_type="product",
        entity_type="product", ad_type="PCA",
        required=frozenset({"productid", "productname", "spend", "revenue"}),
        colmap=_m(
            product_id="ProductID", product_name="ProductName", campaign_id="Campaign_id",
            campaign_name="Campaign_name", atc="Atc", clicks="Clicks", cpm_reported="Cpm",
            ctr_reported="Ctr", impressions="Impressions", orders="Orders",
            revenue="Revenue", roas_reported="Roas", spend="Spend",
        ),
        # Zepto exports Ctr as a percentage (1.01 means 1.01%), unlike Amazon.
        pct_fields=frozenset({"ctr_reported"}),
    ),

    # ---------------- BigBasket ----------------
    Signature(
        key="bigbasket_keyword", platform="BigBasket", report_type="keyword", entity_type="keyword",
        required=frozenset({"keyword", "match type", "ad spend", "ad impressions", "ad revenue"}),
        colmap=_m(
            keyword="Keyword", match_type="Match Type", spend="Ad Spend",
            impressions="Ad Impressions", ctr_reported="CTR", cpm_reported="CPM",
            revenue="Ad Revenue", roas_reported="ROAS",
        ),
        pct_fields=frozenset({"ctr_reported"}),
    ),
    Signature(
        key="bigbasket_product", platform="BigBasket", report_type="product", entity_type="product",
        # Some BigBasket exports leave the product-name column header blank, so it is
        # not part of `required`; ingest names blank headers 'col 0', 'col 1', ...
        required=frozenset({"ad spend", "ad impressions", "add to cart", "ad revenue",
                            "same category orders"}),
        colmap=_m(
            product_name=["Product Name", "col 0"], spend="Ad Spend", impressions="Ad Impressions",
            cpm_reported="CPM", atc="Add to Cart", revenue="Ad Revenue",
            roas_reported="ROAS", orders=["Same Category Orders", "Other SKU Orders"],
        ),
        campaign_name_above_header=True,
    ),

    # ---------------- Blinkit (one workbook, five differently-shaped sheets) ----------------
    Signature(
        key="blinkit_keyword", platform="Blinkit", report_type="keyword", entity_type="keyword",
        required=frozenset({"keyword", "estimated budget consumed", "direct sales", "date_ist"}),
        colmap=_m(
            date="date_ist", campaign_id="Campaign ID", campaign_name="Campaign Name",
            keyword="Keyword", match_type="Match Type", cpm_reported="CPM",
            budget="Total Budget", impressions="Impressions",
            atc=["Direct ATC", "Indirect ATC"], new_users="New Users",
            direct_revenue="Direct Sales", indirect_revenue="Indirect Sales",
            units=["Direct Quantities Sold", "Indirect Quantities Sold"],
            spend="Estimated Budget Consumed", roas_reported="Total RoAS",
        ),
        orders_from_units=True,
    ),
    Signature(
        key="blinkit_category", platform="Blinkit", report_type="category", entity_type="category",
        required=frozenset({"category name", "estimated budget consumed", "direct sales", "date_ist"}),
        colmap=_m(
            date="date_ist", campaign_id="Campaign ID", campaign_name="Campaign Name",
            placement="Category Name", cpm_reported="CPM", budget="Total Budget",
            impressions="Impressions", atc=["Direct ATC", "Indirect ATC"],
            new_users="New Users", direct_revenue="Direct Sales",
            indirect_revenue="Indirect Sales",
            units=["Direct Quantities Sold", "Indirect Quantities Sold"],
            spend="Estimated Budget Consumed", roas_reported="Total RoAS",
        ),
        orders_from_units=True,
    ),
    Signature(
        # Blinkit's "Product Recommendation" sheet is an ad-placement report, not a
        # product one: Asset is the recommendation slot ("Next Product
        # Recommendations") and Title is "#-NA". Mapping those to product_id and
        # product_name put the placement name in the Product ID column and "#-NA" in
        # Product Name. There is no product identifier anywhere in this export, so it
        # is filed as what it is — a placement report.
        key="blinkit_placement", platform="Blinkit", report_type="placement",
        entity_type="placement",
        required=frozenset({"title", "asset", "estimated budget consumed", "direct sales"}),
        colmap=_m(
            date="date_ist", campaign_id="Campaign ID", campaign_name="Campaign Name",
            placement="Asset", cpm_reported="CPM",
            budget="Total Budget", impressions="Impressions",
            atc=["Direct ATC", "Indirect ATC"], new_users="New Users",
            direct_revenue="Direct Sales", indirect_revenue="Indirect Sales",
            units=["Direct Quantities Sold", "Indirect Quantities Sold"],
            spend="Estimated Budget Consumed", roas_reported="Total RoAS",
        ),
        orders_from_units=True,
    ),
    Signature(
        key="blinkit_visual", platform="Blinkit", report_type="campaign",
        entity_type="campaign", ad_type="Visual DIY",
        required=frozenset({"targeting layout", "unique clicks", "estimated budget consumed", "direct sales"}),
        colmap=_m(
            date="date_ist", campaign_id="Campaign ID", campaign_name="Campaign Name",
            placement="Targeting Layout", cpm_reported="CPM", budget="Total Budget",
            impressions="Impressions", clicks="Unique Clicks", ctr_reported="CTR %",
            atc=["Direct ATC", "Indirect ATC"], new_users="New Users",
            direct_revenue="Direct Sales", indirect_revenue="Indirect Sales",
            units=["Direct Quantities Sold", "Indirect Quantities Sold"],
            spend="Estimated Budget Consumed", roas_reported="Total RoAS",
        ),
        pct_fields=frozenset({"ctr_reported"}),
        orders_from_units=True,
    ),
    Signature(
        key="blinkit_budget", platform="Blinkit", report_type="budget", entity_type="campaign",
        required=frozenset({"campaign name", "campaign type", "claimables", "served_budget_consumed"}),
        colmap=_m(
            campaign_id="Campaign ID", campaign_name="Campaign Name", ad_type="Campaign Type",
            impressions="Impressions", budget="Total Budget", spend="served_budget_consumed",
        ),
    ),
]


# --- Which rows make up a platform's TOTAL -------------------------------------
# Every platform ships the same money at several grains (campaign / product /
# keyword / city), so summing all rows would double- or quadruple-count it.
#
# For each (platform, sub-platform) we take the FIRST report type in the priority
# list that was actually ingested. That adapts to whatever the feed contains: this
# month Flipkart National has no campaign export so its product report is used;
# if one appears next month it is used automatically, no code change.
PRIMARY_PRIORITY = {
    "Amazon": ["campaign", "product"],
    "Flipkart": ["campaign", "product"],
    "Instamart": ["campaign", "product", "city"],
    "Zepto": ["campaign", "product"],
    # BigBasket publishes no campaign report at all — only product and keyword.
    # Listing campaign first left it permanently "partial", implying a missing
    # file that is never coming. Product is its most complete export.
    "BigBasket": ["product", "keyword"],
    "Blinkit": [],
}

# Report types that are a separate, non-overlapping ad product rather than another
# view of the same spend, so they add to the total instead of replacing it.
#   Flipkart 'placement' = the PCA banner report (PLA is covered above).
#   Blinkit  = four genuinely distinct ad formats whose sum reconciles exactly with
#              the MTD Claimables sheet — which is why 'budget' is excluded here.
# ponytail: Flipkart 'placement' was additive, but it overlaps the campaign spend
# rather than being a separate ad product, so it double-counted National. National
# total = campaign only. Re-add here only if a placement report is ever a distinct spend.
ADDITIVE_REPORTS = {
    "Blinkit": {"keyword", "category", "placement", "campaign"},
}


def primary_report_types(available: dict[tuple, set]) -> set[tuple]:
    """available: {(platform, sub_platform): {report_type, ...}} -> primary triples."""
    primary = set()
    for (platform, sub_platform), types in available.items():
        chosen = None
        for candidate in PRIMARY_PRIORITY.get(platform, []):
            if candidate in types:
                primary.add((platform, sub_platform, candidate))
                chosen = candidate
                break
        extras = ADDITIVE_REPORTS.get(platform, set()) & types
        for extra in extras:
            primary.add((platform, sub_platform, extra))
        # Nothing preferred and nothing additive present: fall back to whatever this
        # platform actually has. The priority list is a preference, not a requirement —
        # treating it as one meant a platform whose only export was a keyword report
        # (BigBasket's list is campaign/product) had no primary rows at all, so
        # platform_summary was empty and the entire dashboard rendered blank with no
        # error. A breakdown report under-reports the platform total, which is exactly
        # what the `partial` flag already exists to say.
        if not chosen and not extras and types:
            primary.add((platform, sub_platform, _FALLBACK_ORDER(types)))
    return primary


def _FALLBACK_ORDER(types: set) -> str:
    """The most complete of what's available, when no preferred report was supplied."""
    for candidate in ("campaign", "product", "city", "keyword", "placement", "category"):
        if candidate in types:
            return candidate
    return sorted(types)[0]


def detect(columns) -> Optional[Signature]:
    """Best matching signature for a set of raw column headers, or None."""
    cols = {norm(c) for c in columns if not str(c).startswith("Unnamed:")}
    hits = [s for s in SIGNATURES if s.score(cols) == 1.0]
    if not hits:
        return None
    return max(hits, key=lambda s: s.specificity(cols))
