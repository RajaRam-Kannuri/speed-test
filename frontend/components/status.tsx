import { AlertTriangle, Ban, CheckCircle2, CircleDashed, Clock, Loader2, RotateCcw, XCircle } from "lucide-react";
import { Badge } from "@/components/ui";

// Status always pairs color with an icon and a word, never color alone.
const MAP: Record<string, { label: string; variant: "good" | "critical" | "warning" | "default" | "primary"; icon: React.ElementType; spin?: boolean }> = {
  passed: { label: "Passed", variant: "good", icon: CheckCircle2 },
  failed: { label: "Failed", variant: "critical", icon: XCircle },
  error: { label: "Error", variant: "critical", icon: AlertTriangle },
  flaky: { label: "Flaky", variant: "warning", icon: RotateCcw },
  queued: { label: "Queued", variant: "default", icon: Clock },
  running: { label: "Running", variant: "primary", icon: Loader2, spin: true },
  cancelling: { label: "Cancelling", variant: "default", icon: Loader2, spin: true },
  cancelled: { label: "Cancelled", variant: "default", icon: Ban },
  skipped: { label: "Skipped", variant: "default", icon: CircleDashed },
  completed: { label: "Completed", variant: "good", icon: CheckCircle2 },
  generated: { label: "Generated", variant: "primary", icon: CircleDashed },
  draft: { label: "Draft", variant: "default", icon: CircleDashed },
  ready: { label: "Ready", variant: "good", icon: CheckCircle2 },
  archived: { label: "Archived", variant: "default", icon: Ban },
  valid: { label: "Valid", variant: "good", icon: CheckCircle2 },
  warnings: { label: "Warnings", variant: "warning", icon: AlertTriangle },
  invalid: { label: "Invalid", variant: "critical", icon: XCircle },
  unvalidated: { label: "Not validated", variant: "default", icon: CircleDashed },
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const s = MAP[status] ?? { label: status, variant: "default" as const, icon: CircleDashed };
  const Icon = s.icon;
  return (
    <Badge variant={s.variant} className={className}>
      <Icon className={`h-3 w-3 ${s.spin ? "animate-spin" : ""}`} aria-hidden />
      {s.label}
    </Badge>
  );
}

export function CategoryBadge({ category }: { category: string }) {
  const label = category.charAt(0).toUpperCase() + category.slice(1);
  return <Badge variant="outline">{label}</Badge>;
}

export function PriorityDot({ priority }: { priority: string }) {
  const color = priority === "high" ? "bg-critical" : priority === "medium" ? "bg-warning" : "bg-muted-foreground/40";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className={`h-1.5 w-1.5 rounded-full ${color}`} aria-hidden />
      {priority.charAt(0).toUpperCase() + priority.slice(1)}
    </span>
  );
}
