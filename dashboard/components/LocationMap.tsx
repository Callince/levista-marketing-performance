"use client";

import { useMemo, useState } from "react";
import states from "@/lib/india-states.json";
import coords from "@/lib/city-coords.json";
import { Row, money, num, pct } from "@/lib/api";

// JSON imports widen [lat, lng] to number[], so assert through unknown.
const COORDS = coords as unknown as Record<string, [number, number]>;
const STATES = states as unknown as {
  features: { properties: { state: string }; geometry: { coordinates: number[][][][] } }[];
};

const WIDTH = 620;
const HEIGHT = 660;
const PAD = 12;

// Equirectangular with a standard parallel through central India. Without the
// cos() term the country comes out noticeably stretched east-to-west.
const STANDARD_PARALLEL = (23 * Math.PI) / 180;
const LON_SCALE = Math.cos(STANDARD_PARALLEL);

const BOUNDS = (() => {
  let minLon = 180, maxLon = -180, minLat = 90, maxLat = -90;
  for (const f of STATES.features) {
    for (const poly of f.geometry.coordinates) {
      for (const ring of poly) {
        for (const [lon, lat] of ring) {
          if (lon < minLon) minLon = lon;
          if (lon > maxLon) maxLon = lon;
          if (lat < minLat) minLat = lat;
          if (lat > maxLat) maxLat = lat;
        }
      }
    }
  }
  return { minLon, maxLon, minLat, maxLat };
})();

const SPAN_X = (BOUNDS.maxLon - BOUNDS.minLon) * LON_SCALE;
const SPAN_Y = BOUNDS.maxLat - BOUNDS.minLat;
const SCALE = Math.min((WIDTH - PAD * 2) / SPAN_X, (HEIGHT - PAD * 2) / SPAN_Y);
const OFFSET_X = (WIDTH - SPAN_X * SCALE) / 2;
const OFFSET_Y = (HEIGHT - SPAN_Y * SCALE) / 2;

function project(lon: number, lat: number): [number, number] {
  return [
    OFFSET_X + (lon - BOUNDS.minLon) * LON_SCALE * SCALE,
    OFFSET_Y + (BOUNDS.maxLat - lat) * SCALE,
  ];
}

const STATE_PATHS = STATES.features.map((f) => ({
  state: f.properties.state,
  d: f.geometry.coordinates
    .map((poly) =>
      poly
        .map((ring) =>
          ring
            .map(([lon, lat], i) => {
              const [x, y] = project(lon, lat);
              return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
            })
            .join("") + "Z")
        .join(""))
    .join(""),
}));

/** Return bands, matching the traffic lights used everywhere else. */
function tone(roas: number | null) {
  if (roas === null || roas === undefined) return { fill: "#94a3b8", label: "no return data" };
  if (roas >= 3) return { fill: "#2E7D32", label: "healthy (₹3+)" };
  if (roas >= 1) return { fill: "#F59E0B", label: "break-even (₹1–3)" };
  return { fill: "#C62828", label: "losing money (under ₹1)" };
}

type Point = {
  city: string; lat: number; lon: number; revenue: number; spend: number;
  orders: number; roas: number | null; platforms: string[];
};

export default function LocationMap({ rows, metric = "revenue" }: {
  rows: Row[]; metric?: "revenue" | "spend" | "orders";
}) {
  const [hover, setHover] = useState<Point | null>(null);

  const { points, unmapped, unmappedRevenue } = useMemo(() => {
    // Rows arrive per platform; one dot per city, so a city served by two platforms
    // is one bubble carrying the combined figures.
    const merged = new Map<string, Point>();
    const missing = new Map<string, number>();

    for (const row of rows) {
      const city = String(row.city ?? "");
      const revenue = (row.revenue as number) ?? 0;
      const at = COORDS[city];
      if (!at) {
        missing.set(city, (missing.get(city) ?? 0) + revenue);
        continue;
      }
      const existing = merged.get(city);
      const platform = String(row.platform ?? "");
      if (existing) {
        existing.revenue += revenue;
        existing.spend += (row.spend as number) ?? 0;
        existing.orders += (row.orders as number) ?? 0;
        if (platform && !existing.platforms.includes(platform)) existing.platforms.push(platform);
      } else {
        merged.set(city, {
          city, lat: at[0], lon: at[1], revenue,
          spend: (row.spend as number) ?? 0,
          orders: (row.orders as number) ?? 0,
          roas: null, platforms: platform ? [platform] : [],
        });
      }
    }
    const list = [...merged.values()];
    for (const p of list) p.roas = p.spend > 0 ? p.revenue / p.spend : null;
    list.sort((a, b) => b[metric] - a[metric]);
    return {
      points: list,
      unmapped: [...missing.keys()],
      unmappedRevenue: [...missing.values()].reduce((a, b) => a + b, 0),
    };
  }, [rows, metric]);

  const largest = Math.max(...points.map((p) => p[metric]), 1);
  // Area, not radius, tracks the value — a radius scale exaggerates big cities.
  const radius = (value: number) => 3 + Math.sqrt(Math.max(value, 0) / largest) * 26;

  if (points.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-700">
        No city has coordinates for this selection.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 lg:flex-row">
      <div className="relative shrink-0">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-auto w-full max-w-[620px]"
             role="img" aria-label="Revenue by city across India">
          <g>
            {STATE_PATHS.map((s) => (
              <path key={s.state} d={s.d}
                    className="fill-slate-100 stroke-slate-300 dark:fill-slate-800 dark:stroke-slate-700"
                    strokeWidth={0.6} />
            ))}
          </g>
          <g>
            {points.map((p) => {
              const [x, y] = project(p.lon, p.lat);
              const { fill } = tone(p.roas);
              return (
                <circle
                  key={p.city}
                  cx={x} cy={y} r={radius(p[metric])}
                  fill={fill} fillOpacity={hover && hover.city !== p.city ? 0.25 : 0.6}
                  stroke={fill} strokeWidth={1}
                  onMouseEnter={() => setHover(p)}
                  onMouseLeave={() => setHover(null)}
                  className="cursor-pointer transition-opacity"
                >
                  <title>{`${p.city}: ${money(p.revenue)}`}</title>
                </circle>
              );
            })}
          </g>
        </svg>

        {hover && (
          <div className="pointer-events-none absolute left-2 top-2 rounded-lg border border-slate-200 bg-white/95 p-3 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-900/95">
            <div className="text-sm font-bold text-slate-900 dark:text-white">{hover.city}</div>
            <div className="mt-1 space-y-0.5 text-slate-600 dark:text-slate-300">
              <div>Revenue <b>{money(hover.revenue)}</b></div>
              <div>Spend <b>{money(hover.spend)}</b></div>
              <div>Orders <b>{num(hover.orders)}</b></div>
              <div>ROAS <b>{hover.roas === null ? "—" : `₹${hover.roas.toFixed(2)}`}</b></div>
              <div className="text-slate-400">{hover.platforms.join(", ")}</div>
            </div>
          </div>
        )}
      </div>

      <div className="min-w-0 flex-1 space-y-3">
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Bubble colour — return on spend
          </p>
          <div className="space-y-1">
            {[3, 1.5, 0.5, null].map((v, i) => {
              const t = tone(v);
              return (
                <div key={i} className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
                  <span className="inline-block h-3 w-3 rounded-full"
                        style={{ backgroundColor: t.fill, opacity: 0.7 }} />
                  {t.label}
                </div>
              );
            })}
          </div>
          <p className="mt-2 text-xs text-slate-500">
            Bubble size is {metric} — area scales with the value, so a city twice as big
            has twice the ink.
          </p>
        </div>

        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Top cities
          </p>
          <table className="w-full text-xs">
            <tbody>
              {points.slice(0, 10).map((p) => (
                <tr key={p.city}
                    onMouseEnter={() => setHover(p)} onMouseLeave={() => setHover(null)}
                    className="cursor-pointer border-b border-slate-100 last:border-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50">
                  <td className="py-1 pr-2">
                    <span className="mr-1.5 inline-block h-2 w-2 rounded-full"
                          style={{ backgroundColor: tone(p.roas).fill }} />
                    {p.city}
                  </td>
                  <td className="py-1 text-right tabular-nums">{money(p.revenue)}</td>
                  <td className="py-1 pl-2 text-right tabular-nums text-slate-500">
                    {p.roas === null ? "—" : `₹${p.roas.toFixed(2)}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {unmapped.length > 0 && (
          <p className="text-xs text-amber-700 dark:text-amber-400">
            Not on the map: {unmapped.join(", ")}
            {unmappedRevenue > 0 && (
              <>
                {" "}— {money(unmappedRevenue)}{" "}
                ({pct(unmappedRevenue /
                  (unmappedRevenue + points.reduce((t, p) => t + p.revenue, 0)))} of located
                revenue)
              </>
            )}
            . These name a district or region rather than one point.
          </p>
        )}
      </div>
    </div>
  );
}
