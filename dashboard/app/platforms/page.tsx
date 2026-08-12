"use client";

import { useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  Insight, Kpis, PlatformRow, Row, compactMoney, delta, deltaTone, get, money, num,
  pct, periodName, roasTone, tipMoney,
} from "@/lib/api";
import {
  Card, DataTable, ErrorBox, Kpi, Loading, roasColumn, usePeriod,
} from "@/components/ui";

export default function Platforms() {
  const [platforms, setPlatforms] = useState<PlatformRow[] | null>(null);
  const [selected, setSelected] = useState<string>("");
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [campaigns, setCampaigns] = useState<Row[]>([]);
  const [insight, setInsight] = useState<Insight | null>(null);
  const [error, setError] = useState("");
  const { period, prior, query } = usePeriod();

  useEffect(() => {
    if (!period) return;
    get<PlatformRow[]>(`/api/platforms?_=1${query}`)
      .then((p) => { setPlatforms(p); setSelected(p[0]?.platform ?? ""); })
      .catch((e) => setError(String(e.message ?? e)));
  }, [period, query]);

  useEffect(() => {
    if (!selected) return;
    setKpis(null);
    Promise.all([
      get<Kpis>(`/api/kpis?platform=${encodeURIComponent(selected)}${query}`),
      get<Row[]>(`/api/campaigns?platform=${encodeURIComponent(selected)}&limit=25${query}`),
      get<Insight[]>("/api/insights"),
    ]).then(([k, c, i]) => {
      setKpis(k); setCampaigns(c);
      setInsight(i.find((x) => x.platform === selected) ?? null);
    }).catch((e) => setError(String(e.message ?? e)));
  }, [selected, query]);

  if (error) return <ErrorBox error={error} />;
  if (!platforms) return <Loading />;

  return (
    <>
      <header className="mb-4">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Platform Dashboard</h1>
        <p className="text-sm text-slate-500">
          Compare marketplaces, then drill into one.
          {prior && (platforms[0]?.growth_basis === "per day"
            ? ` Growth is per day against ${periodName(prior)} (${platforms[0]?.days} days vs ${platforms[0]?.compare_days}).`
            : ` Growth is against ${periodName(prior)}.`)}
        </p>
      </header>

      <Card title="Spend against revenue" subtitle="A bar where spend is taller than revenue is losing money."
            className="mb-5">
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={platforms} margin={{ left: 8, right: 8 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
            <XAxis dataKey="platform" tick={{ fontSize: 11 }} />
            <YAxis tickFormatter={compactMoney} tick={{ fontSize: 11 }} />
            <Tooltip formatter={tipMoney} contentStyle={{ fontSize: 12, borderRadius: 8 }} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="revenue" name="Revenue" fill="#1F3B4D" radius={[4, 4, 0, 0]} />
            <Bar dataKey="spend" name="Spend" fill="#B08968" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Card>

      <Card title="Ranking" className="mb-5">
        <DataTable
          columns={[
            { key: "rank_revenue", label: "#", align: "right" },
            { key: "platform", label: "Platform" },
            { key: "revenue", label: "Revenue", align: "right", format: (v) => money(v) },
            { key: "spend", label: "Spend", align: "right", format: (v) => money(v) },
            { key: "orders", label: "Orders", align: "right", format: (v) => num(v) },
            roasColumn(),
            { key: "revenue_share", label: "Revenue Share", align: "right", format: (v) => pct(v) },
            ...(prior ? [{
              key: "revenue_growth",
              label: platforms[0]?.growth_basis === "per day" ? "Revenue Growth /day" : "Revenue Growth",
              align: "right" as const,
              format: (v: never) => delta(v as number | null) ?? "—",
              tone: (v: never) => deltaTone(v as number | null),
            }] : []),
          ]}
          rows={platforms}
        />
      </Card>

      <div className="mb-4 flex flex-wrap gap-2">
        {platforms.map((p) => (
          <button
            key={p.platform}
            onClick={() => setSelected(p.platform)}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
              selected === p.platform
                ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                : "border border-slate-300 bg-white text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
            }`}
          >
            {p.platform}
          </button>
        ))}
      </div>

      {!kpis ? <Loading /> : (
        <>
          <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-5">
            <Kpi label="Revenue" value={money(kpis.revenue)} tone="text-emerald-600 dark:text-emerald-400" />
            <Kpi label="Spend" value={money(kpis.spend)} />
            <Kpi label="ROAS" value={`₹${kpis.roas?.toFixed(2) ?? "—"}`} tone={roasTone(kpis.roas)} />
            <Kpi label="Orders" value={num(kpis.orders)} />
            <Kpi label="CTR" value={pct(kpis.ctr)} />
          </div>

          {insight && (
            <Card title={`${selected} — what happened`} className="mb-5">
              <dl className="space-y-1.5 text-sm">
                {[["What happened", insight.what_happened],
                  ["Why", insight.why_it_happened],
                  ["What to do next", insight.what_to_do_next]].map(([label, text]) => (
                  <div key={label} className="grid grid-cols-[7.5rem_1fr] gap-2">
                    <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</dt>
                    <dd className="text-slate-700 dark:text-slate-300">{text}</dd>
                  </div>
                ))}
              </dl>
            </Card>
          )}

          <Card title={`${selected} campaigns`}>
            <DataTable
              columns={[
                { key: "campaign_name", label: "Campaign", width: "max-w-md truncate" },
                { key: "impressions", label: "Impressions", align: "right", format: (v) => num(v) },
                { key: "spend", label: "Spend", align: "right", format: (v) => money(v) },
                { key: "orders", label: "Orders", align: "right", format: (v) => num(v) },
                { key: "revenue", label: "Revenue", align: "right", format: (v) => money(v) },
                roasColumn(),
              ]}
              rows={campaigns}
            />
          </Card>
        </>
      )}
    </>
  );
}
