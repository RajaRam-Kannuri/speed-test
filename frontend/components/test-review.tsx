"use client";

import { ChevronDown, ChevronRight, ExternalLink } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import useSWR from "swr";
import { RunButton } from "@/components/run-controls";
import { CategoryBadge, PriorityDot, StatusBadge } from "@/components/status";
import { StepList } from "@/components/step-list";
import { Badge, Spinner } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { fetcher } from "@/lib/api";
import type { TestCase } from "@/lib/types";

const BASIS: Record<string, { label: string; hint: string }> = {
  discovered: { label: "Observed", hint: "Expectation is what discovery observed on the site (a regression baseline)." },
  confirmed: { label: "Confirmed", hint: "Expectation was verified during discovery." },
  inferred: { label: "Inferred", hint: "A reasonable assumption. Review it before relying on the result." },
  specified: { label: "From spec", hint: "Expectation comes from the API specification or your instructions." },
};

function Expanded({ id }: { id: string }) {
  const { project } = useWorkspace();
  const { data } = useSWR<TestCase>(project ? `/projects/${project.id}/test-cases/${id}` : null, fetcher);
  if (!data) return <div className="p-4"><Spinner /></div>;
  return (
    <div className="grid gap-3 bg-muted/30 px-4 py-3">
      {data.description && <p className="text-sm text-muted-foreground">{data.description}</p>}
      <StepList steps={data.steps ?? []} messages={data.validation_messages} />
      <Link href={`/tests/${id}`} className="inline-flex items-center gap-1 text-sm text-primary hover:underline">Open in editor <ExternalLink className="h-3.5 w-3.5" /></Link>
    </div>
  );
}

export function TestReview({ ids, heading }: { ids: string[]; heading?: React.ReactNode }) {
  const { project } = useWorkspace();
  const { data: all } = useSWR<TestCase[]>(project ? `/projects/${project.id}/test-cases` : null, fetcher);
  const cases = React.useMemo(() => (all ?? []).filter((c) => ids.includes(c.id)), [all, ids]);
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [open, setOpen] = React.useState<string | null>(null);
  const initialised = React.useRef(false);

  React.useEffect(() => {
    if (!initialised.current && cases.length) {
      initialised.current = true;
      setSelected(new Set(cases.filter((c) => c.validation_status !== "invalid").map((c) => c.id)));
    }
  }, [cases]);

  if (!all) return <div className="py-8"><Spinner /></div>;
  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const allSelected = cases.length > 0 && cases.every((c) => selected.has(c.id) || c.validation_status === "invalid");

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>{heading}</div>
        <RunButton testCaseIds={[...selected]} />
      </div>
      <div className="overflow-hidden rounded-lg border bg-card">
        <table className="w-full text-sm" data-testid="generated-tests">
          <thead>
            <tr className="border-b bg-muted/40 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <th className="w-10 px-3 py-2">
                <input type="checkbox" aria-label="Select all" checked={allSelected}
                  onChange={() => setSelected(allSelected ? new Set() : new Set(cases.filter((c) => c.validation_status !== "invalid").map((c) => c.id)))} />
              </th>
              <th className="px-3 py-2">Test case</th>
              <th className="px-3 py-2">Category</th>
              <th className="hidden px-3 py-2 md:table-cell">Priority</th>
              <th className="hidden px-3 py-2 lg:table-cell">Expectation</th>
              <th className="px-3 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {cases.map((c) => (
              <React.Fragment key={c.id}>
                <tr className="border-b last:border-0 hover:bg-muted/30">
                  <td className="px-3 py-2.5">
                    <input type="checkbox" aria-label={`Select ${c.title}`} checked={selected.has(c.id)} disabled={c.validation_status === "invalid"} onChange={() => toggle(c.id)} />
                  </td>
                  <td className="px-3 py-2.5">
                    <button className="flex items-center gap-1.5 text-left font-medium hover:text-primary" onClick={() => setOpen(open === c.id ? null : c.id)} aria-expanded={open === c.id}>
                      {open === c.id ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
                      {c.title}
                    </button>
                    <span className="ml-5 text-xs text-muted-foreground">{c.step_count} steps · {c.kind === "api" ? "API" : "Browser"}{c.tags.includes("ai") ? " · AI-proposed" : ""}</span>
                  </td>
                  <td className="px-3 py-2.5"><CategoryBadge category={c.category} /></td>
                  <td className="hidden px-3 py-2.5 md:table-cell"><PriorityDot priority={c.priority} /></td>
                  <td className="hidden px-3 py-2.5 lg:table-cell"><Badge variant={c.expectation_basis === "inferred" ? "warning" : "outline"} title={BASIS[c.expectation_basis]?.hint}>{BASIS[c.expectation_basis]?.label ?? c.expectation_basis}</Badge></td>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-wrap gap-1">
                      {c.last_result ? <Link href={`/runs/${c.last_result.execution_id}`}><StatusBadge status={c.last_result.status} /></Link> : <StatusBadge status={c.status} />}
                      {c.validation_status === "invalid" && <StatusBadge status="invalid" />}
                    </div>
                  </td>
                </tr>
                {open === c.id && <tr className="border-b"><td colSpan={6} className="p-0"><Expanded id={c.id} /></td></tr>}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        &ldquo;Generated&rdquo; tests have not run yet. Results appear only after a real run. Expectation shows where each check comes from; review &ldquo;Inferred&rdquo; ones.
      </p>
    </div>
  );
}
