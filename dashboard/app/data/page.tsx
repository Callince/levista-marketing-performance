"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { FileRow, Row, get, money, num, periodName, post } from "@/lib/api";
import {
  Badge, Card, DataTable, ErrorBox, ExportButtons, Loading, usePeriod,
} from "@/components/ui";

type Job = { status: string; message: string; finished_at: string | null };
type Recon = {
  platform: string; tracked_spend: number; tracked_revenue: number;
  billed_spend: number | null; billed_revenue: number | null;
  gap_spend: number | null; gap_revenue: number | null;
};

const PLATFORMS = ["Amazon", "Flipkart", "Instamart", "Zepto", "BigBasket", "Blinkit"];
const PRODUCTS = ["Cold Coffee", "Filter Coffee", "Instant Coffee"];
const SUBPLATFORMS = ["Minutes", "National"];   // Flipkart market
const AD_TYPES = ["PLA", "PCA"];                 // ad type — Flipkart Minutes/National each have both; Zepto too
const REPORTS = ["campaign", "product", "keyword", "city", "placement"];

const STATUS_TONE: Record<string, string> = {
  ok: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  duplicate: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  needs_review: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  failed: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
};

export default function DataPage() {
  const [files, setFiles] = useState<FileRow[] | null>(null);
  const [uploads, setUploads] = useState<Row[]>([]);
  const [job, setJob] = useState<Job>({ status: "idle", message: "", finished_at: null });
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [label, setLabel] = useState("");
  const [platform, setPlatform] = useState("");
  const [category, setCategory] = useState("");
  const [subPlatform, setSubPlatform] = useState("");
  const [adType, setAdType] = useState("");
  const [reportType, setReportType] = useState("");
  const [staged, setStaged] = useState<File[]>([]);
  const [recon, setRecon] = useState<Recon[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const { available } = usePeriod();

  const refresh = useCallback(() => {
    get<FileRow[]>("/api/files").then(setFiles).catch((e) => setError(String(e.message ?? e)));
    get<Row[]>("/api/uploads").then(setUploads).catch(() => {});
    get<{ rows: Recon[] }>("/api/reconciliation").then((r) => setRecon(r.rows)).catch(() => {});
  }, []);

  useEffect(refresh, [refresh]);

  // Poll only while a rebuild is actually running.
  useEffect(() => {
    if (job.status !== "running") return;
    const id = setInterval(() => {
      get<Job>("/api/job").then((j) => {
        setJob(j);
        if (j.status !== "running") refresh();
      }).catch(() => {});
    }, 2000);
    return () => clearInterval(id);
  }, [job.status, refresh]);

  async function send(list: File[]) {
    if (!list.length) return;
    const body = new FormData();
    list.forEach((f) => body.append("files", f));
    if (label) body.append("period", label);
    if (platform) body.append("platform", platform);
    if (category) body.append("category", category);
    if (subPlatform) body.append("sub_platform", subPlatform);
    if (adType) body.append("ad_type", adType);
    if (reportType) body.append("report_type", reportType);
    setNotice("");
    try {
      const res = await post<{ saved: string[]; rejected: { filename: string; reason: string }[]; job: Job }>(
        "/api/upload", body);
      setJob(res.job);
      setStaged([]);
      setNotice(
        `Uploaded ${res.saved.length} file(s).` +
        (res.rejected.length ? ` Skipped: ${res.rejected.map((r) => r.filename).join(", ")}.` : ""));
    } catch (e) {
      setError(String((e as Error).message));
    }
  }

  async function remove(row: Row) {
    const name = String(row.filename ?? "this file");
    if (!confirm(`Remove ${name}? This deletes the uploaded file and its data, then rebuilds.`)) return;
    setNotice("");
    const body = new FormData();
    body.append("path", String(row.path ?? ""));
    try {
      const res = await post<{ removed: string; job: Job }>("/api/files/remove", body);
      setJob(res.job);
      setNotice(`Removing ${res.removed}…`);
    } catch (e) {
      setError(String((e as Error).message));
    }
  }

  async function rebuild() {
    setNotice("");
    const body = new FormData();
    if (label) body.append("period", label);
    const res = await post<{ job: Job }>("/api/rebuild", body);
    setJob(res.job);
  }

  async function clearAll() {
    const typed = window.prompt(
      "This moves ALL current source files to a backup folder and empties the database, " +
      "so you can upload fresh data. Files are moved, not deleted.\n\nType CLEAR to confirm.");
    if (typed !== "CLEAR") { setNotice("Clear cancelled."); return; }
    setNotice("");
    const body = new FormData();
    body.append("confirm", "CLEAR");
    try {
      const res = await post<{ moved: number; backup: string }>("/api/data/clear", body);
      setJob({ status: "done", finished_at: null,
        message: `Cleared — ${res.moved} source items moved to ${res.backup}. Upload your files above to begin.` });
      refresh();
    } catch (e) {
      setError(String((e as Error).message));
    }
  }

  if (error) return <ErrorBox error={error} />;

  return (
    <>
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Data & Uploads</h1>
          <p className="text-sm text-slate-500">
            Drop next month&apos;s exports here. Platform and report type are detected from the
            file&apos;s columns, so folder names and file names do not matter. Leave the month
            blank to detect it from the files — set it explicitly when the exports carry no
            dates of their own (Amazon, Zepto and Blinkit do not).
          </p>
          <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
            <b>Which report is which:</b> the <b>campaign</b> report is a platform&apos;s full
            billed total — upload it for every platform to get accurate headline numbers. The{" "}
            <b>product</b>, <b>keyword</b>, <b>city</b> and <b>placement</b> reports are partial
            breakdowns (only the spend attributed to that dimension), so they sum to less than the
            campaign total — that is expected. When a campaign report isn&apos;t available (e.g.
            BigBasket), set the billed total in <code>overrides.json</code>.
          </div>
        </div>
        <ExportButtons />
      </header>

      <Card className="mb-5">
        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); setStaged(Array.from(e.dataTransfer.files)); }}
          onClick={() => input.current?.click()}
          className={`cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition ${
            dragging
              ? "border-slate-900 bg-slate-100 dark:border-slate-200 dark:bg-slate-800"
              : "border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800/50"
          }`}
        >
          <div className="text-sm font-medium text-slate-700 dark:text-slate-200">
            Drop CSV, XLSX, XLS or ZIP files here, or click to choose
          </div>
          <div className="mt-1 text-xs text-slate-500">
            Set the platform and options below, then press Upload. Loading reloads this month
            only — other months already loaded are left alone.
          </div>
          <input
            ref={input}
            type="file"
            multiple
            accept=".csv,.xlsx,.xls,.zip"
            className="hidden"
            onChange={(e) => setStaged(Array.from(e.target.files ?? []))}
          />
        </div>

        <div
          className="mt-3 rounded-lg border border-slate-200 p-3 dark:border-slate-800"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Which platform is this data from?
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {["", ...PLATFORMS].map((p) => (
              <button
                key={p || "auto"}
                type="button"
                onClick={() => {
                  setPlatform(p);
                  if (p !== "Flipkart") setSubPlatform("");
                  if (p !== "Flipkart" && p !== "Zepto") setAdType("");
                }}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                  platform === p
                    ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                    : "border border-slate-300 bg-white text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
                }`}
              >
                {p || "Detect automatically"}
              </button>
            ))}
          </div>
          <p className="mt-2 text-xs text-slate-500">
            {platform
              ? `Recorded as ${platform}. The file's own columns still decide what it is — if they say something else, the columns win and the difference is flagged below.`
              : "Platform and report type are read from the file's columns, so this is optional. Choose one if a file has failed to be recognised, so it can still be attributed."}
          </p>
        </div>

        <div
          className="mt-3 rounded-lg border border-slate-200 p-3 dark:border-slate-800"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Which product is this data for?
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {["", ...PRODUCTS].map((c) => (
              <button
                key={c || "auto"}
                type="button"
                onClick={() => setCategory(c)}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                  category === c
                    ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                    : "border border-slate-300 bg-white text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
                }`}
              >
                {c || "Detect automatically"}
              </button>
            ))}
          </div>
          <p className="mt-2 text-xs text-slate-500">
            {category
              ? `Every row in these files will be labelled ${category}. Leave this off for exports that already name the product per row.`
              : "Optional. Product is otherwise read from each row — set it only when a file is entirely one product but doesn't say so."}
          </p>
        </div>

        <div
          className="mt-3 grid gap-3 sm:grid-cols-3"
          onClick={(e) => e.stopPropagation()}
        >
          {platform === "Flipkart" && (
          <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Sub-platform
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              {["", ...SUBPLATFORMS].map((s) => (
                <button
                  key={s || "auto"}
                  type="button"
                  onClick={() => setSubPlatform(s)}
                  className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                    subPlatform === s
                      ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                      : "border border-slate-300 bg-white text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
                  }`}
                >
                  {s || "Auto"}
                </button>
              ))}
            </div>
            <p className="mt-2 text-xs text-slate-500">
              Flipkart&apos;s market. Read from the folder path, which an uploaded file lacks —
              set it so Minutes vs National is right.
            </p>
          </div>
          )}

          {(platform === "Flipkart" || platform === "Zepto") && (
          <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Ad type
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              {["", ...AD_TYPES].map((a) => (
                <button
                  key={a || "auto"}
                  type="button"
                  onClick={() => setAdType(a)}
                  className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                    adType === a
                      ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                      : "border border-slate-300 bg-white text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
                  }`}
                >
                  {a || "Auto"}
                </button>
              ))}
            </div>
            <p className="mt-2 text-xs text-slate-500">
              PLA or PCA. Flipkart Minutes and National each have both, and Zepto too — set it
              alongside the sub-platform.
            </p>
          </div>
          )}

          <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Report type
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              {["", ...REPORTS].map((r) => (
                <button
                  key={r || "auto"}
                  type="button"
                  onClick={() => setReportType(r)}
                  className={`rounded-lg px-3 py-1.5 text-sm font-medium capitalize transition ${
                    reportType === r
                      ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                      : "border border-slate-300 bg-white text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
                  }`}
                >
                  {r || "Auto"}
                </button>
              ))}
            </div>
            <p className="mt-2 text-xs text-slate-500">
              Usually read from the columns — set it only to attribute a file the pipeline
              couldn&apos;t recognise. Campaign = the platform total.
            </p>
          </div>
        </div>

        {staged.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg border border-emerald-300 bg-emerald-50 p-3 dark:border-emerald-900 dark:bg-emerald-950/40">
            <span className="text-sm text-slate-700 dark:text-slate-200">
              <b>{staged.length}</b> file(s) ready
              {platform && ` · ${platform}`}{subPlatform && ` ${subPlatform}`}{adType && ` ${adType}`}
              {category && ` · ${category}`}
              <span className="ml-2 text-xs text-slate-500">
                {staged.map((f) => f.name).join(", ").slice(0, 70)}
              </span>
            </span>
            <button
              type="button"
              onClick={() => send(staged)}
              disabled={job.status === "running"}
              className="ml-auto rounded-lg bg-emerald-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              {job.status === "running" ? "Uploading…" : `Upload ${staged.length} file(s)`}
            </button>
            <button type="button" onClick={() => setStaged([])}
                    className="text-xs text-slate-500 hover:underline">
              clear
            </button>
          </div>
        )}

        <div className="mt-3 flex flex-wrap items-end gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-500" htmlFor="month">
              Month to load as
            </label>
            <input
              id="month"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="auto-detect"
              pattern="\d{4}-\d{2}"
              className="mt-1 w-36 rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900"
            />
          </div>
          <button
            onClick={rebuild}
            disabled={job.status === "running"}
            className="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
          >
            {job.status === "running" ? "Rebuilding…" : "Rebuild from input folder"}
          </button>
          {notice && <span className="text-sm text-slate-600 dark:text-slate-300">{notice}</span>}
          {job.status !== "idle" && (
            <span className="text-sm">
              <Badge tone={
                job.status === "done" ? STATUS_TONE.ok
                : job.status === "error" ? STATUS_TONE.failed : STATUS_TONE.needs_review}>
                {job.status}
              </Badge>{" "}
              <span className="text-slate-600 dark:text-slate-300">{job.message}</span>
            </span>
          )}
        </div>
      </Card>

      <Card className="mb-5" title="Months loaded">
        {available.length === 0 ? (
          <p className="text-sm text-slate-500">Nothing loaded yet.</p>
        ) : (
          <p className="text-sm text-slate-600 dark:text-slate-300">
            {available.map(periodName).join(" · ")}
            {available.length === 1 && " — load a second month to switch on comparison."}
          </p>
        )}
      </Card>

      {recon.length > 0 && (
        <Card
          className="mb-5"
          title="Billed vs tracked"
          subtitle="Your billed platform total (overrides.json) against what the uploaded reports actually sum to. A gap means the campaign report was missing or incomplete — the headline uses the billed figure."
        >
          <DataTable
            columns={[
              { key: "platform", label: "Platform" },
              { key: "billed_spend", label: "Billed Spend", align: "right", format: (v) => money(v) },
              { key: "tracked_spend", label: "Tracked Spend", align: "right", format: (v) => money(v) },
              {
                key: "gap_spend", label: "Gap", align: "right",
                format: (v) => (v === null || v === undefined ? "—" : money(v)),
                tone: (v) => (v === null || v === undefined || Math.abs(v as number) < 1
                  ? "text-slate-400" : "font-semibold text-amber-700 dark:text-amber-400"),
              },
              { key: "billed_revenue", label: "Billed Rev.", align: "right", format: (v) => money(v) },
              { key: "tracked_revenue", label: "Tracked Rev.", align: "right", format: (v) => money(v) },
              {
                key: "gap_revenue", label: "Gap", align: "right",
                format: (v) => (v === null || v === undefined ? "—" : money(v)),
                tone: (v) => (v === null || v === undefined || Math.abs(v as number) < 1
                  ? "text-slate-400" : "font-semibold text-amber-700 dark:text-amber-400"),
              },
            ]}
            rows={recon as unknown as Row[]}
            pageSize={10}
          />
        </Card>
      )}

      <Card
        className="mb-5"
        title="Uploaded files"
        subtitle="Files you added through this page. Removing one deletes it from the app and rebuilds the database without it. Original source exports are not shown here and cannot be removed."
      >
        {uploads.length === 0 ? (
          <p className="text-sm text-slate-500">Nothing uploaded through the app yet.</p>
        ) : (
          <DataTable
            columns={[
              { key: "filename", label: "File", width: "max-w-md truncate" },
              { key: "batch", label: "Uploaded" },
              { key: "size_kb", label: "Size (KB)", align: "right", format: (v) => num(v) },
              {
                key: "_remove", label: "", align: "right",
                render: (row) => (
                  <button
                    type="button"
                    onClick={() => remove(row)}
                    disabled={job.status === "running"}
                    className="rounded-lg border border-red-300 px-2.5 py-1 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-40 dark:border-red-900 dark:text-red-400 dark:hover:bg-red-950"
                  >
                    Remove
                  </button>
                ),
              },
            ]}
            rows={uploads}
            pageSize={10}
          />
        )}
      </Card>

      <Card
        title="Every file the pipeline has seen"
        subtitle="Duplicates are byte-identical copies of another file and are counted once. Anything marked needs review is an export shape not yet in the signature registry."
      >
        {files === null ? <Loading /> : (
          <DataTable
            columns={[
              { key: "filename", label: "File", width: "max-w-md truncate" },
              { key: "platform", label: "Platform" },
              { key: "sub_platform", label: "Sub-platform" },
              { key: "report_type", label: "Report type" },
              {
                key: "_role", label: "Role",
                render: (row) => {
                  if (row.report_type === "campaign")
                    return <span className="font-medium text-slate-700 dark:text-slate-200">Total</span>;
                  if (["product", "keyword", "city", "placement"].includes(String(row.report_type)))
                    return <span className="text-slate-500">Partial</span>;
                  return <span className="text-slate-400">—</span>;
                },
              },
              { key: "sheet_name", label: "Sheet" },
              { key: "category", label: "Category" },
              { key: "row_count", label: "Rows", align: "right", format: (v) => num(v) },
              {
                key: "processing_status", label: "Status",
                tone: (v) => (v === "failed" || v === "needs_review"
                  ? "font-semibold text-amber-700 dark:text-amber-400" : "text-slate-500"),
              },
              { key: "error", label: "Note", width: "max-w-md truncate" },
            ]}
            rows={files as unknown as Row[]}
          />
        )}
      </Card>

      <Card className="mt-5 border-red-200 dark:border-red-950" title="Start over">
        <p className="mb-3 text-sm text-slate-600 dark:text-slate-300">
          Move every current source file to a backup folder and empty the database, so you can
          upload fresh data through this page. Files are <b>moved, not deleted</b> — they go to
          <code className="mx-1">_backup_input_cleared</code> and can be restored.
        </p>
        <button
          type="button"
          onClick={clearAll}
          disabled={job.status === "running"}
          className="rounded-lg bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
        >
          Clear all data
        </button>
      </Card>
    </>
  );
}
