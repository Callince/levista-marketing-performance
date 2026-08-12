"use client";

import { useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  Row, compactMoney, get, money, num, pct, periodName, roasTone, tipMoney,
} from "@/lib/api";
import {
  Card, DataTable, Empty, ErrorBox, GlobalFilterBar, Kpi, Loading, roasColumn, usePeriod,
} from "@/components/ui";

type Segment = {
  category: string; period: string;
  summary: {
    revenue?: number; spend?: number; orders?: number; impressions?: number;
    clicks?: number; atc?: number; roas?: number; ctr?: number; conv_rate?: number; cpc?: number;
  };
  platforms: Row[];
  campaigns: Row[];
  keywords: Row[];
  cities: Row[];
  products: Row[];
};

// Business order, not alphabetical — matches the workbook and the deck.
const CATEGORIES = ["Instant Coffee", "Filter Coffee", "Cold Coffee"];
const inBusinessOrder = (found: string[]) => [
  ...CATEGORIES.filter((c) => found.includes(c)),
  ...found.filter((c) => !CATEGORIES.includes(c)),
];

export default function Segments() {
  const [data, setData] = useState<Record<string, Segment>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const { period, options, filters } = usePeriod();

  // The Product buttons in the filter bar narrow which segments are shown; the
  // Platform buttons scope the numbers inside each one.
  const all = inBusinessOrder(options.categories.length ? options.categories : CATEGORIES);
  const present = filters.category ? all.filter((c) => c === filters.category) : all;
  const platformQuery = filters.platform
    ? `&platform=${encodeURIComponent(filters.platform)}` : "";

  useEffect(() => {
    if (!period) return;
    setLoading(true);
    Promise.all(present.map((c) =>
      get<Segment>(
        `/api/segment?category=${encodeURIComponent(c)}&period=${period}${platformQuery}`)
        .then((s) => [c, s] as const)))
      .then((pairs) => setData(Object.fromEntries(pairs)))
      .catch((e) => setError(String(e.message ?? e)))
      .finally(() => setLoading(false));
  }, [period, present.join("|"), platformQuery]);

  if (error) return <ErrorBox error={error} />;

  const withData = present.filter((c) => (data[c]?.summary?.revenue ?? 0) > 0);

  return (
    <>
      <header className="mb-4">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
          Product Segments{period && ` — ${periodName(period)}`}
          {filters.platform && ` — ${filters.platform}`}
        </h1>
        <p className="text-sm text-slate-500">
          Instant, Filter and Cold Coffee side by side: what each earns, and which campaigns,
          keywords, locations and platforms drive it.
          {filters.platform && ` Showing ${filters.platform} only — click it again to clear.`}
        </p>
      </header>

      {/* Always rendered, so a filter can be changed while the data reloads. */}
      <GlobalFilterBar />

      {loading ? <Loading /> : withData.length === 0 ? (
        <Empty>
          {filters.platform
            ? `No category breakdown for ${filters.platform} this month — click the platform button again to clear the filter.`
            : "No category breakdown for this month. The July workbook records totals per platform without splitting them by coffee type, so segments appear only for months loaded from the raw platform exports."}
        </Empty>
      ) : (
        <div className="grid gap-5 xl:grid-cols-2">
          {withData.map((category) => {
            const segment = data[category];
            const s = segment.summary;
            return (
              <section key={category} className="space-y-4">
                <div className="rounded-xl border border-[#6F4E37] bg-[#6F4E37] px-4 py-2">
                  <h2 className="text-base font-bold text-white">{category}</h2>
                </div>

                <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                  <Kpi label="Revenue" value={money(s.revenue)}
                       tone="text-emerald-600 dark:text-emerald-400" />
                  <Kpi label="Orders" value={num(s.orders)} />
                  <Kpi label="ROAS" value={s.roas ? `₹${s.roas.toFixed(2)}` : "—"}
                       tone={roasTone(s.roas ?? null)} />
                  <Kpi label="Spend" value={money(s.spend)} />
                </div>
                <div className="grid grid-cols-3 gap-3">
                  <Kpi label="CTR" value={pct(s.ctr ?? null)} />
                  <Kpi label="CPC" value={s.cpc ? money(s.cpc) : "—"} />
                  <Kpi label="Conv. Rate" value={pct(s.conv_rate ?? null)} />
                </div>

                <Card title="Platform performance">
                  {segment.platforms.length === 0 ? (
                    <Empty>No platform data.</Empty>
                  ) : (
                    <>
                      <ResponsiveContainer width="100%" height={200}>
                        <BarChart data={segment.platforms} margin={{ left: 8, right: 8 }}>
                          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                          <XAxis dataKey="platform" tick={{ fontSize: 11 }} />
                          <YAxis tickFormatter={compactMoney} tick={{ fontSize: 11 }} />
                          <Tooltip formatter={tipMoney}
                                   contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                          <Bar dataKey="revenue" name="Revenue" fill="#1F3B4D" radius={[4, 4, 0, 0]} />
                          <Bar dataKey="spend" name="Spend" fill="#B08968" radius={[4, 4, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                      <DataTable
                        pageSize={8}
                        columns={[
                          { key: "platform", label: "Platform" },
                          { key: "revenue", label: "Revenue", align: "right", format: (v) => money(v) },
                          { key: "spend", label: "Spend", align: "right", format: (v) => money(v) },
                          { key: "orders", label: "Orders", align: "right", format: (v) => num(v) },
                          roasColumn(),
                        ]}
                        rows={segment.platforms}
                      />
                    </>
                  )}
                </Card>

                {([
                  ["Top campaigns", segment.campaigns, "campaign_name", "Campaign"],
                  ["Top keywords", segment.keywords, "keyword", "Keyword"],
                  ["Top locations", segment.cities, "city", "City"],
                  ["Top products", segment.products, "product_name", "Product"],
                ] as const).map(([title, rows, key, label]) => (
                  <Card key={title} title={title}>
                    <DataTable
                      pageSize={8}
                      columns={[
                        { key: "platform", label: "Platform" },
                        { key, label, width: "max-w-xs truncate" },
                        { key: "spend", label: "Spend", align: "right", format: (v) => money(v) },
                        { key: "revenue", label: "Revenue", align: "right", format: (v) => money(v) },
                        { key: "orders", label: "Orders", align: "right", format: (v) => num(v) },
                        roasColumn(),
                      ]}
                      rows={rows as Row[]}
                      empty={title === "Top locations"
                        ? "Only Zepto and Instamart report a location, and neither has rows for this category."
                        : "No data for this category."}
                    />
                  </Card>
                ))}
              </section>
            );
          })}
        </div>
      )}
    </>
  );
}
