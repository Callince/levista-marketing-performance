"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Row, compactMoney, get, money, num, pct, periodName, tipMoney, tipNum } from "@/lib/api";
import {
  Card, Column, DataTable, ErrorBox, GlobalFilterBar, Loading, roasColumn, usePeriod,
} from "@/components/ui";

/** Campaigns, products, keywords and cities are the same page with different
 *  columns and a different label field — so they share one component. */
export type EntityConfig = {
  endpoint: "campaigns" | "products" | "keywords" | "cities";
  title: string;
  subtitle: string;
  labelKey: string;
  labelHeader: string;
  extraColumns?: Column[];
  /** Shown as an amber banner — use to flag a partial breakdown that sums to less
   *  than the platform's billed total (products/keywords only cover attributed spend). */
  note?: string;
};

const MEASURES = [
  { key: "revenue", label: "Revenue" },
  { key: "spend", label: "Spend" },
  { key: "orders", label: "Orders" },
  { key: "impressions", label: "Impressions" },
];

export default function EntityPage({ config }: { config: EntityConfig }) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState("");
  const [measure, setMeasure] = useState("revenue");
  const { period, filters, fullQuery } = usePeriod();

  useEffect(() => {
    if (!period) return;                       // wait for the month to be known
    const id = setTimeout(() => {
      setRows(null);
      get<Row[]>(`/api/${config.endpoint}?limit=2000${fullQuery}`)
        .then(setRows)
        .catch((e) => setError(String(e.message ?? e)));
    }, 200);                                   // debounce the free-text filters
    return () => clearTimeout(id);
  }, [config.endpoint, fullQuery, period]);

  const chart = useMemo(() => {
    if (!rows) return [];
    return [...rows]
      .filter((r) => typeof r[measure] === "number")
      .sort((a, b) => (b[measure] as number) - (a[measure] as number))
      .slice(0, 12)
      .map((r) => ({
        name: String(r[config.labelKey] ?? "—").slice(0, 26),
        value: r[measure] as number,
      }));
  }, [rows, measure, config.labelKey]);

  const totals = useMemo(() => {
    if (!rows?.length) return null;
    const sum = (k: string) => rows.reduce((t, r) => t + ((r[k] as number) ?? 0), 0);
    const spend = sum("spend"), revenue = sum("revenue");
    return { spend, revenue, orders: sum("orders"), roas: spend ? revenue / spend : null };
  }, [rows]);

  const columns: Column[] = [
    ...(filters.platform ? [] : [{ key: "platform", label: "Platform" } as Column]),
    { key: config.labelKey, label: config.labelHeader, width: "max-w-xs truncate" },
    ...(config.extraColumns ?? []),
    { key: "impressions", label: "Impressions", align: "right", format: (v) => num(v) },
    { key: "clicks", label: "Clicks", align: "right", format: (v) => num(v) },
    { key: "ctr", label: "CTR", align: "right", format: (v) => pct(v) },
    { key: "spend", label: "Spend", align: "right", format: (v) => money(v) },
    { key: "orders", label: "Orders", align: "right", format: (v) => num(v) },
    { key: "revenue", label: "Revenue", align: "right", format: (v) => money(v) },
    roasColumn(),
  ];

  if (error) return <ErrorBox error={error} />;

  return (
    <>
      <header className="mb-4">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">{config.title}</h1>
        <p className="text-sm text-slate-500">
          {config.subtitle}{period && ` — ${periodName(period)}`}
        </p>
      </header>

      <GlobalFilterBar />

      {config.note && (
        <div className="mb-4 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          {config.note}
        </div>
      )}

      {totals && (
        <div className="mb-4 flex flex-wrap gap-6 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-slate-800 dark:bg-slate-900">
          <span><span className="text-slate-500">Rows </span><b>{rows?.length}</b></span>
          <span><span className="text-slate-500">Spend </span><b>{money(totals.spend)}</b></span>
          <span><span className="text-slate-500">Revenue </span><b>{money(totals.revenue)}</b></span>
          <span><span className="text-slate-500">Orders </span><b>{num(totals.orders)}</b></span>
          <span><span className="text-slate-500">ROAS </span><b>{totals.roas ? `₹${totals.roas.toFixed(2)}` : "—"}</b></span>
        </div>
      )}

      <Card
        title={`Top 12 by ${MEASURES.find((m) => m.key === measure)?.label.toLowerCase()}`}
        className="mb-4"
      >
        <div className="mb-3 flex gap-1">
          {MEASURES.map((m) => (
            <button
              key={m.key}
              onClick={() => setMeasure(m.key)}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium transition ${
                measure === m.key
                  ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
        {chart.length ? (
          <ResponsiveContainer width="100%" height={Math.max(240, chart.length * 26)}>
            <BarChart data={chart} layout="vertical" margin={{ left: 8, right: 24 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#e2e8f0" />
              <XAxis
                type="number"
                tickFormatter={(v) => (measure === "revenue" || measure === "spend" ? compactMoney(v) : num(v))}
                tick={{ fontSize: 11 }}
              />
              <YAxis type="category" dataKey="name" width={190} tick={{ fontSize: 11 }} />
              <Tooltip
                formatter={(v: unknown) =>
                  measure === "revenue" || measure === "spend" ? tipMoney(v) : tipNum(v)}
                contentStyle={{ fontSize: 12, borderRadius: 8 }}
              />
              <Bar dataKey="value" fill="#6F4E37" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="p-4 text-sm text-slate-500">Nothing to chart for this selection.</div>
        )}
      </Card>

      <Card title="All rows" subtitle="Click any column heading to sort.">
        {rows === null ? <Loading />
          : <DataTable columns={columns} rows={rows} searchable
                       exportEntity={config.endpoint} pageSize={25} />}
      </Card>
    </>
  );
}
