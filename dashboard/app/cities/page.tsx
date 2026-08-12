"use client";

import { useEffect, useMemo, useState } from "react";
import { Row, get, money, num, pct, periodName } from "@/lib/api";
import {
  Card, DataTable, Empty, ErrorBox, GlobalFilterBar, Kpi, Loading, roasColumn, usePeriod,
} from "@/components/ui";
import LocationMap from "@/components/LocationMap";

type Coverage = {
  platforms: string[]; spend_share: number | null;
  covered_spend: number; total_spend: number;
};

const METRICS = [
  { key: "revenue", label: "Revenue" },
  { key: "spend", label: "Spend" },
  { key: "orders", label: "Orders" },
] as const;

export default function Cities() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [metric, setMetric] = useState<(typeof METRICS)[number]["key"]>("revenue");
  const [error, setError] = useState("");
  const { period, fullQuery, query } = usePeriod();

  useEffect(() => {
    if (!period) return;
    setRows(null);
    Promise.all([
      get<Row[]>(`/api/cities?limit=2000${fullQuery}`),
      get<Coverage>(`/api/locations/coverage?_=1${query}`),
    ])
      .then(([r, c]) => { setRows(r); setCoverage(c); })
      .catch((e) => setError(String(e.message ?? e)));
  }, [period, fullQuery, query]);

  const totals = useMemo(() => {
    if (!rows?.length) return null;
    const sum = (k: string) => rows.reduce((t, r) => t + ((r[k] as number) ?? 0), 0);
    const spend = sum("spend"), revenue = sum("revenue");
    const cities = new Set(rows.map((r) => r.city)).size;
    return { spend, revenue, orders: sum("orders"), cities,
             roas: spend ? revenue / spend : null };
  }, [rows]);

  // Best and worst by return, ignoring cities too small to judge.
  const extremes = useMemo(() => {
    if (!rows?.length) return null;
    const judged = rows
      .filter((r) => ((r.spend as number) ?? 0) >= 500 && r.roas !== null)
      .sort((a, b) => (b.roas as number) - (a.roas as number));
    if (!judged.length) return null;
    return { best: judged.slice(0, 5), worst: judged.slice(-5).reverse() };
  }, [rows]);

  if (error) return <ErrorBox error={error} />;

  return (
    <>
      <header className="mb-4">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
          Location Analysis{period && ` — ${periodName(period)}`}
        </h1>
        <p className="text-sm text-slate-500">
          Where in India the sales come from, and which cities earn back what they cost.
        </p>
      </header>

      <GlobalFilterBar />

      {coverage && (
        <div className="mb-4 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          <b>Location data covers {pct(coverage.spend_share)} of spend.</b>{" "}
          Only {coverage.platforms.join(" and ")} report a city
          ({money(coverage.covered_spend)} of {money(coverage.total_spend)}). Amazon,
          Flipkart, BigBasket and Blinkit ship no location dimension at all, so everything
          below describes that share of the business — not all of it.
        </div>
      )}

      {rows === null ? <Loading /> : rows.length === 0 ? (
        <Empty>No location data for this selection.</Empty>
      ) : (
        <>
          {totals && (
            <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-5">
              <Kpi label="Revenue" value={money(totals.revenue)}
                   tone="text-emerald-600 dark:text-emerald-400" />
              <Kpi label="Spend" value={money(totals.spend)} />
              <Kpi label="Orders" value={num(totals.orders)} />
              <Kpi label="ROAS"
                   value={totals.roas ? `₹${totals.roas.toFixed(2)}` : "—"} />
              <Kpi label="Cities" value={num(totals.cities)} />
            </div>
          )}

          <Card
            title="Revenue heatmap"
            subtitle="Every city with sales, placed on the map. Bubble size is the measure you pick; colour is the return on spend."
            className="mb-5"
          >
            <div className="mb-3 flex gap-1">
              {METRICS.map((m) => (
                <button
                  key={m.key}
                  onClick={() => setMetric(m.key)}
                  className={`rounded-lg px-2.5 py-1 text-xs font-medium transition ${
                    metric === m.key
                      ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300"
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>
            <LocationMap rows={rows} metric={metric} />
          </Card>

          {extremes && (
            <div className="mb-5 grid gap-4 md:grid-cols-2">
              <Card title="Best performing locations"
                    subtitle="Highest return per ₹1 spent, among cities with real spend.">
                <DataTable
                  columns={[
                    { key: "city", label: "City" },
                    { key: "platform", label: "Platform" },
                    { key: "spend", label: "Spend", align: "right", format: (v) => money(v) },
                    { key: "revenue", label: "Revenue", align: "right", format: (v) => money(v) },
                    roasColumn(),
                  ]}
                  rows={extremes.best}
                  pageSize={5}
                />
              </Card>
              <Card title="Low performing locations"
                    subtitle="Where the budget returns least — the first places to re-bid.">
                <DataTable
                  columns={[
                    { key: "city", label: "City" },
                    { key: "platform", label: "Platform" },
                    { key: "spend", label: "Spend", align: "right", format: (v) => money(v) },
                    { key: "revenue", label: "Revenue", align: "right", format: (v) => money(v) },
                    roasColumn(),
                  ]}
                  rows={extremes.worst}
                  pageSize={5}
                />
              </Card>
            </div>
          )}

          <Card title="All locations" subtitle="Click any column heading to sort.">
            <DataTable
              columns={[
                { key: "platform", label: "Platform" },
                { key: "city", label: "City" },
                { key: "impressions", label: "Impressions", align: "right", format: (v) => num(v) },
                { key: "clicks", label: "Clicks", align: "right", format: (v) => num(v) },
                { key: "spend", label: "Spend", align: "right", format: (v) => money(v) },
                { key: "orders", label: "Orders", align: "right", format: (v) => num(v) },
                { key: "revenue", label: "Revenue", align: "right", format: (v) => money(v) },
                { key: "conv_rate", label: "Conv. Rate", align: "right", format: (v) => pct(v) },
                roasColumn(),
              ]}
              rows={rows}
              searchable
              exportEntity="cities"
              pageSize={25}
            />
          </Card>
        </>
      )}
    </>
  );
}
