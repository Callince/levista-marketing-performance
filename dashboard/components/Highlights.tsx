"use client";

import { money, num, pct, roasTone } from "@/lib/api";
import { Card, Empty } from "@/components/ui";

type Named = {
  name?: string | null; keyword?: string | null; platform?: string | null;
  revenue?: number | null; spend?: number | null; roas?: number | null;
  share?: number | null; orders?: number | null; cpc?: number | null;
  conv_rate?: number | null;
};

export type HighlightData = {
  period: string;
  product: { highest_revenue?: Named; best_return?: Named; worst_return?: Named; count?: number };
  platform: {
    highest_revenue?: Named; highest_roas?: Named; lowest_roas?: Named;
    lowest_cpc?: Named | null; highest_conversion?: Named | null;
    cpc_coverage?: number; platform_count?: number;
  };
  location: {
    highest_revenue?: Named; best_return?: Named; worst_return?: Named; count?: number;
    coverage?: { platforms: string[]; spend_share: number | null };
  };
  keyword: {
    top_converting?: Named[]; high_spend_low_conversion?: Named[]; opportunities?: Named[];
    wasted_spend?: number; wasted_count?: number;
  };
};

const roasText = (v: number | null | undefined) =>
  v === null || v === undefined ? "" : `₹${v.toFixed(2)} per ₹1`;

function Line({ label, item, extra }: { label: string; item?: Named | null; extra?: string }) {
  const name = item?.name ?? item?.keyword;
  return (
    <div className="flex justify-between gap-3 border-b border-slate-100 py-1.5 text-sm last:border-0 dark:border-slate-800">
      <span className="shrink-0 text-slate-500">{label}</span>
      {name ? (
        <span className="truncate text-right">
          <span className="font-medium text-slate-900 dark:text-slate-100">{name}</span>
          {item?.platform && <span className="ml-1 text-xs text-slate-400">({item.platform})</span>}
          {extra && <span className="ml-2 text-xs text-slate-500">{extra}</span>}
        </span>
      ) : (
        <span className="text-slate-400">not available</span>
      )}
    </div>
  );
}

function KeywordRow({ item, right }: { item: Named; right: string }) {
  return (
    <div className="flex justify-between gap-2 text-sm">
      <span className="truncate text-slate-700 dark:text-slate-300">
        {item.name ?? item.keyword}
        {item.platform && <span className="ml-1 text-xs text-slate-400">({item.platform})</span>}
      </span>
      <span className="shrink-0 tabular-nums text-slate-500">
        {right}
        <span className={`ml-2 font-medium ${roasTone(item.roas ?? null)}`}>
          {item.roas === null || item.roas === undefined ? "—" : `₹${item.roas.toFixed(2)}`}
        </span>
      </span>
    </div>
  );
}

export default function Highlights({ data }: { data: HighlightData }) {
  const { product, platform, location, keyword } = data;
  const coverage = location?.coverage;

  return (
    <div className="mb-5 grid gap-4 lg:grid-cols-2">
      <Card title="Product insights" subtitle={`${product?.count ?? 0} advertised products`}>
        <Line label="Highest revenue" item={product?.highest_revenue}
              extra={product?.highest_revenue
                ? `${money(product.highest_revenue.revenue)} · ${pct(product.highest_revenue.share ?? null)} of product revenue`
                : ""} />
        <Line label="Best return" item={product?.best_return}
              extra={roasText(product?.best_return?.roas)} />
        <Line label="Lowest return" item={product?.worst_return}
              extra={roasText(product?.worst_return?.roas)} />
      </Card>

      <Card
        title="Platform insights"
        subtitle={platform?.cpc_coverage !== undefined
          ? `${platform.cpc_coverage} of ${platform.platform_count} platforms report clicks, so the cost-per-click and conversion rankings cover those only.`
          : ""}
      >
        <Line label="Highest revenue" item={platform?.highest_revenue}
              extra={platform?.highest_revenue
                ? `${money(platform.highest_revenue.revenue)} · ${pct(platform.highest_revenue.share ?? null)}`
                : ""} />
        <Line label="Highest ROAS" item={platform?.highest_roas}
              extra={roasText(platform?.highest_roas?.roas)} />
        <Line label="Lowest ROAS" item={platform?.lowest_roas}
              extra={roasText(platform?.lowest_roas?.roas)} />
        <Line label="Lowest cost per click" item={platform?.lowest_cpc}
              extra={platform?.lowest_cpc?.cpc ? money(platform.lowest_cpc.cpc) : ""} />
        <Line label="Highest conversion" item={platform?.highest_conversion}
              extra={platform?.highest_conversion?.conv_rate
                ? pct(platform.highest_conversion.conv_rate) : ""} />
      </Card>

      <Card
        title="Location insights"
        subtitle={coverage?.platforms?.length
          ? `Only ${coverage.platforms.join(" and ")} report a city — ${pct(coverage.spend_share)} of spend. The other platforms ship no location at all, so this covers part of the business.`
          : "No platform reports a location this month."}
      >
        {location?.highest_revenue ? (
          <>
            <Line label="Highest revenue" item={location.highest_revenue}
                  extra={`${money(location.highest_revenue.revenue)} · ${pct(location.highest_revenue.share ?? null)} of located revenue`} />
            <Line label="Best return" item={location.best_return}
                  extra={roasText(location.best_return?.roas)} />
            <Line label="Growth opportunity" item={location.worst_return}
                  extra={location.worst_return?.roas
                    ? `${roasText(location.worst_return.roas)} — weakest of ${location.count} cities`
                    : ""} />
          </>
        ) : <Empty>No location data for this month.</Empty>}
      </Card>

      <Card
        title="Keyword insights"
        subtitle={keyword?.wasted_count
          ? `${money(keyword.wasted_spend)} across ${keyword.wasted_count} keywords produced no sales at all.`
          : "No keyword spend went entirely unrewarded."}
      >
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Top converting
        </p>
        {(keyword?.top_converting ?? []).slice(0, 3).map((k, i) => (
          <KeywordRow key={i} item={k} right={`${num(k.orders)} orders`} />
        ))}

        <p className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
          High spend, poor return
        </p>
        {(keyword?.high_spend_low_conversion ?? []).length === 0 ? (
          <p className="text-sm text-slate-500">
            None &mdash; every keyword with real spend is at least breaking even.
          </p>
        ) : (keyword?.high_spend_low_conversion ?? []).slice(0, 3).map((k, i) => (
          <KeywordRow key={i} item={k} right={money(k.spend)} />
        ))}

        <p className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Opportunities to scale
        </p>
        {(keyword?.opportunities ?? []).slice(0, 3).map((k, i) => (
          <KeywordRow key={i} item={k} right={money(k.spend)} />
        ))}
      </Card>
    </div>
  );
}
