"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Dispatch, ReactNode, SetStateAction, createContext, useContext, useEffect, useState,
} from "react";
import { GLOSSARY, PeriodCoverage, Periods, Row, dateRange, get, periodName, roasTone } from "@/lib/api";

// ---------------------------------------------------------------- period context
// Which month is on screen is shared by every page, so it lives here rather than
// being threaded through props or duplicated per page.
export type GlobalFilters = {
  platform: string; category: string; city: string; keyword: string; campaign: string;
  date: string;
};

const EMPTY: GlobalFilters = { platform: "", category: "", city: "", keyword: "", campaign: "", date: "" };

type PeriodState = {
  period: string | null;
  prior: string | null;
  available: string[];
  comparable: boolean;
  setPeriod: (p: string) => void;
  filters: GlobalFilters;
  setFilters: Dispatch<SetStateAction<GlobalFilters>>;
  options: { platforms: string[]; categories: string[] };
  /** "" when no month is loaded yet, else "&period=2026-08" for query strings. */
  query: string;
  /** period + every active global filter, ready to append to an API call. */
  fullQuery: string;
  /** the actual dates the selected period covers, or null while loading. */
  coverage: PeriodCoverage | null;
  /** the report days available in the selected month, for the day filter. */
  days: string[];
};

const PeriodContext = createContext<PeriodState>({
  period: null, prior: null, available: [], comparable: false, setPeriod: () => {},
  filters: EMPTY, setFilters: () => {}, options: { platforms: [], categories: [] },
  query: "", fullQuery: "", coverage: null, days: [],
});

export const usePeriod = () => useContext(PeriodContext);

function PeriodProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<Periods>({
    periods: [], latest: null, prior: null, comparable: false,
  });
  const [period, setPeriod] = useState<string | null>(null);
  const [filters, setFilters] = useState<GlobalFilters>(EMPTY);
  const [options, setOptions] = useState({ platforms: [] as string[], categories: [] as string[] });
  const [coverage, setCoverage] = useState<PeriodCoverage | null>(null);
  const [days, setDays] = useState<string[]>([]);

  useEffect(() => {
    get<Periods>("/api/periods")
      .then((p) => { setState(p); setPeriod((current) => current ?? p.latest); })
      .catch(() => {});
    get<{ platforms: string[]; categories: string[] }>("/api/filters")
      .then(setOptions).catch(() => {});
  }, []);

  // The real dates the chosen month covers (a 10-day report is not the whole month),
  // and the individual report days available for the day filter.
  useEffect(() => {
    if (!period) { setCoverage(null); setDays([]); return; }
    get<PeriodCoverage>(`/api/period?period=${encodeURIComponent(period)}`)
      .then((r) => setCoverage({ start: r.start, end: r.end }))
      .catch(() => setCoverage(null));
    get<{ days: string[] }>(`/api/days?period=${encodeURIComponent(period)}`)
      .then((r) => setDays(r.days)).catch(() => setDays([]));
  }, [period]);

  // If the selected day isn't in the newly-chosen month, drop it.
  useEffect(() => {
    setFilters((f) => (f.date && !days.includes(f.date) ? { ...f, date: "" } : f));
  }, [days]);

  const index = period ? state.periods.indexOf(period) : -1;
  const prior = index > 0 ? state.periods[index - 1] : null;

  const query = period ? `&period=${encodeURIComponent(period)}` : "";
  const fullQuery = query + Object.entries(filters)
    .filter(([, v]) => v)
    .map(([k, v]) => `&${k}=${encodeURIComponent(v)}`)
    .join("");

  return (
    <PeriodContext.Provider
      value={{
        period, prior, available: state.periods, comparable: state.comparable,
        setPeriod, filters, setFilters, options, query, fullQuery, coverage, days,
      }}
    >
      {children}
    </PeriodContext.Provider>
  );
}

export function PeriodPicker() {
  const { period, prior, available, setPeriod, coverage } = usePeriod();
  if (available.length === 0) return null;
  // Show a day span only when it's a real multi-day range; a single/degenerate date
  // would mislead, so the month label carries it on its own.
  const span = coverage && coverage.start && coverage.end && coverage.start !== coverage.end
    ? dateRange(coverage.start, coverage.end) : "";
  if (available.length === 1) {
    return (
      <div className="text-xs text-slate-500">
        <div className="font-medium">Showing</div>
        <div>{periodName(available[0])}</div>
        {span && <div className="mt-0.5 text-[11px] font-medium text-slate-600 dark:text-slate-300">{span}</div>}
        <div className="mt-1 text-[11px] leading-snug">
          Load another month to switch on comparison.
        </div>
      </div>
    );
  }
  return (
    <div className="text-xs">
      <label className="font-medium text-slate-500" htmlFor="period">Month</label>
      <select
        id="period"
        value={period ?? ""}
        onChange={(e) => setPeriod(e.target.value)}
        className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900"
      >
        {[...available].reverse().map((p) => (
          <option key={p} value={p}>{periodName(p)}</option>
        ))}
      </select>
      {span && <div className="mt-1 text-[11px] font-medium text-slate-600 dark:text-slate-300">{span}</div>}
      <div className="mt-0.5 text-[11px] text-slate-400">
        {prior ? `compared with ${periodName(prior)}` : "no earlier month to compare"}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- primitives

export function Info({ term }: { term: string }) {
  const text = GLOSSARY[term];
  if (!text) return null;
  return (
    <span className="group relative ml-1 inline-flex cursor-help align-middle">
      <span className="flex h-3.5 w-3.5 items-center justify-center rounded-full border border-slate-400 text-[9px] font-bold text-slate-500">
        ?
      </span>
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-30 mb-1.5 hidden w-60 -translate-x-1/2 rounded-md bg-slate-900 px-2.5 py-2 text-xs font-normal leading-snug text-white shadow-lg group-hover:block"
      >
        {text}
      </span>
    </span>
  );
}

export function Card({ title, subtitle, children, className = "" }: {
  title?: string; subtitle?: string; children: ReactNode; className?: string;
}) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900 ${className}`}>
      {title && (
        <header className="mb-3">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h2>
          {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Kpi({ label, value, tone = "", hint, delta }: {
  label: string; value: string; tone?: string; hint?: string; delta?: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-center text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
        <Info term={label} />
      </div>
      <div className={`mt-1.5 text-2xl font-bold tabular-nums ${tone || "text-slate-900 dark:text-slate-100"}`}>
        {value}
      </div>
      {(hint || delta) && (
        <div className="mt-1 text-xs text-slate-500">{delta ?? hint}</div>
      )}
    </div>
  );
}

export function Badge({ children, tone }: { children: ReactNode; tone: string }) {
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${tone}`}>
      {children}
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-700">
      {children}
    </div>
  );
}

export function Loading() {
  return <div className="animate-pulse p-6 text-sm text-slate-400">Loading…</div>;
}

export function ErrorBox({ error }: { error: string }) {
  return (
    <div className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
      <strong className="font-semibold">Could not load data.</strong> {error}
      <div className="mt-1 text-xs">
        Is the API running? Start it with{" "}
        <code className="rounded bg-red-100 px-1 dark:bg-red-900">
          uvicorn api.main:app --port 8000
        </code>{" "}
        from the <code>platform</code> folder.
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- table

export type Column = {
  key: string;
  label: string;
  format?: (v: never, row: Row) => string;
  /** Full control of the cell — for buttons and other non-text content. Wins over format. */
  render?: (row: Row) => ReactNode;
  align?: "left" | "right";
  tone?: (v: never) => string;
  width?: string;
};

export function DataTable({
  columns, rows, empty = "No data for this selection.", pageSize = 25,
  exportEntity, searchable = false, highlight,
}: {
  columns: Column[]; rows: Row[]; empty?: string; pageSize?: number;
  /** entity name enables server-side Excel/CSV export of the filtered table */
  exportEntity?: "campaigns" | "products" | "keywords" | "cities";
  searchable?: boolean;
  /** mark the row matching the current selection without hiding the others */
  highlight?: (row: Row) => boolean;
}) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const [page, setPage] = useState(0);
  const [needle, setNeedle] = useState("");
  const { fullQuery } = usePeriod();

  const filtered = needle
    ? rows.filter((r) => columns.some((c) => {
        const v = r[c.key];
        return v !== null && v !== undefined
          && String(v).toLowerCase().includes(needle.toLowerCase());
      }))
    : rows;

  const toolbar = (exportEntity || searchable) && (
    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
      {searchable ? (
        <input
          value={needle}
          onChange={(e) => { setNeedle(e.target.value); setPage(0); }}
          placeholder="Search this table…"
          className="w-56 rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900"
        />
      ) : <span />}
      {exportEntity && (
        <div className="flex gap-1.5 text-xs">
          <span className="self-center text-slate-500">Export what is shown:</span>
          {(["csv", "xlsx"] as const).map((fmt) => (
            <a
              key={fmt}
              href={`${process.env.NEXT_PUBLIC_API ?? "http://localhost:8000"}/api/export/table/${exportEntity}?fmt=${fmt}${fullQuery}`}
              className="rounded-lg border border-slate-300 px-2 py-1 font-medium text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              {fmt === "csv" ? "CSV" : "Excel"}
            </a>
          ))}
        </div>
      )}
    </div>
  );

  if (!rows.length) return <><>{toolbar}</><Empty>{empty}</Empty></>;

  const sortedAll = sort
    ? [...rows].sort((a, b) => {
        const x = a[sort.key], y = b[sort.key];
        if (x === null || x === undefined) return 1;
        if (y === null || y === undefined) return -1;
        return typeof x === "number" && typeof y === "number"
          ? (x - y) * sort.dir
          : String(x).localeCompare(String(y)) * sort.dir;
      })
    : filtered;

  const pages = Math.max(1, Math.ceil(sortedAll.length / pageSize));
  const current = Math.min(page, pages - 1);
  const sorted = sortedAll.slice(current * pageSize, (current + 1) * pageSize);

  return (
    <>
    {toolbar}
    <div className="overflow-x-auto">
      <table className="w-full min-w-max text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left dark:border-slate-700">
            {columns.map((c) => (
              <th
                key={c.key}
                onClick={() =>
                  setSort((s) =>
                    s?.key === c.key ? { key: c.key, dir: s.dir === 1 ? -1 : 1 } : { key: c.key, dir: -1 })
                }
                className={`cursor-pointer whitespace-nowrap px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500 select-none hover:text-slate-900 dark:hover:text-slate-200 ${
                  c.align === "right" ? "text-right" : ""
                }`}
              >
                {c.label}
                <Info term={c.label} />
                {sort?.key === c.key && <span className="ml-1">{sort.dir === 1 ? "▲" : "▼"}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <tr
              key={i}
              className={`border-b border-slate-100 last:border-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50 ${
                highlight?.(row)
                  ? "bg-slate-100 font-semibold dark:bg-slate-800"
                  : highlight ? "opacity-50" : ""
              }`}
            >
              {columns.map((c) => {
                const value = row[c.key];
                return (
                  <td
                    key={c.key}
                    className={`px-3 py-2 tabular-nums ${c.align === "right" ? "text-right" : ""} ${
                      c.tone ? c.tone(value as never) : ""
                    } ${c.width ?? ""}`}
                    title={typeof value === "string" ? value : undefined}
                  >
                    {c.render ? c.render(row) : c.format ? c.format(value as never, row) : value ?? "—"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    {pages > 1 && (
      <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
        <span>
          {current * pageSize + 1}–{Math.min((current + 1) * pageSize, sortedAll.length)} of{" "}
          {sortedAll.length}
        </span>
        <div className="flex gap-1">
          <button
            onClick={() => setPage(Math.max(0, current - 1))}
            disabled={current === 0}
            className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40 dark:border-slate-700"
          >
            Previous
          </button>
          <span className="px-2 py-1">Page {current + 1} of {pages}</span>
          <button
            onClick={() => setPage(Math.min(pages - 1, current + 1))}
            disabled={current >= pages - 1}
            className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40 dark:border-slate-700"
          >
            Next
          </button>
        </div>
      </div>
    )}
    </>
  );
}


/** The dashboard-wide filter bar. Dimensions a table does not carry are simply
 *  ignored by that table rather than emptying it. */
/** A toggle button. Clicking the one already selected clears that filter, so a
 *  filter can always be removed with the same click that applied it. */
function Toggle({ label, active, onClick, clearable = true }: {
  label: string; active: boolean; onClick: () => void; clearable?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      title={active
        ? (clearable ? `Click again to remove the ${label} filter` : `Showing ${label}`)
        : `Show only ${label}`}
      className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
        active
          ? "bg-slate-900 text-white shadow-sm dark:bg-slate-100 dark:text-slate-900"
          : "border border-slate-300 bg-white text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
      }`}
    >
      {label}
      {/* "All" is the absence of a filter, so it has nothing to clear. */}
      {active && clearable && <span className="ml-1.5 text-xs opacity-70">×</span>}
    </button>
  );
}

export function GlobalFilterBar() {
  const { filters, setFilters, options, days } = usePeriod();
  const box =
    "rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";
  const empty: GlobalFilters = {
    platform: "", category: "", city: "", keyword: "", campaign: "", date: "",
  };
  const active = Object.values(filters).filter(Boolean).length;

  /** Same value again = switch it off.
   *
   *  Functional updates, not a spread of the render's `filters`: two clicks landing
   *  in one tick would otherwise both build from the same stale object and the
   *  second would silently undo the first. */
  const toggle = (field: "platform" | "category", value: string) =>
    setFilters((current) => ({
      ...current, [field]: current[field] === value ? "" : value,
    }));

  const set = (field: keyof GlobalFilters, value: string) =>
    setFilters((current) => ({ ...current, [field]: value }));

  return (
    <div className="mb-4 space-y-2.5 rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-16 shrink-0 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Platform
        </span>
        <Toggle label="All" active={!filters.platform} clearable={false}
                onClick={() => set("platform", "")} />
        {options.platforms.map((p) => (
          <Toggle key={p} label={p} active={filters.platform === p}
                  onClick={() => toggle("platform", p)} />
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="w-16 shrink-0 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Product
        </span>
        <Toggle label="All" active={!filters.category} clearable={false}
                onClick={() => set("category", "")} />
        {options.categories.map((c) => (
          <Toggle key={c} label={c} active={filters.category === c}
                  onClick={() => toggle("category", c)} />
        ))}
      </div>

      {days.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-16 shrink-0 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Day
          </span>
          <select className={box} value={filters.date} onChange={(e) => set("date", e.target.value)}>
            <option value="">All days · whole month</option>
            {days.map((d) => <option key={d} value={d}>{dateRange(d, d)}</option>)}
          </select>
          {filters.date && (
            <span className="text-xs text-slate-500">viewing a single day</span>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <span className="w-16 shrink-0 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Search
        </span>
        {(["city", "keyword", "campaign"] as const).map((field) => (
          <span key={field} className="relative">
            <input
              className={`${box} w-40 ${filters[field] ? "pr-7" : ""}`}
              placeholder={field[0].toUpperCase() + field.slice(1)}
              value={filters[field]}
              onChange={(e) => set(field, e.target.value)}
            />
            {filters[field] && (
              <button
                type="button"
                onClick={() => set(field, "")}
                title={`Remove the ${field} filter`}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-sm text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
              >
                ×
              </button>
            )}
          </span>
        ))}
        {active > 0 && (
          <button
            type="button"
            onClick={() => setFilters(empty)}
            className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            Clear all {active}
          </button>
        )}
        <span className="ml-auto text-[11px] text-slate-400">
          Date range is by month — the exports are pre-aggregated, not daily.
        </span>
      </div>
    </div>
  );
}

export const roasColumn = (key = "roas", label = "ROAS"): Column => ({
  key, label, align: "right",
  tone: (v: never) => `font-semibold ${roasTone(v as number | null)}`,
  format: (v: never) => (v === null || v === undefined ? "—" : `₹${(v as number).toFixed(2)}`),
});

// ---------------------------------------------------------------- shell

// Grouped so the sidebar reads as three jobs — see the headline, dig into a
// dimension, manage the data — rather than one flat list of nine links.
const NAV = [
  {
    section: "Overview",
    items: [
      { href: "/", label: "Executive", icon: "◧" },
      { href: "/segments", label: "Product Segments", icon: "◑" },
      { href: "/insights", label: "Insights", icon: "◈" },
    ],
  },
  {
    section: "Drill down",
    items: [
      { href: "/platforms", label: "Platforms", icon: "▦" },
      { href: "/campaigns", label: "Campaigns", icon: "▤" },
      { href: "/products", label: "Products", icon: "▣" },
      { href: "/keywords", label: "Keywords", icon: "▩" },
      { href: "/cities", label: "Cities", icon: "◉" },
    ],
  },
  {
    section: "Manage",
    items: [{ href: "/data", label: "Data & Uploads", icon: "▤" }],
  },
];

export function Shell({ children }: { children: ReactNode }) {
  return (
    <PeriodProvider>
      <ShellInner>{children}</ShellInner>
    </PeriodProvider>
  );
}

function ShellInner({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  // Remember the choice — a sidebar that springs back open on every navigation
  // is worse than one that never collapsed.
  useEffect(() => {
    setCollapsed(localStorage.getItem("levista.nav.collapsed") === "1");
  }, []);
  const toggle = () => setCollapsed((was) => {
    localStorage.setItem("levista.nav.collapsed", was ? "0" : "1");
    return !was;
  });

  return (
    <div className="flex min-h-screen bg-slate-50 dark:bg-slate-950">
      <aside
        // Width is inline rather than a conditional Tailwind class: the v4 JIT did
        // not emit w-16 from inside the template literal, so the class landed on the
        // element with no rule behind it and the sidebar never actually shrank.
        style={{ width: collapsed ? 64 : 240 }}
        className="sticky top-0 flex h-screen shrink-0 flex-col border-r border-slate-200 bg-white transition-[width] duration-200 ease-out dark:border-slate-800 dark:bg-slate-900"
      >
        <div className="flex items-center gap-2 border-b border-slate-200 px-3 py-4 dark:border-slate-800">
          {/* The brand wordmark is dark brown, so it is lightened in dark mode
              rather than shipped as a second asset. */}
          {collapsed ? (
            <img src="/levista-mark.svg" alt="Levista"
                 className="h-8 w-auto shrink-0 dark:brightness-0 dark:invert" />
          ) : (
            <div className="min-w-0">
              <img src="/levista-logo.svg" alt="Levista Foods"
                   className="h-7 w-auto dark:brightness-0 dark:invert" />
              <div className="mt-1 truncate text-[11px] text-slate-500">
                Marketing Performance
              </div>
            </div>
          )}
          <button
            type="button"
            onClick={toggle}
            title={collapsed ? "Expand menu" : "Collapse menu"}
            aria-label={collapsed ? "Expand menu" : "Collapse menu"}
            className="ml-auto rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-900 dark:hover:bg-slate-800 dark:hover:text-slate-100"
          >
            {collapsed ? "»" : "«"}
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto p-2">
          {NAV.map((group) => (
            <div key={group.section} className="mb-3">
              {!collapsed && (
                <div className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                  {group.section}
                </div>
              )}
              {group.items.map((item) => {
                const active = path === item.href;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    title={collapsed ? item.label : undefined}
                    aria-current={active ? "page" : undefined}
                    className={`group relative mb-0.5 flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition ${
                      active
                        ? "bg-slate-100 font-semibold text-slate-900 dark:bg-slate-800 dark:text-white"
                        : "text-slate-600 hover:bg-slate-50 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-100"
                    } ${collapsed ? "justify-center px-0" : ""}`}
                  >
                    {/* accent bar marks the current page without shouting */}
                    <span
                      className={`absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r ${
                        active ? "bg-[#6F4E37]" : "bg-transparent"
                      }`}
                    />
                    <span className={`text-base leading-none ${active ? "text-[#6F4E37]" : "text-slate-400"}`}>
                      {item.icon}
                    </span>
                    {!collapsed && <span className="truncate">{item.label}</span>}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        {!collapsed && (
          <div className="border-t border-slate-200 px-4 py-3 dark:border-slate-800">
            <PeriodPicker />
          </div>
        )}
      </aside>
      <main className="min-w-0 flex-1 p-6">{children}</main>
    </div>
  );
}

// ---------------------------------------------------------------- filters

export function Filters({ platforms, categories, value, onChange, showSearch = true }: {
  platforms: string[];
  categories: string[];
  value: { platform: string; category: string; search: string };
  onChange: (v: { platform: string; category: string; search: string }) => void;
  showSearch?: boolean;
}) {
  const select =
    "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2">
      <select
        className={select}
        value={value.platform}
        onChange={(e) => onChange({ ...value, platform: e.target.value })}
      >
        <option value="">All platforms</option>
        {platforms.map((p) => <option key={p} value={p}>{p}</option>)}
      </select>
      <select
        className={select}
        value={value.category}
        onChange={(e) => onChange({ ...value, category: e.target.value })}
      >
        <option value="">All categories</option>
        {categories.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      {showSearch && (
        <input
          className={`${select} min-w-56 flex-1`}
          placeholder="Search…"
          value={value.search}
          onChange={(e) => onChange({ ...value, search: e.target.value })}
        />
      )}
    </div>
  );
}

export function ExportButtons() {
  const base = process.env.NEXT_PUBLIC_API ?? "http://localhost:8000";
  const cls =
    "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800";
  return (
    <div className="flex gap-2">
      <a className={cls} href={`${base}/api/export/excel`}>Export Excel</a>
      <a className={cls} href={`${base}/api/export/ppt`}>Export PowerPoint</a>
    </div>
  );
}
