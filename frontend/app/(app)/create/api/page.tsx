"use client";

import { FileUp, Lock, Sparkles } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import useSWR from "swr";
import { TestReview } from "@/components/test-review";
import { Alert, Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Field, Input, PageHeader, Select, Spinner, Tabs, TabsContent, TabsList, TabsTrigger, Textarea } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { api, fetcher } from "@/lib/api";
import type { Collection, Job, TestCase } from "@/lib/types";

const METHOD_COLOR: Record<string, string> = {
  GET: "text-[#106b10] bg-[#e7f6e7]", POST: "text-[#2b4fb3] bg-[#e8edfb]", PUT: "text-[#8a5b00] bg-[#fdf3dc]",
  PATCH: "text-[#7a3fb0] bg-[#f2eafb]", DELETE: "text-[#a72b2b] bg-[#fbe9e9]",
};

function ImportForm({ onImported }: { onImported: (c: Collection) => void }) {
  const { project } = useWorkspace();
  const router = useRouter();
  const [specText, setSpecText] = React.useState("");
  const [specUrl, setSpecUrl] = React.useState("");
  const [baseUrl, setBaseUrl] = React.useState("");
  const [token, setToken] = React.useState("");
  const [tab, setTab] = React.useState("url");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [manual, setManual] = React.useState({ method: "GET", url: "", headers: "", body: "", status: "200", title: "" });

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 5_000_000) { setError("The file is larger than 5 MB."); return; }
    setSpecText(await f.text());
    setTab("paste");
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!project) return;
    setBusy(true);
    setError(null);
    try {
      if (tab === "manual") {
        let headers: Record<string, string> = {};
        let body: unknown = undefined;
        try {
          headers = manual.headers.trim() ? JSON.parse(manual.headers) : {};
          body = manual.body.trim() ? JSON.parse(manual.body) : undefined;
        } catch {
          throw new Error("Headers and body must be valid JSON.");
        }
        const tc = await api<TestCase>(`/projects/${project.id}/api-requests`, {
          json: { method: manual.method, url: manual.url, headers, body, title: manual.title || null,
                  expected_status: manual.status.split(",").map((s) => Number(s.trim())).filter(Boolean) },
        });
        router.push(`/tests/${tc.id}`);
        return;
      }
      const c = await api<Collection>(`/projects/${project.id}/api-collections`, {
        json: { spec_text: tab === "paste" ? specText : null, spec_url: tab === "url" ? specUrl : null, base_url: baseUrl || null, api_token: token || null },
      });
      onImported(c);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader><div><CardTitle>Where is your API described?</CardTitle><CardDescription>OpenAPI 3.x, Swagger 2.0 and Postman v2.1 collections are supported, in JSON or YAML.</CardDescription></div></CardHeader>
      <CardContent>
        <form onSubmit={submit} className="grid gap-4">
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList>
              <TabsTrigger value="url">Specification URL</TabsTrigger>
              <TabsTrigger value="paste">Upload or paste</TabsTrigger>
              <TabsTrigger value="manual">Single request</TabsTrigger>
            </TabsList>
            <TabsContent value="url">
              <Field label="OpenAPI / Swagger URL" htmlFor="spec-url"><Input id="spec-url" value={specUrl} onChange={(e) => setSpecUrl(e.target.value)} placeholder="https://api.example.com/openapi.json" required={tab === "url"} /></Field>
            </TabsContent>
            <TabsContent value="paste" className="grid gap-3">
              <label className="flex w-fit cursor-pointer items-center gap-2 rounded-md border bg-card px-3 py-2 text-sm hover:bg-muted">
                <FileUp className="h-4 w-4" /> Choose a file
                <input type="file" accept=".json,.yaml,.yml" className="sr-only" onChange={onFile} />
              </label>
              <Textarea aria-label="Specification content" value={specText} onChange={(e) => setSpecText(e.target.value)} rows={8} className="font-mono text-xs" placeholder='{"openapi": "3.0.0", ...}' required={tab === "paste"} />
            </TabsContent>
            <TabsContent value="manual" className="grid gap-3">
              <div className="grid gap-3 sm:grid-cols-[8rem_1fr]">
                <Field label="Method" htmlFor="m-method"><Select id="m-method" value={manual.method} onChange={(e) => setManual({ ...manual, method: e.target.value })}>{["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => <option key={m}>{m}</option>)}</Select></Field>
                <Field label="URL" htmlFor="m-url"><Input id="m-url" value={manual.url} onChange={(e) => setManual({ ...manual, url: e.target.value })} placeholder="https://api.example.com/v1/users" required={tab === "manual"} /></Field>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Headers (JSON)" htmlFor="m-headers" hint='Use {{variable}} for secrets, e.g. {"Authorization": "Bearer {{api_token}}"}'><Textarea id="m-headers" rows={3} className="font-mono text-xs" value={manual.headers} onChange={(e) => setManual({ ...manual, headers: e.target.value })} /></Field>
                <Field label="Body (JSON)" htmlFor="m-body"><Textarea id="m-body" rows={3} className="font-mono text-xs" value={manual.body} onChange={(e) => setManual({ ...manual, body: e.target.value })} /></Field>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Expected status" htmlFor="m-status" hint="Comma separated, e.g. 200 or 200,204"><Input id="m-status" value={manual.status} onChange={(e) => setManual({ ...manual, status: e.target.value })} /></Field>
                <Field label="Test name (optional)" htmlFor="m-title"><Input id="m-title" value={manual.title} onChange={(e) => setManual({ ...manual, title: e.target.value })} /></Field>
              </div>
            </TabsContent>
          </Tabs>
          {tab !== "manual" && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="API base URL (optional)" htmlFor="base-url" hint="Overrides the server address in the specification."><Input id="base-url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://staging-api.example.com" /></Field>
              <Field label="API token (optional)" htmlFor="api-token" hint={<span className="inline-flex items-center gap-1"><Lock className="h-3 w-3" /> Stored encrypted as api_token and sent as a bearer token.</span>}>
                <Input id="api-token" type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" />
              </Field>
            </div>
          )}
          {error && <Alert variant="error">{error}</Alert>}
          <div><Button type="submit" loading={busy}>{tab === "manual" ? "Create API test" : "Import API"}</Button></div>
        </form>
      </CardContent>
    </Card>
  );
}

function Endpoints({ collection, selected, setSelected }: { collection: Collection; selected: Set<string>; setSelected: (s: Set<string>) => void }) {
  const eps = collection.endpoints ?? [];
  const all = eps.length > 0 && eps.every((e) => selected.has(e.id));
  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <table className="w-full text-sm" data-testid="endpoints">
        <thead>
          <tr className="border-b bg-muted/40 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <th className="w-10 px-3 py-2"><input type="checkbox" aria-label="Select all endpoints" checked={all} onChange={() => setSelected(all ? new Set() : new Set(eps.map((e) => e.id)))} /></th>
            <th className="px-3 py-2">Endpoint</th>
            <th className="hidden px-3 py-2 md:table-cell">Summary</th>
            <th className="px-3 py-2">Documented responses</th>
          </tr>
        </thead>
        <tbody>
          {eps.map((e) => (
            <tr key={e.id} className="border-b last:border-0">
              <td className="px-3 py-2"><input type="checkbox" aria-label={`Select ${e.method} ${e.path}`} checked={selected.has(e.id)} onChange={() => { const n = new Set(selected); n.has(e.id) ? n.delete(e.id) : n.add(e.id); setSelected(n); }} /></td>
              <td className="px-3 py-2">
                <span className={`mr-2 inline-block w-16 rounded px-1.5 py-0.5 text-center font-mono text-[11px] font-semibold ${METHOD_COLOR[e.method] ?? "bg-muted"}`}>{e.method}</span>
                <span className="font-mono text-[13px]">{e.path}</span>
                {e.requires_auth && <Lock className="ml-1.5 inline h-3.5 w-3.5 text-muted-foreground" aria-label="Requires authentication" />}
              </td>
              <td className="hidden px-3 py-2 text-muted-foreground md:table-cell">{e.summary}</td>
              <td className="px-3 py-2"><div className="flex flex-wrap gap-1">{Object.keys(e.responses).map((c) => <Badge key={c} variant="outline" className="font-mono">{c}</Badge>)}</div></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ApiFlow() {
  const router = useRouter();
  const params = useSearchParams();
  const collectionId = params.get("collection");
  const jobId = params.get("job");
  const setParam = (k: string, v: string) => { const p = new URLSearchParams(params.toString()); p.set(k, v); router.replace(`/create/api?${p.toString()}`); };
  const { data: collection } = useSWR<Collection>(collectionId ? `/api-collections/${collectionId}` : null, fetcher);
  const { data: job } = useSWR<Job>(jobId ? `/generation-jobs/${jobId}` : null, fetcher, { refreshInterval: (j) => (j && ["queued", "running"].includes(j.status) ? 1000 : 0) });
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => { if (collection?.endpoints) setSelected(new Set(collection.endpoints.map((e) => e.id))); }, [collection?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function generate() {
    if (!collection) return;
    setBusy(true);
    setError(null);
    try {
      const j = await api<Job>(`/api-collections/${collection.id}/generate`, { json: { endpoint_ids: [...selected], use_ai: true } });
      setParam("job", j.id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6">
      <PageHeader title="Test an API" description="Import your API description. We generate positive, negative, boundary, auth and schema checks from it and run them for real." />
      {!collectionId && <ImportForm onImported={(c) => setParam("collection", c.id)} />}
      {collection && (
        <Card>
          <CardHeader>
            <div>
              <CardTitle>{collection.name}</CardTitle>
              <CardDescription>{collection.endpoint_count} endpoints · {collection.source_type} · requests go to <span className="font-mono">{collection.base_url}</span></CardDescription>
            </div>
            {!jobId && <Button onClick={generate} loading={busy} disabled={!selected.size} data-testid="generate-api-tests"><Sparkles /> Generate tests ({selected.size})</Button>}
          </CardHeader>
          <CardContent className="grid gap-3">
            <Endpoints collection={collection} selected={selected} setSelected={setSelected} />
            <p className="text-xs text-muted-foreground">Expected status codes come from the responses documented for each endpoint. Where a code is not documented, the test accepts the whole class (for example any 4xx) and says so.</p>
            {error && <Alert variant="error">{error}</Alert>}
          </CardContent>
        </Card>
      )}
      {job && ["queued", "running"].includes(job.status) && <Card><CardContent className="flex items-center gap-3 py-6 text-sm"><Spinner /> Generating API tests…</CardContent></Card>}
      {job?.status === "failed" && <Alert variant="error" title="Test generation failed">{job.error_message}</Alert>}
      {job?.status === "completed" && (
        <TestReview ids={job.result.test_case_ids ?? []} heading={
          <div>
            <h2 className="text-base font-semibold">{job.result.created} API tests generated</h2>
            <p className="text-sm text-muted-foreground">Planned by {job.result.ai?.used ? `the built-in planner and ${job.model}` : "the built-in planner"} from the specification.</p>
          </div>
        } />
      )}
    </div>
  );
}

export default function ApiPage() {
  return <React.Suspense><ApiFlow /></React.Suspense>;
}
