"use client";

import { PlayCircle } from "lucide-react";
import Link from "next/link";
import useSWR from "swr";
import { StatusBadge } from "@/components/status";
import { EmptyState, PageHeader, Spinner } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { fetcher } from "@/lib/api";
import type { Execution } from "@/lib/types";
import { ACTIVE_STATUSES, formatDuration, timeAgo } from "@/lib/utils";

export default function RunsPage() {
  const { project } = useWorkspace();
  const { data } = useSWR<Execution[]>(project ? `/projects/${project.id}/executions` : null, fetcher, {
    refreshInterval: (d) => (d?.some((e) => ACTIVE_STATUSES.includes(e.status)) ? 2000 : 15000),
  });
  if (!project) return <EmptyState title="Create a project first" />;
  return (
    <div>
      <PageHeader title="Runs" description="Every execution with its real outcome. Runs execute in isolated cloud browsers." />
      {!data ? <Spinner /> : data.length === 0 ? (
        <EmptyState icon={<PlayCircle className="h-6 w-6" />} title="No runs yet" description="Select tests on the Tests page and choose Run." />
      ) : (
        <div className="overflow-hidden rounded-lg border bg-card">
          <table className="w-full text-sm" data-testid="runs-table">
            <thead>
              <tr className="border-b bg-muted/40 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                <th className="px-4 py-2">Status</th><th className="px-4 py-2">Result</th><th className="hidden px-4 py-2 md:table-cell">Browser</th>
                <th className="hidden px-4 py-2 md:table-cell">Trigger</th><th className="px-4 py-2">Duration</th><th className="px-4 py-2">Started</th>
              </tr>
            </thead>
            <tbody>
              {data.map((e) => (
                <tr key={e.id} className="border-b last:border-0 hover:bg-muted/30">
                  <td className="px-4 py-2.5"><Link href={`/runs/${e.id}`}><StatusBadge status={e.status} /></Link></td>
                  <td className="px-4 py-2.5">
                    <Link href={`/runs/${e.id}`} className="tabular hover:text-primary">{e.passed}/{e.total} passed{e.failed ? `, ${e.failed} failed` : ""}{e.flaky ? `, ${e.flaky} flaky` : ""}</Link>
                    <span className="block font-mono text-[11px] text-muted-foreground">{e.id.slice(0, 8)}</span>
                  </td>
                  <td className="hidden px-4 py-2.5 md:table-cell">{e.browser}{e.workers > 1 ? ` · ${e.workers} workers` : ""}</td>
                  <td className="hidden px-4 py-2.5 capitalize md:table-cell">{e.trigger}</td>
                  <td className="px-4 py-2.5">{formatDuration(e.duration_ms)}</td>
                  <td className="px-4 py-2.5 text-muted-foreground">{timeAgo(e.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
