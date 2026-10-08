"use client";

import * as React from "react";

// Pass/fail uses the reserved status colors and always ships with a legend,
// a per-bar tooltip and a text alternative (the table view lives in Reports).
const GOOD = "#0ca30c";
const CRITICAL = "#d03b3b";

export function TrendChart({ data, height = 180 }: { data: { date: string; passed: number; failed: number }[]; height?: number }) {
  const [hover, setHover] = React.useState<number | null>(null);
  const max = Math.max(1, ...data.map((d) => d.passed + d.failed));
  const width = 640;
  const padL = 32, padB = 22, padT = 8;
  const plotH = height - padB - padT;
  const slot = (width - padL) / data.length;
  const barW = Math.min(22, slot * 0.6);
  const ticks = niceTicks(max);
  const y = (v: number) => padT + plotH - (v / ticks[ticks.length - 1]) * plotH;
  const total = data.reduce((a, d) => a + d.passed + d.failed, 0);

  return (
    <div className="relative">
      <div className="mb-2 flex items-center gap-4 text-xs text-muted-foreground" aria-hidden>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: GOOD }} />Passed</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: CRITICAL }} />Failed</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img"
        aria-label={`Test results per day for the last ${data.length} days: ${total} results in total`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={width} y1={y(t)} y2={y(t)} stroke="hsl(var(--border))" strokeWidth={1} strokeDasharray={t === 0 ? undefined : "2 3"} />
            <text x={padL - 6} y={y(t) + 3.5} textAnchor="end" fontSize={10} fill="hsl(var(--muted-foreground))" className="tabular">{t}</text>
          </g>
        ))}
        {data.map((d, i) => {
          const x = padL + i * slot + (slot - barW) / 2;
          const failedH = (d.failed / ticks[ticks.length - 1]) * plotH;
          const passedH = (d.passed / ticks[ticks.length - 1]) * plotH;
          const base = y(0);
          const gap = d.failed && d.passed ? 2 : 0;
          return (
            <g key={d.date} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={padL + i * slot} y={padT} width={slot} height={plotH} fill={hover === i ? "hsl(var(--muted))" : "transparent"} />
              {d.passed > 0 && <path d={roundedTop(x, base - passedH, barW, passedH, d.failed ? 0 : 3)} fill={GOOD} />}
              {d.failed > 0 && <path d={roundedTop(x, base - passedH - failedH - gap, barW, failedH, 3)} fill={CRITICAL} />}
              {(i % Math.ceil(data.length / 7) === 0 || i === data.length - 1) && (
                <text x={x + barW / 2} y={height - 6} textAnchor="middle" fontSize={10} fill="hsl(var(--muted-foreground))">
                  {new Date(d.date + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      {hover !== null && (
        <div className="pointer-events-none absolute top-6 rounded-md border bg-card px-2.5 py-1.5 text-xs shadow-md"
          style={{ left: `${Math.min(85, ((padL + hover * slot) / width) * 100)}%` }}>
          <p className="font-medium">{new Date(data[hover].date + "T00:00:00").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}</p>
          <p className="tabular text-muted-foreground"><span style={{ color: GOOD }}>■</span> {data[hover].passed} passed</p>
          <p className="tabular text-muted-foreground"><span style={{ color: CRITICAL }}>■</span> {data[hover].failed} failed</p>
        </div>
      )}
    </div>
  );
}

function roundedTop(x: number, y: number, w: number, h: number, r: number): string {
  if (h <= 0) return "";
  r = Math.min(r, h, w / 2);
  return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`;
}

function niceTicks(max: number): number[] {
  const step = max <= 4 ? 1 : max <= 10 ? 2 : Math.pow(10, Math.floor(Math.log10(max))) * (max / Math.pow(10, Math.floor(Math.log10(max))) > 5 ? 2 : 1);
  const top = Math.ceil(max / step) * step;
  const out = [];
  for (let v = 0; v <= top; v += step) out.push(v);
  return out;
}

export function CategoryBars({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  if (!entries.length) return <p className="text-sm text-muted-foreground">No failures in this period.</p>;
  return (
    <ul className="grid gap-2.5" aria-label="Failures by category">
      {entries.map(([label, value]) => (
        <li key={label} className="grid grid-cols-[minmax(0,10rem)_1fr_2.5rem] items-center gap-3 text-sm" title={`${label}: ${value}`}>
          <span className="truncate text-muted-foreground">{label}</span>
          <span className="h-2 rounded-r-full bg-muted">
            <span className="block h-2 rounded-r-full bg-primary" style={{ width: `${(value / max) * 100}%` }} />
          </span>
          <span className="tabular text-right font-medium">{value}</span>
        </li>
      ))}
    </ul>
  );
}
