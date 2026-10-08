"use client";

import { CheckCircle2, Copy, Save, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import useSWR from "swr";
import { RunButton } from "@/components/run-controls";
import { StatusBadge } from "@/components/status";
import { StepEditor } from "@/components/step-editor";
import { Alert, Button, Card, CardContent, Field, Input, Select, Spinner, Tabs, TabsContent, TabsList, TabsTrigger, Textarea } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { api, fetcher } from "@/lib/api";
import type { Result, Step, TestCase, ValidationMessage } from "@/lib/types";
import { formatDuration, timeAgo } from "@/lib/utils";

interface Draft { title: string; description: string; category: string; priority: string; kind: "ui" | "api"; steps: Step[] }

function History({ id }: { id: string }) {
  const { project } = useWorkspace();
  const { data } = useSWR<Result[]>(project ? `/projects/${project.id}/test-cases/${id}/history` : null, fetcher);
  if (!data) return <Spinner />;
  if (!data.length) return <p className="text-sm text-muted-foreground">This test has not run yet.</p>;
  return (
    <ul className="divide-y rounded-lg border bg-card">
      {data.map((r) => (
        <li key={r.id}>
          <Link href={`/runs/${r.execution_id}?result=${r.id}`} className="flex items-center gap-3 px-4 py-2.5 text-sm hover:bg-muted/50">
            <StatusBadge status={r.status} /><span className="text-muted-foreground">{r.browser}</span>
            {r.failure && <span className="text-xs text-muted-foreground">{r.failure.label}</span>}
            <span className="ml-auto text-xs text-muted-foreground">{formatDuration(r.duration_ms)}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function Code({ id }: { id: string }) {
  const { project } = useWorkspace();
  const { data } = useSWR<{ code: string }>(project ? `/projects/${project.id}/test-cases/${id}/code` : null, fetcher);
  if (!data) return <Spinner />;
  return (
    <div className="grid gap-2">
      <p className="text-sm text-muted-foreground">Playwright TypeScript generated from the steps. Edit the steps; the code is regenerated for every run.</p>
      <pre className="max-h-[60vh] overflow-auto rounded-lg border bg-[#0f1117] p-4 font-mono text-[12.5px] leading-5 text-[#e6e8ef]" data-testid="generated-code">{data.code}</pre>
    </div>
  );
}

export function TestEditor({ testCase }: { testCase?: TestCase }) {
  const { project, canWrite } = useWorkspace();
  const router = useRouter();
  const [draft, setDraft] = React.useState<Draft>({
    title: testCase?.title ?? "", description: testCase?.description ?? "", category: testCase?.category ?? "functional",
    priority: testCase?.priority ?? "medium", kind: testCase?.kind ?? "ui", steps: testCase?.steps ?? [],
  });
  const [messages, setMessages] = React.useState<ValidationMessage[]>(testCase?.validation_messages ?? []);
  const [status, setStatus] = React.useState(testCase?.validation_status ?? "unvalidated");
  const [dirty, setDirty] = React.useState(!testCase);
  const [busy, setBusy] = React.useState<"" | "save" | "validate" | "dup">("");
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);

  const update = (patch: Partial<Draft>) => { setDraft((d) => ({ ...d, ...patch })); setDirty(true); setNotice(null); };

  async function save(): Promise<TestCase | null> {
    if (!project) return null;
    setBusy("save");
    setError(null);
    try {
      const body = { ...draft, steps: draft.steps.map(({ id, ...s }) => s) }; // eslint-disable-line @typescript-eslint/no-unused-vars
      const saved = testCase
        ? await api<TestCase>(`/projects/${project.id}/test-cases/${testCase.id}`, { method: "PATCH", json: body })
        : await api<TestCase>(`/projects/${project.id}/test-cases`, { json: body });
      setMessages(saved.validation_messages);
      setStatus(saved.validation_status);
      setDirty(false);
      setNotice("Saved");
      if (!testCase) router.replace(`/tests/${saved.id}`);
      return saved;
    } catch (err) {
      setError((err as Error).message);
      return null;
    } finally {
      setBusy("");
    }
  }

  async function validate() {
    if (!project) return;
    const saved = dirty ? await save() : testCase;
    if (!saved) return;
    setBusy("validate");
    try {
      const res = await api<{ status: string; messages: ValidationMessage[]; compiled: boolean | null }>(`/projects/${project.id}/test-cases/${saved.id}/validate`, { method: "POST" });
      setMessages(res.messages);
      setStatus(res.status);
      setNotice(res.status === "invalid" ? null : res.compiled ? "Valid: the generated Playwright code compiled." : "Valid");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function duplicate() {
    if (!project || !testCase) return;
    setBusy("dup");
    const copy = await api<TestCase>(`/projects/${project.id}/test-cases/${testCase.id}/duplicate`, { method: "POST" });
    router.push(`/tests/${copy.id}`);
  }

  const editor = (
    <div className="grid gap-4">
      <StepEditor steps={draft.steps} onChange={(steps) => update({ steps })} messages={messages} kind={draft.kind} readOnly={!canWrite} />
    </div>
  );

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <Input aria-label="Test name" value={draft.title} onChange={(e) => update({ title: e.target.value })} placeholder="Name this test, e.g. Customer can sign in"
            className="h-auto border-transparent bg-transparent px-0 text-xl font-semibold shadow-none focus-visible:ring-0" disabled={!canWrite} />
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <StatusBadge status={status} />
            {testCase && <span>Version {testCase.version} · updated {timeAgo(testCase.updated_at)}</span>}
            {dirty && <span className="text-[#8a5b00]">Unsaved changes</span>}
            {notice && <span className="flex items-center gap-1 text-[#106b10]"><CheckCircle2 className="h-3.5 w-3.5" />{notice}</span>}
          </div>
        </div>
        {canWrite && (
          <div className="flex flex-wrap items-start gap-2">
            <Button variant="outline" onClick={validate} loading={busy === "validate"} data-testid="validate-test"><ShieldCheck /> Validate</Button>
            {testCase && <Button variant="outline" onClick={duplicate} loading={busy === "dup"}><Copy /> Duplicate</Button>}
            <Button onClick={save} loading={busy === "save"} disabled={!draft.title.trim()} data-testid="save-test"><Save /> Save</Button>
          </div>
        )}
      </div>
      {error && <Alert variant="error">{error}</Alert>}

      <div className="grid gap-6 lg:grid-cols-[1fr_18rem]">
        <div className="min-w-0">
          {testCase ? (
            <Tabs defaultValue="steps">
              <TabsList><TabsTrigger value="steps">Steps</TabsTrigger><TabsTrigger value="code">Code</TabsTrigger><TabsTrigger value="history">History</TabsTrigger></TabsList>
              <TabsContent value="steps">{editor}</TabsContent>
              <TabsContent value="code"><Code id={testCase.id} /></TabsContent>
              <TabsContent value="history"><History id={testCase.id} /></TabsContent>
            </Tabs>
          ) : editor}
        </div>
        <aside className="grid content-start gap-4">
          {testCase && canWrite && (
            <Card><CardContent className="pt-4">
              {dirty ? <p className="text-sm text-muted-foreground">Save your changes to run this test.</p> : <RunButton testCaseIds={[testCase.id]} label="Run test" />}
            </CardContent></Card>
          )}
          <Card>
            <CardContent className="grid gap-3 pt-4">
              <Field label="Type" htmlFor="tc-kind">
                <Select id="tc-kind" value={draft.kind} onChange={(e) => update({ kind: e.target.value as "ui" | "api" })} disabled={!canWrite || !!testCase}>
                  <option value="ui">Browser test</option><option value="api">API test</option>
                </Select>
              </Field>
              <Field label="Category" htmlFor="tc-cat">
                <Select id="tc-cat" value={draft.category} onChange={(e) => update({ category: e.target.value })} disabled={!canWrite}>
                  {["functional", "negative", "boundary", "security", "ui", "smoke", "regression"].map((c) => <option key={c} value={c}>{c}</option>)}
                </Select>
              </Field>
              <Field label="Priority" htmlFor="tc-pri">
                <Select id="tc-pri" value={draft.priority} onChange={(e) => update({ priority: e.target.value })} disabled={!canWrite}>
                  <option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option>
                </Select>
              </Field>
              <Field label="Description" htmlFor="tc-desc">
                <Textarea id="tc-desc" rows={4} value={draft.description} onChange={(e) => update({ description: e.target.value })} disabled={!canWrite} />
              </Field>
              <p className="text-xs text-muted-foreground">Use <code className="rounded bg-muted px-1">{"{{variable}}"}</code> to reference environment variables, such as <code className="rounded bg-muted px-1">{"{{username}}"}</code>. Manage them in Settings.</p>
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  );
}
