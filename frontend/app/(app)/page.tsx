"use client";

import { AlertTriangle, ArrowRight, Lightbulb, RotateCcw } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import useSWR from "swr";
import { CategoryBars, TrendChart } from "@/components/charts";
import { CreateOptions } from "@/components/create-test-dialog";
import { NewProjectForm } from "@/components/new-project-dialog";
import { StatusBadge } from "@/components/status";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, EmptyState, Select, Spinner } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { fetcher } from "@/lib/api";
import type { Dashboard } from "@/lib/types";
import { formatDuration, timeAgo } from "@/lib/utils";

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border bg-card px-4 py-3.5">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className="tabular mt-1 text-2xl font-semibold tracking-tight">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export default function DashboardPage() {
  const { project, orgId, projects, me } = useWorkspace();
  const [scope, setScope] = React.useState<"project" | "all">("project");
  const query = scope === "project" && project ? `?project_id=${project.id}` : "";
  const { data, isLoading } = useSWR<Dashboard>(project || scope === "all" ? `/organizations/${orgId}/dashboard${query}` : null, fetcher, { refreshInterval: 10000 });

  if (!projects.length) {
    return (
      <div className="mx-auto max-w-xl py-6">
        <h1 className="text-xl font-semibold">Welcome, {me.name.split(" ")[0]}</h1>
        <p className="mb-6 mt-1 text-sm text-muted-foreground">Create a project for the application you want to test. You can add more later.</p>
        <Card><CardContent className="pt-6"><NewProjectForm /></CardContent></Card>
      </div>
    );
  }

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
          <p className="mt-1 text-sm text-muted-foreground">Real results from your test runs. Nothing here is estimated.</p>
        </div>
        <div className="w-48">
          <Select aria-label="Dashboard scope" value={scope} onChange={(e) => setScope(e.target.value as "project" | "all")}>
            <option value="project">This project</option>
            <option value="all">All projects</option>
          </Select>
        </div>
      </div>

      {isLoading || !data ? (
        <div className="flex h-40 items-center justify-center"><Spinner /></div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
            <Stat label="Projects" value={scope === "all" ? data.projects : projects.length} />
            <Stat label="Test cases" value={data.tests} />
            <Stat label="Runs" value={data.executions} />
            <Stat label="Tests passed" value={data.results.passed} />
            <Stat label="Tests failed" value={data.results.failed} />
            <Stat label="Pass rate" value={data.pass_rate === null ? "–" : `${data.pass_rate}%`} hint={data.results.total ? `${data.results.total} results` : "No runs yet"} />
          </div>

          {data.tests === 0 && (
            <Card>
              <CardHeader><div><CardTitle>Create your first test</CardTitle><CardDescription>Pick one. Generated tests are shown for review before anything runs.</CardDescription></div></CardHeader>
              <CardContent><CreateOptions /></CardContent>
            </Card>
          )}

          <div className="grid gap-6 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader><div><CardTitle>Results over the last 14 days</CardTitle><CardDescription>Test results per day</CardDescription></div></CardHeader>
              <CardContent>
                {data.results.total ? <TrendChart data={data.trend} /> : <p className="py-10 text-center text-sm text-muted-foreground">Run a test to see trends here.</p>}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><div><CardTitle>Failure categories</CardTitle><CardDescription>Automated analysis, last 14 days</CardDescription></div></CardHeader>
              <CardContent><CategoryBars data={data.failure_categories} /></CardContent>
            </Card>
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>Recent runs</CardTitle>
                <Link href="/runs" className="flex items-center gap-1 text-sm text-primary hover:underline">All runs <ArrowRight className="h-3.5 w-3.5" /></Link>
              </CardHeader>
              <CardContent className="px-0 pb-2">
                {data.recent.length === 0 ? (
                  <div className="px-5 pb-4"><EmptyState title="No runs yet" description="Select tests on the Tests page and choose Run." /></div>
                ) : (
                  <ul className="divide-y">
                    {data.recent.map((r) => (
                      <li key={r.id}>
                        <Link href={`/runs/${r.id}`} className="flex items-center gap-3 px-5 py-2.5 text-sm hover:bg-muted/60">
                          <StatusBadge status={r.status} />
                          <span className="tabular">{r.passed}/{r.total} passed</span>
                          <span className="text-muted-foreground">{r.browser}</span>
                          <span className="ml-auto text-xs text-muted-foreground">{formatDuration(r.duration_ms)} · {timeAgo(r.created_at)}</span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
            <div className="grid content-start gap-6">
              <Card>
                <CardHeader><CardTitle className="flex items-center gap-1.5"><AlertTriangle className="h-4 w-4 text-critical" /> Critical failures</CardTitle></CardHeader>
                <CardContent>
                  {data.critical_failures.length ? (
                    <ul className="grid gap-2 text-sm">
                      {data.critical_failures.map((c) => (
                        <li key={c.test_case_id}><Link className="hover:underline" href={`/runs/${c.execution_id}`}>{c.title}</Link><span className="block text-xs text-muted-foreground">{c.category}</span></li>
                      ))}
                    </ul>
                  ) : <p className="text-sm text-muted-foreground">No high-priority test is failing.</p>}
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle className="flex items-center gap-1.5"><RotateCcw className="h-4 w-4 text-[#8a5b00]" /> Flaky tests</CardTitle></CardHeader>
                <CardContent>
                  {data.flaky_tests.length ? (
                    <ul className="grid gap-2 text-sm">
                      {data.flaky_tests.map((f) => (
                        <li key={f.test_case_id}><Link className="hover:underline" href={`/tests/${f.test_case_id}`}>{f.title}</Link>
                          <span className="tabular block text-xs text-muted-foreground">{f.passed} passed, {f.failed} failed in {f.runs} runs</span></li>
                      ))}
                    </ul>
                  ) : <p className="text-sm text-muted-foreground">No flaky tests detected.</p>}
                </CardContent>
              </Card>
              {data.recommendations.length > 0 && (
                <Card>
                  <CardHeader><CardTitle className="flex items-center gap-1.5"><Lightbulb className="h-4 w-4 text-primary" /> Recommendations</CardTitle></CardHeader>
                  <CardContent><ul className="grid list-disc gap-1.5 pl-4 text-sm">{data.recommendations.map((r) => <li key={r}>{r}</li>)}</ul></CardContent>
                </Card>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
