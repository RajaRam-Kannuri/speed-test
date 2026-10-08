"use client";

import { AlertTriangle, Bot, CheckCircle2, HelpCircle, KeyRound, MessageSquarePlus, Play, Save, Send, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import useSWR from "swr";
import { useCapabilities } from "@/components/run-controls";
import { StatusBadge } from "@/components/status";
import { StepEditor } from "@/components/step-editor";
import { Alert, Badge, Button, Card, CardContent, Input, Spinner, Textarea } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { api, fetcher } from "@/lib/api";
import type { ChatMessage, Environment, ExecutionDetail, Plan, Step, TestCase, ValidationMessage } from "@/lib/types";
import { ACTIVE_STATUSES, cn, timeAgo } from "@/lib/utils";

interface Conversation { id: string; title: string; created_at: string; messages?: ChatMessage[] }

const EXAMPLES = [
  "Open the application, log in with valid credentials, navigate to the dashboard, create a new customer, and verify that the customer appears in the customer list.",
  "Log in with invalid credentials and verify an error message is shown.",
  "Open the contact page, enter \"Ada\" into the Your name field, and click Send message. Verify the URL contains /contact.",
];

function Prerequisites({ items, onSaved }: { items: Plan["prerequisites"]; onSaved: () => void }) {
  const { project } = useWorkspace();
  const { data: envs } = useSWR<Environment[]>(project ? `/projects/${project.id}/environments` : null, fetcher);
  const [values, setValues] = React.useState<Record<string, string>>({});
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const env = envs?.find((e) => e.is_default) ?? envs?.[0];
  const missing = items.filter((p) => !env?.variables.some((v) => v.key === p.variable && v.has_value));
  if (!missing.length) return <p className="flex items-center gap-1.5 text-xs text-[#106b10]"><CheckCircle2 className="h-3.5 w-3.5" /> All required test data is set in the {env?.name ?? "default"} environment.</p>;
  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!project || !env) return;
    setBusy(true);
    setError(null);
    try {
      for (const p of missing) {
        if (values[p.variable]) await api(`/projects/${project.id}/environments/${env.id}/variables`, { method: "PUT", json: { key: p.variable, value: values[p.variable], is_secret: p.secret } });
      }
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={save} className="grid gap-2 rounded-md border border-[#f3dfb0] bg-[#fefaf0] p-3">
      <p className="flex items-center gap-1.5 text-sm font-medium"><KeyRound className="h-4 w-4" /> Test data needed before running</p>
      {missing.map((p) => (
        <label key={p.variable} className="grid gap-1 text-xs">
          <span><code className="rounded bg-card px-1">{p.variable}</code> — {p.description}{p.secret ? " (stored encrypted)" : ""}</span>
          <Input type={p.secret ? "password" : "text"} value={values[p.variable] ?? ""} onChange={(e) => setValues({ ...values, [p.variable]: e.target.value })} autoComplete="off" />
        </label>
      ))}
      {error && <Alert variant="error">{error}</Alert>}
      <Button size="sm" type="submit" loading={busy} className="w-fit">Save test data</Button>
    </form>
  );
}

function ExecutionCard({ executionId }: { executionId: string }) {
  const { data: e } = useSWR<ExecutionDetail>(`/executions/${executionId}`, fetcher, { refreshInterval: (d) => (d && ACTIVE_STATUSES.includes(d.status) ? 1500 : 0) });
  if (!e) return <Spinner />;
  const r = e.results[0];
  return (
    <div className="grid gap-2 rounded-md border bg-card p-3 text-sm" data-testid="assistant-run">
      <div className="flex items-center gap-2"><StatusBadge status={e.status} /><span className="tabular">{e.passed}/{e.total} passed</span>
        <Link href={`/runs/${e.id}`} className="ml-auto text-primary hover:underline">Open run</Link></div>
      {r?.error_message && <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded bg-muted/50 p-2 font-mono text-xs">{r.error_message.slice(0, 600)}</pre>}
      {r?.failure && <p className="text-xs text-muted-foreground">Analysis: {r.failure.label} ({Math.round(r.failure.confidence * 100)}% confidence). Ask &ldquo;why did it fail?&rdquo; for details.</p>}
    </div>
  );
}

function PlanCard({ message, conversationId, onChanged }: { message: ChatMessage; conversationId: string; onChanged: () => void }) {
  const { project, canWrite } = useWorkspace();
  const plan = message.payload as Plan;
  const [steps, setSteps] = React.useState<Step[]>(plan.steps);
  const [title, setTitle] = React.useState(plan.title);
  const [messages, setMessages] = React.useState<ValidationMessage[]>(plan.validation.messages);
  const [status, setStatus] = React.useState(plan.validation.status);
  const [testId, setTestId] = React.useState<string | undefined>(plan.test_case_id);
  const [compiled, setCompiled] = React.useState<boolean | null>(null);
  const [busy, setBusy] = React.useState<string>("");
  const [error, setError] = React.useState<string | null>(null);
  const [edited, setEdited] = React.useState(false);

  async function saveTest(): Promise<string | null> {
    if (!project) return null;
    setBusy("save");
    setError(null);
    try {
      if (testId) {
        const tc = await api<TestCase>(`/projects/${project.id}/test-cases/${testId}`, { method: "PATCH", json: { title, steps: steps.map(({ id, ...s }) => s) } }); // eslint-disable-line @typescript-eslint/no-unused-vars
        setMessages(tc.validation_messages); setStatus(tc.validation_status);
      } else {
        const tc = await api<TestCase>(`/assistant/messages/${message.id}/save`, { json: { title, steps } });
        setTestId(tc.id); setMessages(tc.validation_messages); setStatus(tc.validation_status);
        onChanged();
        return tc.id;
      }
      setEdited(false);
      return testId!;
    } catch (err) {
      setError((err as Error).message);
      return null;
    } finally {
      setBusy("");
    }
  }

  async function validate() {
    const id = !testId || edited ? await saveTest() : testId;
    if (!id || !project) return;
    setBusy("validate");
    try {
      const res = await api<{ status: string; messages: ValidationMessage[]; compiled: boolean | null }>(`/projects/${project.id}/test-cases/${id}/validate`, { method: "POST" });
      setMessages(res.messages); setStatus(res.status); setCompiled(res.compiled);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function run() {
    const id = !testId || edited ? await saveTest() : testId;
    if (!id) return;
    setBusy("run");
    setError(null);
    try {
      await api(`/assistant/conversations/${conversationId}/run`, { json: { test_case_id: id } });
      onChanged();
    } catch (err) {
      const d = (err as { detail?: { message?: string; tests?: { errors: string[] }[] } }).detail;
      setError(d?.tests ? `${d.message} ${d.tests[0].errors.join(" ")}` : (err as Error).message);
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="grid gap-3 rounded-lg border bg-card p-4" data-testid="plan-card">
      <div className="flex flex-wrap items-center gap-2">
        <Input aria-label="Test name" value={title} onChange={(e) => { setTitle(e.target.value); setEdited(true); }} className="h-8 max-w-xl flex-1 font-medium" disabled={!canWrite} />
        <StatusBadge status={status} />
        <Badge variant="outline">{plan.engine === "anthropic" ? `Planned by ${plan.model}` : "Planned by built-in rules"}</Badge>
      </div>
      {plan.warnings.length > 0 && (
        <ul className="grid gap-1 text-xs text-muted-foreground">{plan.warnings.map((w, i) => <li key={i} className="flex gap-1.5"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#a87000]" />{w}</li>)}</ul>
      )}
      {plan.questions.length > 0 && (
        <div className="grid gap-1 rounded-md bg-accent px-3 py-2 text-sm text-accent-foreground">
          {plan.questions.map((q, i) => <p key={i} className="flex gap-1.5"><HelpCircle className="mt-0.5 h-4 w-4 shrink-0" />{q}</p>)}
          <p className="text-xs opacity-80">Reply below to refine the plan, or edit the steps directly.</p>
        </div>
      )}
      {plan.interpretation.length > 1 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-muted-foreground">How I read your instructions</summary>
          <ul className="mt-2 grid gap-1">{plan.interpretation.map((it, i) => (
            <li key={i} className="flex gap-2 text-xs"><span className={cn("shrink-0", it.note ? "text-critical" : "text-[#106b10]")}>{it.note ? "✗" : "✓"}</span>
              <span>&ldquo;{it.clause}&rdquo; {it.note ? `— ${it.note}` : `→ step${it.steps.length > 1 ? "s" : ""} ${it.steps.map((s) => s + 1).join(", ")}`}</span></li>
          ))}</ul>
        </details>
      )}
      <StepEditor steps={steps} onChange={(s) => { setSteps(s); setEdited(true); }} messages={messages} readOnly={!canWrite} />
      {plan.prerequisites.length > 0 && <Prerequisites items={plan.prerequisites} onSaved={() => setStatus("unvalidated")} />}
      {compiled !== null && (compiled
        ? <p className="flex items-center gap-1.5 text-xs text-[#106b10]"><CheckCircle2 className="h-3.5 w-3.5" /> Playwright code generated and compiled.</p>
        : <p className="text-xs text-critical">The generated code did not compile. See the messages above.</p>)}
      {error && <Alert variant="error">{error}</Alert>}
      {canWrite && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={saveTest} loading={busy === "save"} data-testid="save-plan"><Save /> {testId ? (edited ? "Save changes" : "Saved") : "Save as test"}</Button>
          <Button size="sm" variant="outline" onClick={validate} loading={busy === "validate"} data-testid="validate-plan"><ShieldCheck /> Validate code</Button>
          <Button size="sm" onClick={run} loading={busy === "run"} data-testid="run-plan"><Play /> Run test</Button>
          {testId && <Link href={`/tests/${testId}`} className="self-center text-sm text-primary hover:underline">Open in editor</Link>}
        </div>
      )}
    </div>
  );
}

function Chat({ conversationId }: { conversationId: string }) {
  const { data, mutate } = useSWR<Conversation>(`/assistant/conversations/${conversationId}`, fetcher);
  const [text, setText] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const bottom = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [data?.messages?.length]);

  async function send(content: string) {
    if (!content.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/assistant/conversations/${conversationId}/messages`, { json: { content } });
      setText("");
      await mutate();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!data) return <Spinner />;
  return (
    <div className="flex min-h-[70vh] flex-col">
      <div className="flex-1 space-y-4 pb-4" data-testid="chat-messages">
        {data.messages?.length === 0 && (
          <div className="rounded-lg border border-dashed bg-card p-6">
            <p className="flex items-center gap-2 text-sm font-medium"><Bot className="h-4 w-4 text-primary" /> Describe what you want to test</p>
            <p className="mt-1 text-sm text-muted-foreground">I turn your description into test steps using the pages found by website discovery, show you how I understood it, and run it when you approve.</p>
            <div className="mt-4 grid gap-2">{EXAMPLES.map((ex) => (
              <button key={ex} onClick={() => setText(ex)} className="rounded-md border px-3 py-2 text-left text-sm hover:border-primary/50 hover:bg-accent/40">{ex}</button>
            ))}</div>
          </div>
        )}
        {data.messages?.map((m) => (
          <div key={m.id} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
            <div className={cn("grid max-w-full gap-2", m.role === "user" ? "max-w-[80%]" : "w-full")}>
              <div className={cn("whitespace-pre-wrap rounded-lg px-3.5 py-2.5 text-sm", m.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted")}>{m.content}</div>
              {m.payload?.kind === "plan" && <PlanCard message={m} conversationId={conversationId} onChanged={() => mutate()} />}
              {m.payload?.kind === "execution" && <ExecutionCard executionId={m.payload.execution_id} />}
              {m.payload?.kind === "analysis" && m.payload.items?.length > 0 && (
                <div className="grid gap-2">{m.payload.items.map((it: any) => (
                  <div key={it.result_id} className="rounded-md border bg-card p-3 text-sm">
                    <p className="font-medium">{it.title}: {it.category} <span className="tabular text-xs text-muted-foreground">({Math.round(it.confidence * 100)}%)</span></p>
                    <p className="mt-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Verified</p>
                    <ul className="list-disc pl-5 text-xs">{it.verified.map((v: string, i: number) => <li key={i}>{v}</li>)}</ul>
                    {it.hypotheses.length > 0 && <><p className="mt-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Hypotheses</p><ul className="list-disc pl-5 text-xs">{it.hypotheses.map((v: string, i: number) => <li key={i}>{v}</li>)}</ul></>}
                  </div>
                ))}</div>
              )}
            </div>
          </div>
        ))}
        <div ref={bottom} />
      </div>
      <form onSubmit={(e) => { e.preventDefault(); send(text); }} className="sticky bottom-0 grid gap-2 border-t bg-background pt-3">
        {error && <Alert variant="error">{error}</Alert>}
        <div className="flex items-end gap-2">
          <Textarea aria-label="Message" value={text} onChange={(e) => setText(e.target.value)} rows={2} placeholder="Describe a test, answer a question, or ask why a run failed…"
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(text); } }} />
          <Button type="submit" loading={busy} disabled={!text.trim()} aria-label="Send" data-testid="send-message"><Send /></Button>
        </div>
      </form>
    </div>
  );
}

function AssistantView() {
  const { project, canWrite } = useWorkspace();
  const router = useRouter();
  const params = useSearchParams();
  const caps = useCapabilities();
  const { data: conversations, mutate } = useSWR<Conversation[]>(project ? `/projects/${project.id}/assistant/conversations` : null, fetcher);
  const current = params.get("c") ?? conversations?.[0]?.id ?? null;

  async function start() {
    if (!project) return;
    const c = await api<Conversation>(`/projects/${project.id}/assistant/conversations`, { json: {} });
    await mutate();
    router.replace(`/assistant?c=${c.id}`);
  }
  React.useEffect(() => {
    if (conversations && conversations.length === 0 && canWrite && project) start();
  }, [conversations?.length]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!project) return <Alert>Create a project first.</Alert>;
  return (
    <div className="grid gap-6 lg:grid-cols-[15rem_1fr]">
      <aside className="grid content-start gap-2">
        <div className="mb-2">
          <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight"><Bot className="h-5 w-5 text-primary" /> AI Test Assistant</h1>
          <p className="mt-1 text-xs text-muted-foreground">{caps?.ai.enabled ? `Using ${caps.ai.model}.` : "No AI key configured: the built-in rule engine plans tests and tells you what it could not understand."}</p>
        </div>
        {canWrite && <Button variant="outline" size="sm" onClick={start}><MessageSquarePlus /> New conversation</Button>}
        <ul className="grid gap-0.5">
          {conversations?.map((c) => (
            <li key={c.id}><button onClick={() => router.replace(`/assistant?c=${c.id}`)}
              className={cn("w-full truncate rounded-md px-2.5 py-1.5 text-left text-sm hover:bg-muted", c.id === current && "bg-muted font-medium")}>
              {c.title}<span className="block text-[11px] font-normal text-muted-foreground">{timeAgo(c.created_at)}</span></button></li>
          ))}
        </ul>
      </aside>
      <section className="min-w-0">{current ? <Chat key={current} conversationId={current} /> : <Spinner />}</section>
    </div>
  );
}

export default function AssistantPage() {
  return <React.Suspense><AssistantView /></React.Suspense>;
}
