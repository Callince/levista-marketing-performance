"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Alert, Anomaly, Recommendation, Row, get, money, num, priorityTone, roas,
} from "@/lib/api";
import {
  Badge, Card, DataTable, Empty, ErrorBox, GlobalFilterBar, Loading, roasColumn, usePeriod,
} from "@/components/ui";
import Highlights, { HighlightData } from "@/components/Highlights";

type Buckets = { best: Row[]; worst: Row[]; high_cost: Row[]; wasted: Row[] };

const TABS = [
  { key: "best", label: "Best keywords", note: "Highest return — protect and scale these." },
  { key: "worst", label: "Worst keywords", note: "Spending more than they earn back." },
  { key: "high_cost", label: "Highest cost", note: "Where the keyword budget actually goes." },
  { key: "wasted", label: "Wasted spend", note: "Spend with no sales at all." },
] as const;

export default function Insights() {
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [buckets, setBuckets] = useState<Buckets | null>(null);
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("best");
  const [priority, setPriority] = useState("");
  const [error, setError] = useState("");
  const [highlights, setHighlights] = useState<HighlightData | null>(null);
  const { period, query } = usePeriod();

  useEffect(() => {
    if (!period) return;
    Promise.all([
      get<Recommendation[]>("/api/recommendations"),
      get<Alert[]>("/api/alerts"),
      get<Anomaly[]>("/api/anomalies"),
      get<Buckets>("/api/keywords/buckets"),
      get<HighlightData>(`/api/highlights?_=1${query}`),
    ])
      .then(([r, a, an, b, h]) => {
        setRecs(r); setAlerts(a); setAnomalies(an); setBuckets(b); setHighlights(h);
      })
      .catch((e) => setError(String(e.message ?? e)));
  }, [period, query]);

  const filtered = useMemo(
    () => (priority ? recs.filter((r) => r.priority === priority) : recs),
    [recs, priority]);

  const counts = useMemo(() => {
    const by = (p: string) => recs.filter((r) => r.priority === p).length;
    return { High: by("High"), Medium: by("Medium"), Low: by("Low") };
  }, [recs]);

  if (error) return <ErrorBox error={error} />;
  if (!buckets) return <Loading />;

  return (
    <>
      <header className="mb-4">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Insights & Recommendations</h1>
        <p className="text-sm text-slate-500">
          Generated from this period&apos;s numbers using fixed rules, so the same data always gives
          the same answer.
        </p>
      </header>

      <GlobalFilterBar />

      {highlights && <Highlights data={highlights} />}

      {alerts.length > 0 && (
        <Card title="Alerts" className="mb-5">
          <ul className="space-y-2">
            {alerts.map((a, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                <Badge tone={priorityTone(a.severity)}>{a.severity}</Badge>
                <span className="text-slate-700 dark:text-slate-300">
                  {a.platform && <b className="mr-1">{a.platform}</b>}{a.message}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card
        title="Recommendations"
        subtitle="Ranked by priority, then by the money at stake."
        className="mb-5"
      >
        <div className="mb-3 flex gap-1">
          {["", "High", "Medium", "Low"].map((p) => (
            <button
              key={p || "all"}
              onClick={() => setPriority(p)}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium transition ${
                priority === p
                  ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300"
              }`}
            >
              {p || "All"}{p && ` (${counts[p as keyof typeof counts]})`}
            </button>
          ))}
        </div>
        <DataTable
          columns={[
            {
              key: "priority", label: "Priority",
              format: (v) => String(v),
              tone: (v) => (v === "High" ? "font-semibold text-red-600 dark:text-red-400"
                : v === "Medium" ? "text-amber-600 dark:text-amber-400" : "text-slate-500"),
            },
            { key: "platform", label: "Platform" },
            { key: "entity_type", label: "Type" },
            { key: "entity_name", label: "Name", width: "max-w-xs truncate" },
            { key: "action", label: "Action" },
            { key: "impact_value", label: "Money at stake", align: "right", format: (v) => money(v) },
            { key: "rationale", label: "Why", width: "max-w-lg" },
          ]}
          rows={filtered as unknown as Row[]}
        />
      </Card>

      <Card title="Keyword opportunities and leaks" className="mb-5">
        <div className="mb-3 flex flex-wrap gap-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium transition ${
                tab === t.key
                  ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <p className="mb-2 text-xs text-slate-500">{TABS.find((t) => t.key === tab)!.note}</p>
        <DataTable
          columns={[
            { key: "platform", label: "Platform" },
            { key: "keyword", label: "Keyword", width: "max-w-xs truncate" },
            { key: "match_type", label: "Match Type" },
            { key: "impressions", label: "Impressions", align: "right", format: (v) => num(v) },
            { key: "spend", label: "Spend", align: "right", format: (v) => money(v) },
            { key: "revenue", label: "Revenue", align: "right", format: (v) => money(v) },
            roasColumn(),
          ]}
          rows={buckets[tab]}
          exportEntity="keywords"
          pageSize={10}
          empty="Nothing in this bucket — which is good news."
        />
      </Card>

      <Card title="Anomalies"
            subtitle="Values unusually far from the norm for that platform. Worth a look, not automatically a problem.">
        {anomalies.length === 0 ? (
          <Empty>No anomalies detected this period.</Empty>
        ) : (
          <DataTable
            columns={[
              { key: "platform", label: "Platform" },
              { key: "entity_type", label: "Type" },
              { key: "entity_name", label: "Name", width: "max-w-xs truncate" },
              { key: "metric", label: "Measure" },
              { key: "value", label: "Value", align: "right", format: (v, row) =>
                  row.metric === "roas" ? roas(v) : money(v) },
              { key: "cohort_mean", label: "Typical", align: "right", format: (v, row) =>
                  row.metric === "roas" ? roas(v) : money(v) },
              { key: "z_score", label: "Std deviations", align: "right",
                format: (v) => (v as number).toFixed(2),
                tone: (v) => ((v as number) > 0
                  ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400") },
              { key: "direction", label: "Direction" },
            ]}
            rows={anomalies as unknown as Row[]}
          />
        )}
      </Card>
    </>
  );
}
