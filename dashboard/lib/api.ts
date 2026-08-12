const BASE = process.env.NEXT_PUBLIC_API ?? "http://localhost:8000";

export async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${path}`);
  return res.json();
}

export async function post<T>(path: string, body?: FormData): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: "POST", body });
  if (!res.ok) throw new Error((await res.text()) || res.statusText);
  return res.json();
}

export const downloadUrl = (kind: "excel" | "ppt") => `${BASE}/api/export/${kind}`;

// ---------------------------------------------------------------- formatting
// Indian digit grouping: ₹12,34,567 rather than ₹1,234,567.
const inrFmt = new Intl.NumberFormat("en-IN", {
  style: "currency", currency: "INR", maximumFractionDigits: 0,
});
const numFmt = new Intl.NumberFormat("en-IN");

export const money = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : inrFmt.format(v);

export const compactMoney = (v: number | null | undefined) => {
  if (v === null || v === undefined) return "—";
  if (Math.abs(v) >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
  if (Math.abs(v) >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`;
  return inrFmt.format(v);
};

export const num = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : numFmt.format(Math.round(v));

export const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(2)}%`;

export const roas = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `₹${v.toFixed(2)}`;

/** Green above healthy, amber above break-even, red below it. Matches the Excel rules. */
export const roasTone = (v: number | null | undefined) =>
  v === null || v === undefined ? "text-slate-400"
    : v >= 3 ? "text-emerald-600 dark:text-emerald-400"
    : v >= 1 ? "text-amber-600 dark:text-amber-400"
    : "text-red-600 dark:text-red-400";

export const priorityTone = (p: string) =>
  p === "High" ? "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300"
    : p === "Medium" ? "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"
    : "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300";

// ---------------------------------------------------------------- types
export type Row = Record<string, string | number | null>;

export type Periods = {
  periods: string[]; latest: string | null; prior: string | null; comparable: boolean;
};

/** "2026-08" -> "August 2026". Accepts unknown so it can be handed straight to
 *  Recharts, which types axis and tooltip labels as ReactNode. */
export const periodName = (label: unknown) => {
  if (typeof label !== "string" || !label.includes("-")) return String(label ?? "");
  const [y, m] = label.split("-").map(Number);
  if (!y || !m) return label;
  return new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
};

/** Signed percentage for a month-on-month change. */
export const delta = (v: number | null | undefined) =>
  v === null || v === undefined ? null : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;

export const deltaTone = (v: number | null | undefined, goodWhenUp = true) =>
  v === null || v === undefined ? "text-slate-400"
    : (v >= 0) === goodWhenUp ? "text-emerald-600 dark:text-emerald-400"
    : "text-red-600 dark:text-red-400";

export type Kpis = {
  revenue: number; spend: number; orders: number; roas: number; roi: number;
  ctr: number | null; cpc: number | null; conv_rate: number | null;
  impressions: number; clicks: number;
};

export type PlatformRow = Row & {
  platform: string; revenue: number; spend: number; orders: number;
  roas: number; revenue_share: number; ctr: number | null; conv_rate: number | null;
  revenue_growth: number | null; spend_growth: number | null; roas_change: number | null;
  days: number | null; compare_days: number | null;
  /** "per day" when the two months differ in length, else "total". */
  growth_basis: string | null;
};

export type Insight = {
  platform: string; what_happened: string; why_it_happened: string; what_to_do_next: string;
};

export type Recommendation = {
  priority: string; platform: string; entity_type: string; entity_name: string;
  action: string; impact_value: number | null; rationale: string;
};

export type Alert = {
  severity: string; platform: string | null; alert_type: string;
  entity_name: string | null; message: string;
};

export type Anomaly = {
  platform: string; entity_type: string; entity_name: string; metric: string;
  value: number; cohort_mean: number; z_score: number; direction: string;
};

export type FileRow = {
  filename: string; platform: string | null; sub_platform: string | null;
  report_type: string | null; sheet_name: string | null; category: string | null;
  row_count: number | null; processing_status: string; error: string | null;
};

/** Plain-English explanations shown on hover — the audience is brand managers. */
export const GLOSSARY: Record<string, string> = {
  Revenue: "Sales value generated by your ads.",
  Spend: "Money paid to the platform for advertising.",
  ROAS: "Revenue ÷ Ad Spend. ₹4.00 means every ₹1 spent brought back ₹4. Above ₹3 is healthy, below ₹1 loses money.",
  ROI: "(Revenue − Spend) ÷ Spend. The profit on top of what you spent.",
  Orders: "Number of purchases your ads generated.",
  CTR: "Click-Through Rate: how often people who saw an ad clicked it.",
  CPC: "Cost Per Click: what one click costs on average.",
  CPM: "Cost per 1,000 times your ad was shown.",
  "Conv. Rate": "Share of clicks that turned into an order.",
  "Add to Cart": "Shoppers who added the product to their basket.",
  Impressions: "How many times your ad was shown.",
  Clicks: "How many times your ad was clicked.",
  "Revenue Share": "This platform's share of all advertising revenue.",
  "Revenue Growth": "Change in revenue against the previous month loaded.",
  "Spend Growth": "Change in ad spend against the previous month loaded.",
  "ROAS Change": "Change in return per ₹1 spent against the previous month.",
};

/** Recharts 3 types tooltip values as ValueType (possibly undefined), so the
 *  chart formatters take unknown and narrow. */
export const tipMoney = (v: unknown) => money(typeof v === "number" ? v : null);
export const tipNum = (v: unknown) => num(typeof v === "number" ? v : null);
