"use client";

import { CheckCircle2, Globe, Lock, Sparkles, XCircle } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import useSWR from "swr";
import { useCapabilities } from "@/components/run-controls";
import { TestReview } from "@/components/test-review";
import { Alert, Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Checkbox, Field, Input, PageHeader, Select, Spinner } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { api, fetcher } from "@/lib/api";
import type { Discovery, Job } from "@/lib/types";

function StepPill({ n, label, state }: { n: number; label: string; state: "done" | "current" | "todo" }) {
  return (
    <li className="flex items-center gap-2 text-sm">
      <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold ${state === "done" ? "bg-primary text-primary-foreground" : state === "current" ? "border-2 border-primary text-primary" : "border text-muted-foreground"}`}>{n}</span>
      <span className={state === "todo" ? "text-muted-foreground" : "font-medium"}>{label}</span>
    </li>
  );
}

function DiscoveryForm({ onStarted }: { onStarted: (d: Discovery) => void }) {
  const { project } = useWorkspace();
  const [url, setUrl] = React.useState(project?.base_url ?? "");
  const [authorized, setAuthorized] = React.useState(false);
  const [needsLogin, setNeedsLogin] = React.useState(false);
  const [loginUrl, setLoginUrl] = React.useState("");
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [maxPages, setMaxPages] = React.useState(15);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!project) return;
    setBusy(true);
    setError(null);
    try {
      const d = await api<Discovery>(`/projects/${project.id}/discoveries`, {
        json: { url, authorized, max_pages: maxPages, ...(needsLogin ? { login_url: loginUrl || null, username: username || null, password: password || null } : {}) },
      });
      onStarted(d);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader><div><CardTitle>Which website should we test?</CardTitle><CardDescription>We open it in a cloud browser, follow links on the same site, and note pages, forms and buttons. Forms are not submitted during discovery.</CardDescription></div></CardHeader>
      <CardContent>
        <form onSubmit={submit} className="grid gap-4">
          <Field label="Website URL" htmlFor="site-url">
            <Input id="site-url" required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://staging.myapp.com" />
          </Field>
          <Checkbox checked={needsLogin} onChange={(e) => setNeedsLogin(e.target.checked)} label="The site needs a sign-in to reach the main pages" />
          {needsLogin && (
            <div className="grid gap-3 rounded-md border bg-muted/30 p-3 sm:grid-cols-3">
              <Field label="Sign-in page" htmlFor="login-url" hint="Path or full URL"><Input id="login-url" value={loginUrl} onChange={(e) => setLoginUrl(e.target.value)} placeholder="/login" /></Field>
              <Field label="Username or email" htmlFor="login-user"><Input id="login-user" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" /></Field>
              <Field label="Password" htmlFor="login-pass" hint="Stored encrypted. Never shown in reports."><Input id="login-pass" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" /></Field>
              <p className="flex items-center gap-1.5 text-xs text-muted-foreground sm:col-span-3"><Lock className="h-3.5 w-3.5" /> Use a dedicated test account. Credentials are saved to the project&apos;s default environment as <code>username</code> and <code>password</code>.</p>
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-[12rem_1fr] sm:items-end">
            <Field label="Pages to explore" htmlFor="max-pages">
              <Select id="max-pages" value={maxPages} onChange={(e) => setMaxPages(Number(e.target.value))}>{[5, 10, 15, 25, 50].map((n) => <option key={n} value={n}>Up to {n}</option>)}</Select>
            </Field>
          </div>
          <div className="rounded-md border border-[#f3dfb0] bg-[#fefaf0] p-3">
            <Checkbox required checked={authorized} onChange={(e) => setAuthorized(e.target.checked)} data-testid="authorize-checkbox"
              label={<span><span className="font-medium">I am authorized to test this website.</span> <span className="text-muted-foreground">Only test systems you own or have written permission to test. Internal network addresses are blocked.</span></span>} />
          </div>
          {error && <Alert variant="error">{error}</Alert>}
          <div><Button type="submit" loading={busy} disabled={!authorized}><Globe /> Discover website</Button></div>
        </form>
      </CardContent>
    </Card>
  );
}

function DiscoveryResult({ discovery }: { discovery: Discovery }) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Discovered {discovery.page_count} pages</CardTitle>
          <CardDescription>{discovery.url}</CardDescription>
        </div>
        {discovery.login_result && (
          discovery.login_result.success
            ? <Badge variant="good"><CheckCircle2 className="h-3 w-3" /> Signed in</Badge>
            : <Badge variant="critical"><XCircle className="h-3 w-3" /> Sign-in failed</Badge>
        )}
      </CardHeader>
      <CardContent className="grid gap-4">
        {discovery.login_result && !discovery.login_result.success && (
          <Alert variant="warning" title="Sign-in did not work">Only public pages were explored. {discovery.login_result.error}</Alert>
        )}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" data-testid="discovered-pages">
          {discovery.pages?.map((p) => (
            <div key={p.id} className="overflow-hidden rounded-md border">
              {p.screenshot_url
                ? <img src={p.screenshot_url} alt={`Screenshot of ${p.title}`} className="aspect-[16/10] w-full border-b object-cover object-top" loading="lazy" />
                : <div className="aspect-[16/10] w-full border-b bg-muted" />}
              <div className="p-3">
                <p className="truncate text-sm font-medium" title={p.title}>{p.title || p.url}</p>
                <p className="truncate font-mono text-xs text-muted-foreground">{new URL(p.url).pathname}</p>
                <div className="mt-2 flex flex-wrap gap-1">
                  {p.requires_login && <Badge variant="outline"><Lock className="h-3 w-3" /> Sign-in</Badge>}
                  {p.counts.forms > 0 && <Badge>{p.counts.forms} form{p.counts.forms > 1 ? "s" : ""}</Badge>}
                  {p.counts.fields > 0 && <Badge>{p.counts.fields} fields</Badge>}
                  <Badge>{p.counts.links} links</Badge>
                  {p.counts.tables > 0 && <Badge>{p.counts.tables} table{p.counts.tables > 1 ? "s" : ""}</Badge>}
                </div>
              </div>
            </div>
          ))}
        </div>
        {discovery.skipped.length > 0 && (
          <details className="text-sm">
            <summary className="cursor-pointer text-muted-foreground">{discovery.skipped.length} links skipped for safety or errors</summary>
            <ul className="mt-2 grid gap-1 text-xs text-muted-foreground">{discovery.skipped.slice(0, 20).map((s, i) => <li key={i}><span className="font-mono">{s.url}</span> — {s.reason}</li>)}</ul>
          </details>
        )}
      </CardContent>
    </Card>
  );
}

function WebsiteFlow() {
  const router = useRouter();
  const params = useSearchParams();
  const caps = useCapabilities();
  const discoveryId = params.get("discovery");
  const jobId = params.get("job");
  const setParam = (k: string, v: string) => {
    const p = new URLSearchParams(params.toString());
    p.set(k, v);
    router.replace(`/create/website?${p.toString()}`);
  };

  const { data: discovery } = useSWR<Discovery>(discoveryId ? `/discoveries/${discoveryId}` : null, fetcher, {
    refreshInterval: (d) => (d && ["queued", "running"].includes(d.status) ? 1500 : 0),
  });
  const { data: job } = useSWR<Job>(jobId ? `/generation-jobs/${jobId}` : null, fetcher, {
    refreshInterval: (j) => (j && ["queued", "running"].includes(j.status) ? 1000 : 0),
  });
  const [genBusy, setGenBusy] = React.useState(false);
  const [genError, setGenError] = React.useState<string | null>(null);

  async function generate() {
    if (!discovery) return;
    setGenBusy(true);
    setGenError(null);
    try {
      const j = await api<Job>(`/discoveries/${discovery.id}/generate`, { json: { use_ai: true } });
      setParam("job", j.id);
    } catch (err) {
      setGenError((err as Error).message);
    } finally {
      setGenBusy(false);
    }
  }

  const stage = !discovery ? 1 : discovery.status !== "completed" ? 1 : !job || job.status !== "completed" ? 2 : 3;
  return (
    <div className="grid gap-6">
      <PageHeader title="Test a website" description="Discover the site, review the suggested tests, then run them in a cloud browser." />
      <ol className="flex flex-wrap gap-6" aria-label="Progress">
        <StepPill n={1} label="Discover" state={stage > 1 ? "done" : "current"} />
        <StepPill n={2} label="Generate tests" state={stage > 2 ? "done" : stage === 2 ? "current" : "todo"} />
        <StepPill n={3} label="Review and run" state={stage === 3 ? "current" : "todo"} />
      </ol>

      {!discoveryId && <DiscoveryForm onStarted={(d) => setParam("discovery", d.id)} />}

      {discovery && ["queued", "running"].includes(discovery.status) && (
        <Card><CardContent className="flex items-center gap-3 py-6 text-sm"><Spinner /> Exploring {discovery.url} in a cloud browser. This usually takes under a minute.</CardContent></Card>
      )}
      {discovery?.status === "failed" && (
        <Alert variant="error" title="Discovery failed">{discovery.error_message} <Button variant="link" size="sm" onClick={() => router.replace("/create/website")}>Try again</Button></Alert>
      )}
      {discovery?.status === "completed" && <DiscoveryResult discovery={discovery} />}

      {discovery?.status === "completed" && !jobId && (
        <Card>
          <CardContent className="flex flex-wrap items-center justify-between gap-3 py-5">
            <div>
              <p className="text-sm font-medium">Generate test cases from what we found</p>
              <p className="text-sm text-muted-foreground">
                {caps?.ai.enabled ? `Built-in planners plus ${caps.ai.model} propose scenarios; every AI locator is checked against the discovered page.` : "The built-in planner proposes scenarios. Connect Claude in settings to add AI-proposed journeys."}
              </p>
            </div>
            <Button onClick={generate} loading={genBusy} data-testid="generate-tests"><Sparkles /> Generate tests</Button>
          </CardContent>
          {genError && <CardContent><Alert variant="error">{genError}</Alert></CardContent>}
        </Card>
      )}

      {job && ["queued", "running"].includes(job.status) && (
        <Card><CardContent className="flex items-center gap-3 py-6 text-sm"><Spinner /> Planning tests…</CardContent></Card>
      )}
      {job?.status === "failed" && <Alert variant="error" title="Test generation failed">{job.error_message}</Alert>}
      {job?.status === "completed" && (
        <TestReview ids={job.result.test_case_ids ?? []} heading={
          <div>
            <h2 className="text-base font-semibold">{job.result.created} test cases generated</h2>
            <p className="text-sm text-muted-foreground">
              Planned by {job.result.ai?.used ? `the built-in planner and ${job.model}` : "the built-in planner"}.
              {job.result.ai?.error ? ` AI planning was skipped: ${job.result.ai.error}` : ""}
              {job.result.ai?.rejected?.length ? ` ${job.result.ai.rejected.length} AI suggestions were rejected because they used elements that do not exist on the site.` : ""}
            </p>
          </div>
        } />
      )}
    </div>
  );
}

export default function WebsitePage() {
  return <React.Suspense><WebsiteFlow /></React.Suspense>;
}
