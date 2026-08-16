-- Analytics layer. Every one of these is a GROUP BY over performance_metrics,
-- so there is exactly one place facts are written and no summary can drift.
-- Written in portable SQL (no date functions) so it runs on Postgres and SQLite alike.

DROP VIEW IF EXISTS campaigns;
CREATE VIEW campaigns AS
SELECT period_label, platform, sub_platform, ad_type, category,
       COALESCE(campaign_name, campaign_id) AS campaign_name,
       MIN(period_start) AS period_start, MAX(period_end) AS period_end,
       SUM(impressions) AS impressions, SUM(clicks) AS clicks,
       SUM(spend) AS spend, SUM(revenue) AS revenue,
       SUM(orders) AS orders, SUM(units) AS units, SUM(atc) AS atc,
       SUM(new_users) AS new_users
FROM performance_metrics
WHERE is_primary AND COALESCE(campaign_name, campaign_id) IS NOT NULL
GROUP BY period_label, platform, sub_platform, ad_type, category, COALESCE(campaign_name, campaign_id);

DROP VIEW IF EXISTS keywords;
CREATE VIEW keywords AS
SELECT period_label, platform, sub_platform, category, keyword, match_type,
       MAX(campaign_name) AS campaign_name,
       SUM(impressions) AS impressions, SUM(clicks) AS clicks,
       SUM(spend) AS spend, SUM(revenue) AS revenue,
       SUM(orders) AS orders, SUM(units) AS units, SUM(atc) AS atc,
       SUM(new_users) AS new_users
FROM performance_metrics
WHERE keyword IS NOT NULL
GROUP BY period_label, platform, sub_platform, category, keyword, match_type;

DROP VIEW IF EXISTS products;
CREATE VIEW products AS
SELECT period_label, platform, sub_platform, category,
       COALESCE(product_name, product_id) AS product_name, MAX(product_id) AS product_id,
       SUM(impressions) AS impressions, SUM(clicks) AS clicks,
       SUM(spend) AS spend, SUM(revenue) AS revenue,
       SUM(orders) AS orders, SUM(units) AS units, SUM(atc) AS atc
FROM performance_metrics
WHERE COALESCE(product_name, product_id) IS NOT NULL
GROUP BY period_label, platform, sub_platform, category, COALESCE(product_name, product_id);

DROP VIEW IF EXISTS cities;
CREATE VIEW cities AS
SELECT period_label, platform, sub_platform, category, city,
       SUM(impressions) AS impressions, SUM(clicks) AS clicks,
       SUM(spend) AS spend, SUM(revenue) AS revenue,
       SUM(orders) AS orders, SUM(atc) AS atc
FROM performance_metrics
WHERE city IS NOT NULL
GROUP BY period_label, platform, sub_platform, category, city;

DROP VIEW IF EXISTS sales;
CREATE VIEW sales AS
SELECT period_label, platform, sub_platform, category, period_start, period_end,
       SUM(revenue) AS revenue, SUM(direct_revenue) AS direct_revenue,
       SUM(indirect_revenue) AS indirect_revenue, SUM(units) AS units
FROM performance_metrics
WHERE is_primary
GROUP BY period_label, platform, sub_platform, category, period_start, period_end;

DROP VIEW IF EXISTS orders;
CREATE VIEW orders AS
SELECT period_label, platform, sub_platform, category, period_start, period_end,
       SUM(orders) AS orders, SUM(atc) AS add_to_cart, SUM(clicks) AS clicks
FROM performance_metrics
WHERE is_primary
GROUP BY period_label, platform, sub_platform, category, period_start, period_end;

-- Only Blinkit exports a daily grain; every other platform exports a pre-aggregated
-- period, so this view is intentionally sparse. See README.
DROP VIEW IF EXISTS daily_metrics;
CREATE VIEW daily_metrics AS
SELECT period_label, platform, date,
       SUM(impressions) AS impressions, SUM(clicks) AS clicks,
       SUM(spend) AS spend, SUM(revenue) AS revenue, SUM(orders) AS orders
FROM performance_metrics
WHERE is_primary AND date IS NOT NULL
GROUP BY period_label, platform, date;

DROP VIEW IF EXISTS weekly_metrics;
CREATE VIEW weekly_metrics AS
SELECT period_label, platform, period_start, period_end,
       SUM(impressions) AS impressions, SUM(clicks) AS clicks,
       SUM(spend) AS spend, SUM(revenue) AS revenue, SUM(orders) AS orders
FROM performance_metrics
WHERE is_primary AND period_start IS NOT NULL
GROUP BY period_label, platform, period_start, period_end;

DROP VIEW IF EXISTS monthly_metrics;
CREATE VIEW monthly_metrics AS
SELECT period_label, platform, period_start, period_end,
       SUM(impressions) AS impressions, SUM(clicks) AS clicks,
       SUM(spend) AS spend, SUM(revenue) AS revenue,
       SUM(orders) AS orders, SUM(units) AS units
FROM performance_metrics
WHERE is_primary AND period_start IS NOT NULL
GROUP BY period_label, platform, period_start, period_end;

DROP VIEW IF EXISTS platform_summary;
CREATE VIEW platform_summary AS
SELECT period_label, platform,
       SUM(impressions) AS impressions, SUM(clicks) AS clicks,
       SUM(spend) AS spend, SUM(revenue) AS revenue,
       SUM(orders) AS orders, SUM(units) AS units,
       CASE WHEN SUM(spend) > 0 THEN SUM(revenue) / SUM(spend) END AS roas,
       CASE WHEN SUM(impressions) > 0 THEN SUM(clicks) / SUM(impressions) END AS ctr,
       CASE WHEN SUM(clicks) > 0 THEN SUM(spend) / SUM(clicks) END AS cpc,
       CASE WHEN SUM(clicks) > 0 THEN SUM(orders) / SUM(clicks) END AS conv_rate
FROM performance_metrics
WHERE is_primary
GROUP BY period_label, platform;

DROP VIEW IF EXISTS product_summary;
CREATE VIEW product_summary AS
SELECT period_label, platform, category, product_name, product_id,
       impressions, clicks, spend, revenue, orders, units, atc,
       CASE WHEN spend > 0 THEN revenue / spend END AS roas,
       CASE WHEN impressions > 0 THEN clicks * 1.0 / impressions END AS ctr,
       CASE WHEN clicks > 0 THEN spend / clicks END AS cpc,
       CASE WHEN impressions > 0 THEN spend / impressions * 1000 END AS cpm,
       CASE WHEN clicks > 0 THEN orders * 1.0 / clicks END AS conv_rate
FROM products;

DROP VIEW IF EXISTS keyword_summary;
CREATE VIEW keyword_summary AS
SELECT period_label, platform, category, keyword, match_type, campaign_name,
       impressions, clicks, spend, revenue, orders, units, atc, new_users,
       CASE WHEN spend > 0 THEN revenue / spend END AS roas,
       CASE WHEN impressions > 0 THEN clicks * 1.0 / impressions END AS ctr,
       CASE WHEN clicks > 0 THEN spend / clicks END AS cpc,
       CASE WHEN impressions > 0 THEN spend / impressions * 1000 END AS cpm,
       CASE WHEN clicks > 0 THEN orders * 1.0 / clicks END AS conv_rate
FROM keywords;

DROP VIEW IF EXISTS city_summary;
CREATE VIEW city_summary AS
SELECT period_label, platform, category, city,
       impressions, clicks, spend, revenue, orders, atc,
       CASE WHEN spend > 0 THEN revenue / spend END AS roas,
       CASE WHEN impressions > 0 THEN clicks * 1.0 / impressions END AS ctr,
       CASE WHEN clicks > 0 THEN spend / clicks END AS cpc,
       CASE WHEN impressions > 0 THEN spend / impressions * 1000 END AS cpm,
       CASE WHEN clicks > 0 THEN orders * 1.0 / clicks END AS conv_rate
FROM cities;

DROP VIEW IF EXISTS campaign_summary;
CREATE VIEW campaign_summary AS
SELECT period_label, platform, sub_platform, ad_type, category, campaign_name,
       impressions, clicks, spend, revenue, orders, units, atc, new_users,
       CASE WHEN spend > 0 THEN revenue / spend END AS roas,
       CASE WHEN impressions > 0 THEN clicks * 1.0 / impressions END AS ctr,
       CASE WHEN clicks > 0 THEN spend / clicks END AS cpc,
       CASE WHEN impressions > 0 THEN spend / impressions * 1000 END AS cpm,
       CASE WHEN clicks > 0 THEN orders * 1.0 / clicks END AS conv_rate
FROM campaigns;
