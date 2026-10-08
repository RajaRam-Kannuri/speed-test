import { AlertTriangle, Info, XCircle } from "lucide-react";
import type { Step, ValidationMessage } from "@/lib/types";
import { describeTarget } from "@/lib/utils";

const ACTION_LABEL: Record<string, string> = {
  navigate: "Navigate", click: "Click", fill: "Type", select: "Select", check: "Check", uncheck: "Uncheck", press: "Press",
  wait_for: "Wait for", wait_ms: "Wait", assert_visible: "Assert visible", assert_hidden: "Assert hidden", assert_text: "Assert text",
  assert_no_text: "Assert no text", assert_value: "Assert value", assert_count: "Assert count", assert_url: "Assert URL",
  assert_url_not: "Assert URL changed", assert_title: "Assert title", screenshot: "Screenshot", store_text: "Extract",
  set_variable: "Store variable", api_request: "API request",
};

export function actionLabel(a: string) {
  return ACTION_LABEL[a] ?? a;
}

export function stepSummary(s: Step): string {
  if (s.action === "api_request") {
    const exp = s.options?.expect ?? {};
    const status = exp.status ? `expect ${exp.status.join("/")}` : exp.status_range ? `expect ${exp.status_range[0]}–${exp.status_range[1]}` : "";
    return `${s.options?.method ?? "GET"} ${s.options?.url ?? ""} ${status}${exp.schema ? " + schema" : ""}`;
  }
  const parts = [describeTarget(s.target)];
  if (s.value) parts.push(s.action === "fill" || s.action.startsWith("assert") ? `"${s.value}"` : s.value);
  if (s.action === "set_variable") parts.unshift(`${s.options?.name} =`);
  return parts.filter(Boolean).join(" ");
}

export function MessageIcon({ level }: { level: string }) {
  if (level === "error") return <XCircle className="h-3.5 w-3.5 shrink-0 text-critical" aria-label="Error" />;
  if (level === "warning") return <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-[#a87000]" aria-label="Warning" />;
  return <Info className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-label="Note" />;
}

export function StepList({ steps, messages = [], failedIndex }: { steps: Step[]; messages?: ValidationMessage[]; failedIndex?: number | null }) {
  const general = messages.filter((m) => m.step === null && m.level !== "info");
  return (
    <div className="grid gap-2">
      <ol className="grid gap-1">
        {steps.map((s, i) => {
          const msgs = messages.filter((m) => m.step === i + 1 && m.level !== "info");
          return (
            <li key={i} className={`rounded-md border bg-card px-3 py-2 text-sm ${failedIndex === i ? "border-critical/60 bg-[#fdf3f3]" : ""}`}>
              <div className="flex items-baseline gap-2">
                <span className="tabular w-5 shrink-0 text-xs text-muted-foreground">{i + 1}</span>
                <span className="shrink-0 font-medium">{actionLabel(s.action)}</span>
                <span className="min-w-0 truncate font-mono text-[12.5px] text-muted-foreground">{stepSummary(s)}</span>
              </div>
              {s.description && <p className="ml-7 text-xs text-muted-foreground">{s.description}</p>}
              {msgs.map((m, j) => <p key={j} className="ml-7 mt-1 flex items-center gap-1 text-xs"><MessageIcon level={m.level} />{m.message}</p>)}
            </li>
          );
        })}
      </ol>
      {general.map((m, j) => <p key={j} className="flex items-center gap-1.5 text-xs"><MessageIcon level={m.level} />{m.message}</p>)}
    </div>
  );
}
