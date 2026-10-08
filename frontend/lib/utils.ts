import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "–";
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "–";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function describeTarget(t: { strategy: string; value: string; name?: string } | null | undefined): string {
  if (!t) return "";
  if (t.strategy === "role") return t.name ? `${t.value} "${t.name}"` : t.value;
  const labels: Record<string, string> = { label: "field", text: "text", placeholder: "placeholder", testid: "test id", css: "selector" };
  return `${labels[t.strategy] ?? t.strategy} "${t.value}"`;
}

export const ACTIVE_STATUSES = ["queued", "running", "cancelling"];
