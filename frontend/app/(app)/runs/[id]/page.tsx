"use client";

import { CheckCircle2, Download, FileText, Lightbulb, Microscope, Square, Wand2, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import useSWR from "swr";
import { StatusBadge } from "@/components/status";
import { Alert, Badge, Button, Card, CardContent, CardHeader, CardTitle, Spinner } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { api, fetcher } from "@/lib/api";
import type { Artifact, ExecutionDetail, HealingSuggestion, Result } from "@/lib/types";
import { ACTIVE_STATUSES, cn, describeTarget, formatDuration, timeAgo } from "@/lib/utils";

function ApiEvidence({ artifact }: { artifact: Artifact }) {
  const { data } = useSWR<{ request: any; response: any }>(artifact.url.replace(/^\/api/, ""), fetcher);
  if (!data) return <Spinner />;
  return (
    <div className="grid gap-2 rounded-md border bg-muted/30 p-3 text-xs">
      <p className="font-mono font-medium">{data.request.method} {data.request.url}</p>
      {data.request.body !== null && <pre className="max-h-40 overflow-auto rounded bg-card p-2 font-mono">{JSON.stringify(data.request.body, null, 2)}</pre>}
      <p className="font-medium">Response <Badge variant={data.response.status < 400 ? "good" : "critical"}>{data.response.status}</Badge> <span className="text-muted-foreground">{data.response.elapsed_ms} ms</span></p>
      <pre className="max-h-48 overflow-auto rounded bg-card p-2 font-mono">{data.response.body}</pre>
    </div>
  );
}

function Healing({ items, onDecided }: { items: HealingSuggestion[]; onDecided: () => void }) {
  const { canWrite } = useWorkspace();
  const [busy, setBusy] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  async function decide(id: string, decision: "accept" | "reject") {
    setBusy(id);
    setError(null);
    try {
      await api(`/healing-suggestions/${id}`, { json: { decision } });
      onDecided();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }
  return (
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-1.5"><Wand2 className="h-4 w-4 text-primary" /> Locator repair suggestions</CardTitle></CardHeader>
      <CardContent className="grid gap-3">
        <p className="text-xs text-muted-foreground">Accepting changes only how this step finds the element. The action, values and assertions stay the same. Every decision is recorded in the audit log.</p>
        {items.map((h) => (
          <div key={h.id} className="rounded-md border p-3 text-sm" data-testid="healing-suggestion">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-muted-foreground line-through">{describeTarget(h.original_target)}</span>
              <span aria-hidden>→</span>
              <span className="font-mono text-xs font-medium">{describeTarget(h.suggested_target)}</span>
              <Badge variant="outline" className="tabular">{Math.round(h.confidence * 100)}% confidence</Badge>
              {h.status !== "pending" && <Badge variant={h.status === "accepted" ? "good" : "default"}>{h.status}</Badge>}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{h.rationale}</p>
            {h.status === "pending" && canWrite && (
              <div className="mt-2 flex gap-2">
                <Button size="sm" onClick={() => decide(h.id, "accept")} loading={busy === h.id}>Accept repair</Button>
                <Button size="sm" variant="ghost" onClick={() => decide(h.id, "reject")} disabled={busy === h.id}>Reject</Button>
              </div>
            )}
          </div>
        ))}
        {error && <Alert variant="error">{error}</Alert>}
      </CardContent>
    </Card>
  );
}

function ResultDetail({ id, listStatus }: { id: string; listStatus?: string }) {
  const { data: r, mutate } = useSWR<Result>(`/results/${id}`, fetcher, {
    refreshInterval: (d) => (d && ["queued", "running"].includes(d.status) ? 1500 : 0),
  });
  // The run list polls while the run is active; refetch when it reports a new status for this result.
  React.useEffect(() => { if (listStatus && r && listStatus !== r.status) mutate(); }, [listStatus]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!r) return <div className="p-6"><Spinner /></div>;
  const shots = r.artifacts?.filter((a) => a.kind === "screenshot") ?? [];
  const video = r.artifacts?.find((a) => a.kind === "video");
  const trace = r.artifacts?.find((a) => a.kind === "trace");
  const apis = r.artifacts?.filter((a) => a.kind === "api") ?? [];
  return (
    <div className="grid gap-4" data-testid="result-detail">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={r.status} />
        <h2 className="text-base font-semibold">{r.test_title}</h2>
        <span className="text-xs text-muted-foreground">{formatDuration(r.duration_ms)} · {r.browser}{r.retries_used ? ` · ${r.retries_used} retr${r.retries_used > 1 ? "ies" : "y"}` : ""}</span>
        {r.test_case_id && <Link href={`/tests/${r.test_case_id}`} className="ml-auto text-sm text-primary hover:underline">Open test</Link>}
      </div>

      {r.failure && (
        <Card className="border-[hsl(var(--primary)/0.3)]">
          <CardHeader>
            <CardTitle className="flex items-center gap-1.5"><Microscope className="h-4 w-4 text-primary" /> {r.failure.label}</CardTitle>
            <Badge variant="outline" className="tabular">{Math.round(r.failure.confidence * 100)}% confidence</Badge>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm">
            <p>{r.failure.summary}</p>
            {r.failure.evidence.verified.length > 0 && (
              <div><p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Verified from this run</p>
                <ul className="grid gap-1">{r.failure.evidence.verified.map((v, i) => <li key={i} className="flex gap-1.5"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#106b10]" /><span className="break-words">{v}</span></li>)}</ul></div>
            )}
            {r.failure.evidence.hypotheses.length > 0 && (
              <div><p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Hypotheses (not verified)</p>
                <ul className="grid list-disc gap-1 pl-5">{r.failure.evidence.hypotheses.map((v, i) => <li key={i}>{v}</li>)}</ul></div>
            )}
            {r.failure.evidence.next_actions.length > 0 && (
              <div><p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Suggested next steps</p>
                <ul className="grid list-disc gap-1 pl-5">{r.failure.evidence.next_actions.map((v, i) => <li key={i}>{v}</li>)}</ul></div>
            )}
          </CardContent>
        </Card>
      )}

      {r.healing_suggestions && r.healing_suggestions.length > 0 && <Healing items={r.healing_suggestions} onDecided={() => mutate()} />}

      {r.step_results && r.step_results.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Steps</CardTitle></CardHeader>
          <CardContent>
            <ol className="grid gap-1">
              {r.step_results.map((s, i) => (
                <li key={i} className={cn("rounded-md border px-3 py-2 text-sm", s.status === "failed" && "border-critical/50 bg-[#fdf3f3]")}>
                  <div className="flex items-center gap-2">
                    {s.status === "passed" ? <CheckCircle2 className="h-4 w-4 text-[#0ca30c]" aria-label="Passed" /> : <XCircle className="h-4 w-4 text-critical" aria-label="Failed" />}
                    <span>{s.title.replace(/^Step \d+: /, "")}</span>
                    <span className="tabular ml-auto text-xs text-muted-foreground">{formatDuration(s.duration_ms)}</span>
                  </div>
                  {s.error && <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-card p-2 font-mono text-xs">{s.error}</pre>}
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      )}
      {r.error_message && !r.step_results?.some((s) => s.error) && (
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md border bg-[#fdf3f3] p-3 font-mono text-xs">{r.error_message}</pre>
      )}

      {apis.length > 0 && (
        <Card><CardHeader><CardTitle>API requests</CardTitle></CardHeader><CardContent className="grid gap-3">{apis.map((a) => <ApiEvidence key={a.id} artifact={a} />)}</CardContent></Card>
      )}
      {(shots.length > 0 || video) && (
        <Card>
          <CardHeader><CardTitle>Screenshots and video</CardTitle></CardHeader>
          <CardContent className="grid gap-3">
            {shots.map((s) => <a key={s.id} href={s.url} target="_blank" rel="noreferrer"><img src={s.url} alt={`Screenshot: ${r.test_title}`} className="w-full rounded-md border" loading="lazy" /></a>)}
            {video && <video src={video.url} controls className="w-full rounded-md border" preload="metadata"><track kind="captions" /></video>}
          </CardContent>
        </Card>
      )}
      {trace && (
        <Alert variant="info" title="Playwright trace">
          <a href={`${trace.url}?download=true`} className="font-medium underline">Download trace.zip</a>, then open it at trace.playwright.dev or run <code className="rounded bg-card px-1">npx playwright show-trace trace.zip</code> to step through every action, network call and DOM snapshot.
        </Alert>
      )}
      {r.generated_code && (
        <details className="rounded-md border bg-card">
          <summary className="cursor-pointer px-4 py-2.5 text-sm font-medium">Executed Playwright code</summary>
          <pre className="max-h-[50vh] overflow-auto border-t bg-[#0f1117] p-4 font-mono text-[12px] text-[#e6e8ef]">{r.generated_code}</pre>
        </details>
      )}
    </div>
  );
}

function RunView() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const params = useSearchParams();
  const { canWrite } = useWorkspace();
  const { data: e, mutate, error } = useSWR<ExecutionDetail>(`/executions/${id}`, fetcher, {
    refreshInterval: (d) => (d && ACTIVE_STATUSES.includes(d.status) ? 1500 : 0),
  });
  const selected = params.get("result") ?? e?.results.find((r) => r.status !== "passed")?.id ?? e?.results[0]?.id;
  if (error) return <Alert variant="error" title="Run not found">It may belong to another project.</Alert>;
  if (!e) return <Spinner />;
  const active = ACTIVE_STATUSES.includes(e.status);
  const done = e.results.filter((r) => !["queued", "running"].includes(r.status)).length;

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight">Run {e.id.slice(0, 8)}</h1>
            <StatusBadge status={e.status} />
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{e.browser} · {e.workers > 1 ? `${e.workers} parallel workers` : "sequential"} · {e.trigger} · started {timeAgo(e.created_at)} · {formatDuration(e.duration_ms)}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {active && canWrite && <Button variant="outline" onClick={async () => { await api(`/executions/${e.id}/cancel`, { method: "POST" }); mutate(); }}><Square /> Cancel</Button>}
          {!active && (
            <>
              <Button variant="outline" asChild><a href={`/api/executions/${e.id}/report?format=html`}><FileText /> HTML report</a></Button>
              {e.reports.some((a) => a.name === "report.pdf") && <Button variant="outline" asChild><a href={`/api/executions/${e.id}/report?format=pdf`}><Download /> PDF</a></Button>}
              <Button variant="ghost" asChild><a href={`/api/executions/${e.id}/report?format=allure`}>Allure results</a></Button>
            </>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {[["Tests", e.total], ["Passed", e.passed], ["Failed", e.failed], ["Flaky", e.flaky], ["Pass rate", e.total && !active ? `${e.summary.pass_rate}%` : "–"]].map(([l, v]) => (
          <div key={l as string} className="rounded-lg border bg-card px-4 py-3"><p className="text-xs text-muted-foreground">{l}</p><p className="tabular text-xl font-semibold" data-testid={`stat-${String(l).toLowerCase().replace(" ", "-")}`}>{v}</p></div>
        ))}
      </div>
      {active && (
        <div className="grid gap-1.5">
          <div className="flex items-center gap-2 text-sm text-muted-foreground"><Spinner /> Running in an isolated browser… {done}/{e.total} finished</div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full bg-primary transition-all" style={{ width: `${e.total ? (done / e.total) * 100 : 0}%` }} /></div>
        </div>
      )}
      {e.error_message && <Alert variant="error">{e.error_message}</Alert>}
      {e.recommendations.length > 0 && (
        <Alert variant="info"><span className="flex items-start gap-2"><Lightbulb className="mt-0.5 h-4 w-4 shrink-0" /><span>{e.recommendations.join(" ")}</span></span></Alert>
      )}

      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        <ul className="grid content-start gap-1" data-testid="results-list">
          {e.results.map((r) => (
            <li key={r.id}>
              <button onClick={() => router.replace(`/runs/${e.id}?result=${r.id}`)}
                className={cn("flex w-full items-start gap-2 rounded-md border bg-card px-3 py-2 text-left text-sm hover:border-primary/40", selected === r.id && "border-primary ring-1 ring-primary/30")}>
                <StatusBadge status={r.status} className="mt-0.5 shrink-0" />
                <span className="min-w-0 flex-1">
                  <span className="line-clamp-2">{r.test_title}</span>
                  {r.failure && <span className="block text-xs text-muted-foreground">{r.failure.label}</span>}
                </span>
                <span className="tabular shrink-0 text-xs text-muted-foreground">{formatDuration(r.duration_ms)}</span>
              </button>
            </li>
          ))}
        </ul>
        <div className="min-w-0">{selected ? <ResultDetail key={selected} id={selected} listStatus={e.results.find((r) => r.id === selected)?.status} /> : null}</div>
      </div>
    </div>
  );
}

export default function RunPage() {
  return <React.Suspense><RunView /></React.Suspense>;
}
