"use client";

import { FlaskConical, Layers, Plus, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import useSWR from "swr";
import { RunButton } from "@/components/run-controls";
import { CategoryBadge, PriorityDot, StatusBadge } from "@/components/status";
import { Alert, Badge, Button, Dialog, DialogContent, EmptyState, Field, Input, PageHeader, Select, Spinner, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { api, fetcher } from "@/lib/api";
import type { TestCase } from "@/lib/types";
import { timeAgo } from "@/lib/utils";

interface Suite { id: string; name: string; description: string; test_case_ids: string[] }

const SOURCE_LABEL: Record<string, string> = { website_ai: "Website discovery", api_ai: "API spec", assistant: "Assistant", builder: "Builder", manual: "Manual", recorder: "Recorder" };

function CaseTable() {
  const { project, canWrite } = useWorkspace();
  const [q, setQ] = React.useState("");
  const [kind, setKind] = React.useState("");
  const [category, setCategory] = React.useState("");
  const [status, setStatus] = React.useState("");
  const params = new URLSearchParams(Object.entries({ q, kind, category, status }).filter(([, v]) => v));
  const { data: cases, mutate } = useSWR<TestCase[]>(project ? `/projects/${project.id}/test-cases?${params}` : null, fetcher);
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [suiteOpen, setSuiteOpen] = React.useState(false);

  if (!cases) return <div className="py-10"><Spinner /></div>;
  const runnable = cases.filter((c) => c.validation_status !== "invalid");
  const allSelected = runnable.length > 0 && runnable.every((c) => selected.has(c.id));

  async function archive() {
    if (!project) return;
    await Promise.all([...selected].map((id) => api(`/projects/${project.id}/test-cases/${id}`, { method: "PATCH", json: { status: "archived" } })));
    setSelected(new Set());
    mutate();
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input aria-label="Search tests" placeholder="Search tests" value={q} onChange={(e) => setQ(e.target.value)} className="pl-8" />
        </div>
        <Select aria-label="Type" className="w-32" value={kind} onChange={(e) => setKind(e.target.value)}><option value="">All types</option><option value="ui">Browser</option><option value="api">API</option></Select>
        <Select aria-label="Category" className="w-36" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">All categories</option>{["functional", "negative", "boundary", "security", "ui", "smoke", "regression"].map((c) => <option key={c} value={c}>{c}</option>)}
        </Select>
        <Select aria-label="Status" className="w-32" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Any status</option>{["generated", "draft", "ready", "archived"].map((c) => <option key={c} value={c}>{c}</option>)}
        </Select>
      </div>
      {selected.size > 0 && canWrite && (
        <div className="flex flex-wrap items-start gap-2 rounded-md border bg-accent/50 px-3 py-2">
          <span className="py-1.5 text-sm font-medium">{selected.size} selected</span>
          <RunButton testCaseIds={[...selected]} size="sm" label="Run" />
          <Button size="sm" variant="outline" onClick={() => setSuiteOpen(true)}><Layers /> Save as suite</Button>
          <Button size="sm" variant="ghost" onClick={archive}><Trash2 /> Archive</Button>
        </div>
      )}
      {cases.length === 0 ? (
        <EmptyState icon={<FlaskConical className="h-6 w-6" />} title="No tests match" description="Create tests from a website, an API specification, a plain-English description, or build one step by step."
          action={canWrite && <Button asChild><Link href="/tests/new"><Plus /> New test</Link></Button>} />
      ) : (
        <div className="overflow-hidden rounded-lg border bg-card">
          <table className="w-full text-sm" data-testid="tests-table">
            <thead>
              <tr className="border-b bg-muted/40 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                <th className="w-10 px-3 py-2"><input type="checkbox" aria-label="Select all tests" checked={allSelected} onChange={() => setSelected(allSelected ? new Set() : new Set(runnable.map((c) => c.id)))} /></th>
                <th className="px-3 py-2">Test case</th>
                <th className="hidden px-3 py-2 md:table-cell">Category</th>
                <th className="hidden px-3 py-2 lg:table-cell">Priority</th>
                <th className="px-3 py-2">Last result</th>
                <th className="hidden px-3 py-2 md:table-cell">Updated</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((c) => (
                <tr key={c.id} className="border-b last:border-0 hover:bg-muted/30">
                  <td className="px-3 py-2.5"><input type="checkbox" aria-label={`Select ${c.title}`} checked={selected.has(c.id)} disabled={c.validation_status === "invalid"}
                    onChange={() => setSelected((s) => { const n = new Set(s); n.has(c.id) ? n.delete(c.id) : n.add(c.id); return n; })} /></td>
                  <td className="px-3 py-2.5">
                    <Link href={`/tests/${c.id}`} className="font-medium hover:text-primary">{c.title}</Link>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                      <span>{c.kind === "api" ? "API" : "Browser"} · {c.step_count} steps · {SOURCE_LABEL[c.source] ?? c.source}</span>
                      {c.validation_status === "invalid" && <StatusBadge status="invalid" />}
                      {c.status !== "ready" && <StatusBadge status={c.status} />}
                    </div>
                  </td>
                  <td className="hidden px-3 py-2.5 md:table-cell"><CategoryBadge category={c.category} /></td>
                  <td className="hidden px-3 py-2.5 lg:table-cell"><PriorityDot priority={c.priority} /></td>
                  <td className="px-3 py-2.5">{c.last_result ? <Link href={`/runs/${c.last_result.execution_id}`}><StatusBadge status={c.last_result.status} /></Link> : <span className="text-xs text-muted-foreground">Not run</span>}</td>
                  <td className="hidden px-3 py-2.5 text-xs text-muted-foreground md:table-cell">{timeAgo(c.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <SuiteDialog open={suiteOpen} onOpenChange={setSuiteOpen} ids={[...selected]} />
    </div>
  );
}

function SuiteDialog({ open, onOpenChange, ids }: { open: boolean; onOpenChange: (o: boolean) => void; ids: string[] }) {
  const { project } = useWorkspace();
  const { mutate } = useSWR<Suite[]>(project ? `/projects/${project.id}/suites` : null, fetcher);
  const [name, setName] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api(`/projects/${project!.id}/suites`, { json: { name, test_case_ids: ids } });
      mutate();
      onOpenChange(false);
      setName("");
    } catch (err) {
      setError((err as Error).message);
    }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Save as test suite" description={`A suite runs these ${ids.length} tests together, for example as a regression pack.`}>
        <form onSubmit={save} className="grid gap-4">
          <Field label="Suite name" htmlFor="suite-name"><Input id="suite-name" required value={name} onChange={(e) => setName(e.target.value)} placeholder="Smoke tests" /></Field>
          {error && <Alert variant="error">{error}</Alert>}
          <div className="flex justify-end"><Button type="submit">Save suite</Button></div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Suites() {
  const { project, canWrite } = useWorkspace();
  const { data: suites, mutate } = useSWR<Suite[]>(project ? `/projects/${project.id}/suites` : null, fetcher);
  if (!suites) return <Spinner />;
  if (!suites.length) return <EmptyState icon={<Layers className="h-6 w-6" />} title="No suites yet" description="Select tests on the Test cases tab and choose Save as suite." />;
  return (
    <div className="grid gap-3">
      {suites.map((s) => (
        <div key={s.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card px-4 py-3">
          <div>
            <p className="text-sm font-medium">{s.name}</p>
            <p className="text-xs text-muted-foreground">{s.test_case_ids.length} tests</p>
          </div>
          {canWrite && (
            <div className="flex items-start gap-2">
              <RunButton testCaseIds={[]} suiteId={s.id} size="sm" label="Run suite" />
              <Button size="sm" variant="ghost" aria-label={`Delete suite ${s.name}`} onClick={async () => { await api(`/projects/${project!.id}/suites/${s.id}`, { method: "DELETE" }); mutate(); }}><Trash2 /></Button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export default function TestsPage() {
  const { project, canWrite } = useWorkspace();
  if (!project) return <EmptyState title="Create a project first" description="Use the project menu at the top to create one." />;
  return (
    <div>
      <PageHeader title="Tests" description={<>All test cases in <span className="font-medium text-foreground">{project.name}</span>. <Badge variant="outline">{project.test_count} active</Badge></>}
        actions={canWrite && <Button asChild variant="outline"><Link href="/tests/new"><Plus /> New test</Link></Button>} />
      <Tabs defaultValue="cases">
        <TabsList><TabsTrigger value="cases">Test cases</TabsTrigger><TabsTrigger value="suites">Suites</TabsTrigger></TabsList>
        <TabsContent value="cases"><CaseTable /></TabsContent>
        <TabsContent value="suites"><Suites /></TabsContent>
      </Tabs>
    </div>
  );
}
