"""The report column spec — one definition, read by both the workbook and the deck.

Levista specifies these columns and this order per report type. Keeping them here
rather than in either generator is what stops the Excel and the PowerPoint from
quietly drifting apart.
"""

# Column spec per entity type. Empty columns are dropped per platform, so one
# spec covers every platform's variant of the same report.
COLUMNS = {
    # Exactly the columns Levista's report specifies, in the order specified. Anything
    # a platform does not supply is dropped per block rather than printed empty, so a
    # sheet never shows a column of dashes.
    "campaign": [("Campaign Name", "campaign_name"), ("Impressions", "impressions"),
                 ("Clicks", "clicks"), ("Spends", "spend"), ("Orders", "orders"),
                 ("Revenue", "revenue"), ("ROAS", "roas"), ("CPM", "cpm"),
                 ("CPC", "cpc"), ("CTR", "ctr"), ("ATC", "atc"),
                 ("New to brand(purchase)", "new_users")],
    "product": [("Product ID", "product_id"), ("Product Name", "product_name"),
                ("Impressions", "impressions"), ("Clicks", "clicks"),
                ("Ad Spend", "spend"), ("Units Sold", "units"),
                ("Add to Cart", "atc"), ("Revenue", "revenue"), ("ROAS", "roas"),
                ("CPM", "cpm"), ("CPC", "cpc"), ("CTR", "ctr")],
    "city": [("City Name", "city"), ("Impressions", "impressions"),
             ("Clicks", "clicks"), ("Spend", "spend"), ("Orders", "orders"),
             ("Add to Cart", "atc"), ("Revenue", "revenue"), ("ROAS", "roas"),
             ("CPM", "cpm"), ("CPC", "cpc"), ("CTR", "ctr")],
    "keyword": [("Campaign Name", "campaign_name"), ("Keywords", "keyword"),
                ("Match Type", "match_type"), ("Impression", "impressions"),
                ("Clicks", "clicks"), ("Spend", "spend"), ("Order", "orders"),
                ("Add to Cart", "atc"), ("Revenue", "revenue"), ("ROAS", "roas"),
                ("CPM", "cpm"), ("CPC", "cpc"), ("CTR", "ctr"),
                ("New Users", "new_users")],
}
