"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  Alert, Insight, Kpis, PlatformRow, Row, compactMoney, dateRange, delta, deltaTone, get, money,
  num, pct, periodName, roasTone, tipMoney,
} from "@/lib/api";
import {
  Badge, Card, DataTable, ErrorBox, ExportButtons, GlobalFilterBar, Kpi, Loading,
  roasColumn, usePeriod,
} from "@/components/ui";

const SLICE = ["#1F3B4D", "#6F4E37", "#3D7A8C", "#B08968", "#5C8A72", "#8C6A5D"];

type TrendRow = Row & {
  period_label: string; days: number; revenue: number; spend: number;
  revenue_per_day: number; spend_per_day: number; orders_per_day: number; roas: number;
};

type FunnelStep = {
  step: string; value: number | null; of_previous: number | null;
  of_impressions: number | null; platforms: string[]; spend_share: number | null;
  note: string | null;
};

export default function Executive() {
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [platforms, setPlatforms] = useState<PlatformRow[] | null>(null);
  const [insights, setInsights] = useState<Insight[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [trend, setTrend] = useState<TrendRow[]>([]);
  const [funnel, setFunnel] = useState<FunnelStep[]>([]);
  const [products, setProducts] = useState<Row[]>([]);
  const [error, setError] = useState("");
  const { period, prior, query, fullQuery, filters, coverage } = usePeriod();

  useEffect(() => {
    if (!period) return;
    const scoped = filters.platform ? `&platform=${encodeURIComponent(filters.platform)}` : "";
    const cat = filters.category ? `&category=${encodeURIComponent(filters.category)}` : "";
    Promise.all([
      // The KPIs follow the platform filter; the comparison table deliberately keeps
      // every platform, since a league table of one row compares nothing — the
      // selected row is highlighted instead.
      get<Kpis>(`/api/kpis?_=1${query}${scoped}${cat}`),
      get<PlatformRow[]>(`/api/platforms?_=1${query}${cat}`),
      get<Insight[]>("/api/insights"),
      get<Alert[]>("/api/alerts"),
      get<TrendRow[]>(`/api/trend?_=1${scoped}${cat}`),
      get<FunnelStep[]>(`/api/funnel?_=1${query}${scoped}${cat}`),
      get<Row[]>(`/api/products?limit=10${fullQuery}`),
    ])
      .then(([k, p, i, a, t, f, pr]) => {
        setKpis(k); setPlatforms(p); setInsights(i); setAlerts(a);
        setTrend(t); setFunnel(f); setProducts(pr);
      })
      .catch((e) => setError(String(e.message ?? e)));
  }, [period, query, fullQuery, filters.platform, filters.category]);

  if (error) return <ErrorBox error={error} />;
  if (!kpis || !platforms) return <Loading />;

  const best = platforms[0];
  const worst = [...platforms].sort((a, b) => a.roas - b.roas)[0];

  const sum = (k: string) => platforms.reduce((t, p) => t + ((p[k] as number) ?? 0), 0);
  const basis = platforms[0]?.growth_basis ?? null;
  const days = platforms[0]?.days ?? null;
  const priorDays = platforms[0]?.compare_days ?? null;
  // When the months are different lengths, compare daily rates — on raw totals a
  // 10-day month reads as a collapse against a full one.
  const scale = basis === "per day" && days && priorDays ? days / priorDays : 1;
  const prevRevenue = prior ? sum("prev_revenue") * scale : 0;
  const prevSpend = prior ? sum("prev_spend") * scale : 0;
  const revenueDelta = prevRevenue ? (kpis.revenue - prevRevenue) / prevRevenue : null;
  const spendDelta = prevSpend ? (kpis.spend - prevSpend) / prevSpend : null;
  const perDay = basis === "per day";
  const basisNote = perDay
    ? ` Changes are per day against ${periodName(prior)} — this period covers ${days} days and that one ${priorDays}, so totals are not comparable.`
    : prior ? ` Changes are against ${periodName(prior)}.`
    : " Load another month to see month-on-month change.";

  const funnelMax = Math.max(...funnel.map((s) => s.value ?? 0), 1);
  const selected = filters.platform;

  return (
    <>
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
            Executive Summary{selected && ` — ${selected}`}
            {filters.category && ` — ${filters.category}`}
            {period && ` — ${periodName(period)}`}
          </h1>
          {coverage && coverage.start && coverage.end && coverage.start !== coverage.end && (
            <p className="mt-0.5 text-sm font-medium text-slate-600 dark:text-slate-300">
              Data for {dateRange(coverage.start, coverage.end)}
            </p>
          )}
          <p className="text-sm text-slate-500">
            Every platform in one view. Green is good, amber needs watching, red needs action.
            {basisNote}
          </p>
        </div>
        <ExportButtons />
      </header>

      <GlobalFilterBar />

      <div className="mb-3 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Kpi label="Revenue" value={money(kpis.revenue)} tone="text-emerald-600 dark:text-emerald-400"
             delta={revenueDelta !== null
               ? `${delta(revenueDelta)} ${perDay ? "per day " : ""}vs ${periodName(prior)}` : undefined} />
        <Kpi label="Sales" value={money(kpis.revenue)}
             hint="same as revenue — the exports report one sales value" />
        <Kpi label="Orders" value={num(kpis.orders)} />
        <Kpi label="ROAS" value={`₹${kpis.roas.toFixed(2)}`} tone={roasTone(kpis.roas)}
             hint="per ₹1 spent" />
        <Kpi label="Spend" value={money(kpis.spend)}
             delta={spendDelta !== null
               ? `${delta(spendDelta)} ${perDay ? "per day " : ""}vs ${periodName(prior)}` : undefined} />
      </div>
      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="CTR" value={pct(kpis.ctr)} />
        <Kpi label="CPC" value={kpis.cpc ? money(kpis.cpc) : "—"} />
        <Kpi label="Conv. Rate" value={pct(kpis.conv_rate)} />
        <Kpi label="Impressions" value={num(kpis.impressions)}
             hint={`${num(kpis.clicks)} clicks`} />
      </div>

      {/* Without this, the headline looks broken: spend/revenue are the billed
          totals, but every breakdown can only show the uploaded portion, so the
          numbers below never add up to the cards above. */}
      {kpis.billed_override && (kpis.billed_coverage ?? 1) < 0.95 && (
        <div className="mb-5 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          <b>Revenue and spend above are the billed totals</b> from the platform billing
          dashboards, not the uploaded reports. The reports loaded so far account for{" "}
          {money(kpis.tracked_spend)} of the {money(kpis.spend)} billed
          {kpis.billed_coverage != null && ` (${pct(kpis.billed_coverage)})`}, so everything
          below — by product, campaign, keyword and city — adds up to the tracked figure,
          not the headline. Upload each platform&apos;s campaign report to close the gap.
        </div>
      )}

      {alerts.length > 0 && (
        <Card title="Needs attention" className="mb-5">
          <ul className="space-y-2">
            {alerts.slice(0, 6).map((a, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                <Badge tone={a.severity === "High"
                  ? "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300"
                  : "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"}>
                  {a.severity}
                </Badge>
                <span className="text-slate-700 dark:text-slate-300">{a.message}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="mb-5 grid gap-4 lg:grid-cols-2">
        <Card title="Revenue trend"
              subtitle="Daily rate, because the loaded months cover different numbers of days.">
          {trend.length < 2 ? (
            <div className="p-6 text-sm text-slate-500">
              Only one month is loaded, so there is no trend to draw yet.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={trend} margin={{ left: 8, right: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="period_label" tickFormatter={periodName} tick={{ fontSize: 11 }} />
                <YAxis tickFormatter={compactMoney} tick={{ fontSize: 11 }} />
                <Tooltip formatter={tipMoney} labelFormatter={periodName}
                         contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="revenue_per_day" name="Revenue / day"
                      stroke="#1F3B4D" strokeWidth={2} dot={{ r: 4 }} />
                <Line type="monotone" dataKey="spend_per_day" name="Spend / day"
                      stroke="#B08968" strokeWidth={2} dot={{ r: 4 }} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card title="ROAS trend" subtitle="A ratio, so period length does not distort it.">
          {trend.length < 2 ? (
            <div className="p-6 text-sm text-slate-500">Load a second month to see the trend.</div>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={trend} margin={{ left: 8, right: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="period_label" tickFormatter={periodName} tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v: unknown) => (typeof v === "number" ? `₹${v.toFixed(2)}` : "—")}
                         labelFormatter={periodName}
                         contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                <Line type="monotone" dataKey="roas" name="ROAS" stroke="#2E7D32"
                      strokeWidth={2} dot={{ r: 4 }} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Card>
      </div>

      <div className="mb-5 grid gap-4 lg:grid-cols-3">
        <Card title="Revenue and spend by platform" className="lg:col-span-2">
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={platforms} margin={{ left: 8, right: 8 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
              <XAxis dataKey="platform" tick={{ fontSize: 11 }} />
              <YAxis tickFormatter={compactMoney} tick={{ fontSize: 11 }} />
              <Tooltip formatter={tipMoney} contentStyle={{ fontSize: 12, borderRadius: 8 }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="revenue" name="Revenue" radius={[4, 4, 0, 0]}>
                {platforms.map((p, i) => (
                  <Cell key={i} fill="#1F3B4D"
                        fillOpacity={!selected || p.platform === selected ? 1 : 0.25} />
                ))}
              </Bar>
              <Bar dataKey="spend" name="Spend" radius={[4, 4, 0, 0]}>
                {platforms.map((p, i) => (
                  <Cell key={i} fill="#B08968"
                        fillOpacity={!selected || p.platform === selected ? 1 : 0.25} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Share of revenue">
          <ResponsiveContainer width="100%" height={280}>
            <PieChart>
              <Pie data={platforms} dataKey="revenue" nameKey="platform"
                   innerRadius={55} outerRadius={95} paddingAngle={2}>
                {platforms.map((p, i) => (
                  <Cell key={i} fill={SLICE[i % SLICE.length]}
                        fillOpacity={!selected || p.platform === selected ? 1 : 0.3} />
                ))}
              </Pie>
              <Tooltip formatter={tipMoney} contentStyle={{ fontSize: 12, borderRadius: 8 }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
            </PieChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <div className="mb-5 grid gap-4 lg:grid-cols-2">
        <Card
          title="Conversion funnel"
          subtitle={funnel.length
            ? `Shown for ${funnel[0].platforms.join(", ")} — the platforms that report every stage (${pct(funnel[0].spend_share)} of spend).`
            : "No platform reports every stage of the funnel."}
        >
          {funnel.map((step) => (
            <div key={step.step} className="mb-2">
              <div className="flex items-baseline justify-between text-sm">
                <span className="font-medium text-slate-700 dark:text-slate-200">{step.step}</span>
                <span className="tabular-nums text-slate-900 dark:text-slate-100">
                  {num(step.value)}
                  {step.of_previous !== null && (
                    <span className="ml-2 text-xs text-slate-500">
                      {pct(step.of_previous)} of previous
                    </span>
                  )}
                </span>
              </div>
              <div className="mt-1 h-3 w-full rounded bg-slate-100 dark:bg-slate-800">
                <div
                  className="h-3 rounded bg-[#6F4E37]"
                  style={{ width: `${Math.max(1, ((step.value ?? 0) / funnelMax) * 100)}%` }}
                />
              </div>
              {step.note && <p className="mt-1 text-[11px] text-amber-700 dark:text-amber-400">{step.note}</p>}
            </div>
          ))}
        </Card>

        <Card title="Top products by revenue" subtitle="Across every platform.">
          {products.length === 0 ? (
            <div className="p-4 text-sm text-slate-500">No product data for this selection.</div>
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(220, products.length * 26)}>
              <BarChart data={products.map((p) => ({
                name: String(p.product_name ?? "—").slice(0, 28), value: p.revenue as number,
              })).reverse()} layout="vertical" margin={{ left: 8, right: 20 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#e2e8f0" />
                <XAxis type="number" tickFormatter={compactMoney} tick={{ fontSize: 11 }} />
                <YAxis type="category" dataKey="name" width={180} tick={{ fontSize: 10 }} />
                <Tooltip formatter={tipMoney} contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                <Bar dataKey="value" fill="#3D7A8C" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>
      </div>

      <Card title="Platform performance" subtitle="Ranked by revenue. Click a heading to re-sort."
            className="mb-5">
        <DataTable
          columns={[
            { key: "platform", label: "Platform" },
            { key: "revenue", label: "Revenue", align: "right", format: (v) => money(v) },
            { key: "spend", label: "Spend", align: "right", format: (v) => money(v) },
            { key: "orders", label: "Orders", align: "right", format: (v) => num(v) },
            { key: "impressions", label: "Impressions", align: "right", format: (v) => num(v) },
            { key: "clicks", label: "Clicks", align: "right", format: (v) => num(v) },
            { key: "ctr", label: "CTR", align: "right", format: (v) => pct(v) },
            { key: "cpc", label: "CPC", align: "right", format: (v) => (v ? money(v) : "—") },
            { key: "conv_rate", label: "Conv. Rate", align: "right", format: (v) => pct(v) },
            roasColumn(),
            { key: "revenue_share", label: "Revenue Share", align: "right", format: (v) => pct(v) },
            ...(prior ? [{
              key: "revenue_growth",
              label: perDay ? "Revenue Growth /day" : "Revenue Growth",
              align: "right" as const,
              format: (v: never) => delta(v as number | null) ?? "—",
              tone: (v: never) => deltaTone(v as number | null),
            }, {
              key: "roas_change", label: "ROAS Change", align: "right" as const,
              format: (v: never) => (v === null || v === undefined
                ? "—" : `${(v as number) >= 0 ? "+" : ""}₹${(v as number).toFixed(2)}`),
              tone: (v: never) => deltaTone(v as number | null),
            }] : []),
          ]}
          rows={platforms}
          pageSize={10}
          highlight={(row) => row.platform === selected}
        />
        <p className="mt-3 text-xs text-slate-500">
          A blank CTR, CPC or conversion rate means that platform&apos;s export does not report
          clicks for most of its spend, so the figure would not be comparable. It is left blank
          rather than shown as a misleading number.
          {platforms.some((p) => p.overridden) && (
            <>
              {" "}Where spend is a billed total, CPC is still computed from the tracked spend
              and tracked clicks — the two always share one base, so it will not match
              billed&nbsp;spend&nbsp;÷&nbsp;clicks.
            </>
          )}
        </p>
      </Card>

      {/* With one platform loaded these two cards are the same row, which reads as a
          contradiction — "biggest revenue source" and "first place to act" at once. */}
      {platforms.length === 1 ? (
        <Card title="Only one platform loaded" className="mb-5">
          <div className="text-xl font-bold text-slate-900 dark:text-white">{best.platform}</div>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            {money(best.revenue)} of revenue on {money(best.spend)} of spend — ₹{best.roas.toFixed(2)}{" "}
            back for every ₹1. Upload the other platforms&apos; exports on the{" "}
            <Link href="/data" className="underline">Data &amp; Uploads</Link> page to compare them
            against each other.
          </p>
        </Card>
      ) : (
        <div className="mb-5 grid gap-4 md:grid-cols-2">
          <Card title="Biggest revenue source">
            <div className="text-xl font-bold text-slate-900 dark:text-white">{best.platform}</div>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
              {money(best.revenue)} — {pct(best.revenue_share)} of all advertising revenue, returning{" "}
              ₹{best.roas.toFixed(2)} per ₹1 spent.
            </p>
          </Card>
          <Card title="Weakest use of budget">
            <div className="text-xl font-bold text-slate-900 dark:text-white">{worst.platform}</div>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
              Returns only ₹{worst.roas.toFixed(2)} per ₹1 spent on {money(worst.spend)} of budget —
              the first place to act.
            </p>
          </Card>
        </div>
      )}

      <Card title="What happened, and what to do about it"
            subtitle="Generated from this period's numbers — one read per platform.">
        <div className="space-y-4">
          {insights.map((item) => (
            <article key={item.platform}
                     className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
              <h3 className="mb-2 font-semibold text-slate-900 dark:text-white">{item.platform}</h3>
              <dl className="space-y-1.5 text-sm">
                {[["What happened", item.what_happened],
                  ["Why", item.why_it_happened],
                  ["What to do next", item.what_to_do_next]].map(([label, text]) => (
                  <div key={label} className="grid grid-cols-[7.5rem_1fr] gap-2">
                    <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</dt>
                    <dd className="text-slate-700 dark:text-slate-300">{text}</dd>
                  </div>
                ))}
              </dl>
            </article>
          ))}
        </div>
      </Card>
    </>
  );
}
