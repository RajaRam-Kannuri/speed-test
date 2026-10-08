"use client";

import { Download, FileText } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import useSWR from "swr";
import { CategoryBars, TrendChart } from "@/components/charts";
import { StatusBadge } from "@/components/status";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, EmptyState, PageHeader, Select, Spinner } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { fetcher } from "@/lib/api";
import type { Dashboard, Execution } from "@/lib/types";
import { formatDuration, timeAgo } from "@/lib/utils";

export default function ReportsPage() {
  const { project, orgId } = useWorkspace();
  const [days, setDays] = React.useState(14);
  const [showTable, setShowTable] = React.useState(false);
  const { data } = useSWR<Dashboard>(project ? `/organizations/${orgId}/dashboard?project_id=${project.id}&days=${days}` : null, fetcher);
  const { data: runs } = useSWR<Execution[]>(project ? `/projects/${project.id}/executions?limit=30` : null, fetcher);
  if (!project) return <EmptyState title="Create a project first" />;
  return (
    <div className="grid gap-6">
      <PageHeader title="Reports" description="Trends and downloadable reports built from persisted run data."
        actions={<Select aria-label="Period" className="w-36" value={days} onChange={(e) => setDays(Number(e.target.value))}>{[7, 14, 30, 90].map((d) => <option key={d} value={d}>Last {d} days</option>)}</Select>} />
      {!data ? <Spinner /> : (
        <>
          <div className="grid gap-6 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader>
                <div><CardTitle>Pass and fail trend</CardTitle><CardDescription>Pass rate {data.pass_rate === null ? "–" : `${data.pass_rate}%`} over {data.results.total} results</CardDescription></div>
                <button className="text-sm text-primary hover:underline" onClick={() => setShowTable((s) => !s)}>{showTable ? "Show chart" : "Show table"}</button>
              </CardHeader>
              <CardContent>
                {showTable ? (
                  <table className="w-full text-sm"><thead><tr className="text-left text-xs text-muted-foreground"><th className="py-1">Date</th><th>Passed</th><th>Failed</th></tr></thead>
                    <tbody className="tabular">{data.trend.map((d) => <tr key={d.date} className="border-t"><td className="py-1">{d.date}</td><td>{d.passed}</td><td>{d.failed}</td></tr>)}</tbody></table>
                ) : <TrendChart data={data.trend} />}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><div><CardTitle>Failure categories</CardTitle><CardDescription>Automated classification of failed results</CardDescription></div></CardHeader>
              <CardContent><CategoryBars data={data.failure_categories} /></CardContent>
            </Card>
          </div>
          <Card>
            <CardHeader><div><CardTitle>Flaky tests</CardTitle><CardDescription>Tests that passed only on retry, or alternate between pass and fail</CardDescription></div></CardHeader>
            <CardContent>
              {data.flaky_tests.length ? (
                <table className="w-full text-sm"><thead><tr className="text-left text-xs text-muted-foreground"><th className="py-1">Test</th><th>Runs</th><th>Passed</th><th>Failed</th></tr></thead>
                  <tbody className="tabular">{data.flaky_tests.map((f) => <tr key={f.test_case_id} className="border-t"><td className="py-1.5"><Link href={`/tests/${f.test_case_id}`} className="hover:underline">{f.title}</Link></td><td>{f.runs}</td><td>{f.passed}</td><td>{f.failed}</td></tr>)}</tbody></table>
              ) : <p className="text-sm text-muted-foreground">No flaky tests detected in this period.</p>}
            </CardContent>
          </Card>
        </>
      )}
      <Card>
        <CardHeader><div><CardTitle>Run reports</CardTitle><CardDescription>HTML and PDF reports with screenshots and analysis; Allure-compatible results for existing pipelines</CardDescription></div></CardHeader>
        <CardContent className="px-0 pb-1">
          {!runs ? <div className="px-5"><Spinner /></div> : runs.length === 0 ? <p className="px-5 pb-4 text-sm text-muted-foreground">No runs yet.</p> : (
            <table className="w-full text-sm">
              <tbody>
                {runs.filter((r) => !["queued", "running", "cancelling"].includes(r.status)).map((r) => (
                  <tr key={r.id} className="border-t">
                    <td className="px-5 py-2"><StatusBadge status={r.status} /></td>
                    <td className="px-3 py-2"><Link href={`/runs/${r.id}`} className="tabular hover:underline">{r.passed}/{r.total} passed</Link></td>
                    <td className="hidden px-3 py-2 text-muted-foreground md:table-cell">{r.browser} · {formatDuration(r.duration_ms)}</td>
                    <td className="px-3 py-2 text-muted-foreground">{timeAgo(r.created_at)}</td>
                    <td className="px-5 py-2 text-right">
                      <div className="flex justify-end gap-3">
                        <a className="inline-flex items-center gap-1 text-primary hover:underline" href={`/api/executions/${r.id}/report?format=html`}><FileText className="h-3.5 w-3.5" /> HTML</a>
                        <a className="inline-flex items-center gap-1 text-primary hover:underline" href={`/api/executions/${r.id}/report?format=pdf`}><Download className="h-3.5 w-3.5" /> PDF</a>
                        <a className="text-primary hover:underline" href={`/api/executions/${r.id}/report?format=allure`}>Allure</a>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
