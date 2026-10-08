"use client";

import { Copy, Lock, Plus, Trash2 } from "lucide-react";
import * as React from "react";
import useSWR from "swr";
import { useCapabilities } from "@/components/run-controls";
import { Alert, Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Checkbox, Field, Input, PageHeader, Select, Spinner, Tabs, TabsContent, TabsList, TabsTrigger, Textarea } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { api, fetcher } from "@/lib/api";
import type { Environment } from "@/lib/types";
import { timeAgo } from "@/lib/utils";

function ProjectSettings() {
  const { project, refreshProjects, canWrite } = useWorkspace();
  const [form, setForm] = React.useState({ name: project?.name ?? "", base_url: project?.base_url ?? "", description: project?.description ?? "" });
  const [msg, setMsg] = React.useState<{ ok: boolean; text: string } | null>(null);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api(`/projects/${project!.id}`, { method: "PATCH", json: { ...form, base_url: form.base_url || "" } });
      await refreshProjects();
      setMsg({ ok: true, text: "Project saved" });
    } catch (err) {
      setMsg({ ok: false, text: (err as Error).message });
    }
  }
  return (
    <Card>
      <CardHeader><div><CardTitle>Project</CardTitle><CardDescription>Name and default application address</CardDescription></div></CardHeader>
      <CardContent>
        <form onSubmit={save} className="grid max-w-xl gap-3">
          <Field label="Name" htmlFor="p-name"><Input id="p-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} disabled={!canWrite} /></Field>
          <Field label="Application URL" htmlFor="p-url"><Input id="p-url" value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} disabled={!canWrite} /></Field>
          <Field label="Description" htmlFor="p-desc"><Textarea id="p-desc" rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} disabled={!canWrite} /></Field>
          {msg && <Alert variant={msg.ok ? "success" : "error"}>{msg.text}</Alert>}
          {canWrite && <Button type="submit" className="w-fit">Save project</Button>}
        </form>
      </CardContent>
    </Card>
  );
}

function Environments() {
  const { project, canWrite } = useWorkspace();
  const { data: envs, mutate } = useSWR<Environment[]>(project ? `/projects/${project.id}/environments` : null, fetcher);
  const [envId, setEnvId] = React.useState<string>("");
  const [v, setV] = React.useState({ key: "", value: "", is_secret: false });
  const [newEnv, setNewEnv] = React.useState({ name: "", base_url: "" });
  const [error, setError] = React.useState<string | null>(null);
  const env = envs?.find((e) => e.id === envId) ?? envs?.[0];

  async function addVar(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api(`/projects/${project!.id}/environments/${env!.id}/variables`, { method: "PUT", json: v });
      setV({ key: "", value: "", is_secret: false });
      mutate();
    } catch (err) { setError((err as Error).message); }
  }
  async function addEnv(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const created = await api<Environment>(`/projects/${project!.id}/environments`, { json: { ...newEnv, base_url: newEnv.base_url || null } });
      setNewEnv({ name: "", base_url: "" });
      await mutate();
      setEnvId(created.id);
    } catch (err) { setError((err as Error).message); }
  }

  if (!envs) return <Spinner />;
  return (
    <Card>
      <CardHeader><div><CardTitle>Environments and test data</CardTitle><CardDescription>Variables are available in tests as {"{{name}}"}. Secrets are encrypted at rest, never displayed again, and redacted from logs and reports.</CardDescription></div></CardHeader>
      <CardContent className="grid gap-5">
        <div className="flex flex-wrap items-center gap-2">
          {envs.map((e) => (
            <button key={e.id} onClick={() => setEnvId(e.id)} className={`rounded-md border px-3 py-1.5 text-sm ${env?.id === e.id ? "border-primary bg-accent font-medium" : "hover:bg-muted"}`}>
              {e.name}{e.is_default ? " (default)" : ""}
            </button>
          ))}
        </div>
        {env && (
          <>
            <p className="text-sm text-muted-foreground">Base URL: <span className="font-mono">{env.base_url ?? project?.base_url ?? "not set"}</span></p>
            <table className="w-full text-sm" data-testid="env-variables">
              <thead><tr className="text-left text-xs text-muted-foreground"><th className="py-1">Variable</th><th>Value</th><th /></tr></thead>
              <tbody>
                {env.variables.map((x) => (
                  <tr key={x.id} className="border-t">
                    <td className="py-2 font-mono text-[13px]">{x.key}</td>
                    <td className="py-2">{x.is_secret ? <Badge variant="outline"><Lock className="h-3 w-3" /> Secret, set</Badge> : <span className="font-mono text-[13px]">{x.value}</span>}</td>
                    <td className="py-2 text-right">{canWrite && <Button variant="ghost" size="icon" aria-label={`Delete ${x.key}`} onClick={async () => { await api(`/projects/${project!.id}/environments/${env.id}/variables/${encodeURIComponent(x.key)}`, { method: "DELETE" }); mutate(); }}><Trash2 /></Button>}</td>
                  </tr>
                ))}
                {env.variables.length === 0 && <tr><td colSpan={3} className="py-3 text-sm text-muted-foreground">No variables yet.</td></tr>}
              </tbody>
            </table>
            {canWrite && (
              <form onSubmit={addVar} className="grid gap-2 sm:grid-cols-[12rem_1fr_auto_auto] sm:items-end">
                <Field label="Name" htmlFor="var-key"><Input id="var-key" required value={v.key} onChange={(e) => setV({ ...v, key: e.target.value })} placeholder="username" /></Field>
                <Field label="Value" htmlFor="var-value"><Input id="var-value" required type={v.is_secret ? "password" : "text"} value={v.value} onChange={(e) => setV({ ...v, value: e.target.value })} autoComplete="off" /></Field>
                <Checkbox className="pb-2" label="Secret" checked={v.is_secret} onChange={(e) => setV({ ...v, is_secret: e.target.checked })} />
                <Button type="submit"><Plus /> Save</Button>
              </form>
            )}
          </>
        )}
        {canWrite && (
          <form onSubmit={addEnv} className="grid gap-2 border-t pt-4 sm:grid-cols-[12rem_1fr_auto] sm:items-end">
            <Field label="New environment" htmlFor="env-name"><Input id="env-name" required value={newEnv.name} onChange={(e) => setNewEnv({ ...newEnv, name: e.target.value })} placeholder="Staging" /></Field>
            <Field label="Base URL" htmlFor="env-url"><Input id="env-url" value={newEnv.base_url} onChange={(e) => setNewEnv({ ...newEnv, base_url: e.target.value })} placeholder="https://staging.example.com" /></Field>
            <Button type="submit" variant="outline">Add environment</Button>
          </form>
        )}
        {error && <Alert variant="error">{error}</Alert>}
      </CardContent>
    </Card>
  );
}

interface Members { members: { id: string; name: string; email: string; role: string }[]; invitations: { id: string; email: string; role: string; expires_at: string }[] }

function Team() {
  const { orgId, role, me } = useWorkspace();
  const { data, mutate } = useSWR<Members>(`/organizations/${orgId}/members`, fetcher);
  const [email, setEmail] = React.useState("");
  const [newRole, setNewRole] = React.useState("member");
  const [link, setLink] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const isAdmin = role === "owner" || role === "admin";
  async function invite(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const res = await api<{ accept_path: string }>(`/organizations/${orgId}/invitations`, { json: { email, role: newRole } });
      setLink(`${window.location.origin}${res.accept_path}`);
      setEmail("");
      mutate();
    } catch (err) { setError((err as Error).message); }
  }
  async function changeRole(id: string, r: string) {
    setError(null);
    try { await api(`/organizations/${orgId}/members/${id}`, { method: "PATCH", json: { role: r } }); mutate(); } catch (err) { setError((err as Error).message); }
  }
  if (!data) return <Spinner />;
  return (
    <Card>
      <CardHeader><div><CardTitle>Team</CardTitle><CardDescription>Owners and admins manage members. Members create and run tests. Viewers can only read.</CardDescription></div></CardHeader>
      <CardContent className="grid gap-4">
        <table className="w-full text-sm">
          <tbody>
            {data.members.map((m) => (
              <tr key={m.id} className="border-t first:border-0">
                <td className="py-2"><p className="font-medium">{m.name}{m.email === me.email ? " (you)" : ""}</p><p className="text-xs text-muted-foreground">{m.email}</p></td>
                <td className="w-40 py-2">
                  {isAdmin && m.email !== me.email ? (
                    <Select aria-label={`Role for ${m.email}`} value={m.role} onChange={(e) => changeRole(m.id, e.target.value)}>{["owner", "admin", "member", "viewer"].map((r) => <option key={r}>{r}</option>)}</Select>
                  ) : <Badge variant="outline">{m.role}</Badge>}
                </td>
              </tr>
            ))}
            {data.invitations.map((i) => (
              <tr key={i.id} className="border-t"><td className="py-2"><p>{i.email}</p><p className="text-xs text-muted-foreground">Invitation pending</p></td><td><Badge>{i.role}</Badge></td></tr>
            ))}
          </tbody>
        </table>
        {isAdmin && (
          <form onSubmit={invite} className="grid gap-2 border-t pt-4 sm:grid-cols-[1fr_9rem_auto] sm:items-end">
            <Field label="Invite by email" htmlFor="inv-email"><Input id="inv-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
            <Field label="Role" htmlFor="inv-role"><Select id="inv-role" value={newRole} onChange={(e) => setNewRole(e.target.value)}>{["admin", "member", "viewer"].map((r) => <option key={r}>{r}</option>)}</Select></Field>
            <Button type="submit">Create invitation</Button>
          </form>
        )}
        {link && <Alert variant="success" title="Invitation link created">Email delivery is not configured, so share this link with the person: <span className="break-all font-mono text-xs">{link}</span></Alert>}
        {error && <Alert variant="error">{error}</Alert>}
      </CardContent>
    </Card>
  );
}

interface Token { id: string; name: string; prefix: string; role: string; project_id: string | null; created_at: string; last_used_at: string | null; revoked: boolean }

function CiTokens() {
  const { orgId, project, role } = useWorkspace();
  const isAdmin = role === "owner" || role === "admin";
  const { data, mutate } = useSWR<Token[]>(isAdmin ? `/organizations/${orgId}/api-tokens` : null, fetcher);
  const [name, setName] = React.useState("");
  const [token, setToken] = React.useState<string | null>(null);
  if (!isAdmin) return <Alert>Only owners and admins can manage API tokens.</Alert>;
  async function create(e: React.FormEvent) {
    e.preventDefault();
    const res = await api<{ token: string }>(`/organizations/${orgId}/api-tokens`, { json: { name, project_id: project?.id } });
    setToken(res.token);
    setName("");
    mutate();
  }
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const curl = `curl -X POST ${origin}/api/projects/${project?.id}/executions \\\n  -H "Authorization: Bearer $LORVENLAX_TOKEN" -H "Content-Type: application/json" \\\n  -d '{"suite_id": "<suite-id>", "idempotency_key": "$CI_PIPELINE_ID"}'`;
  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader><div><CardTitle>API tokens for CI/CD</CardTitle><CardDescription>Tokens are scoped to this project and can create and read runs. They are shown once.</CardDescription></div></CardHeader>
        <CardContent className="grid gap-4">
          <form onSubmit={create} className="flex flex-wrap items-end gap-2">
            <div className="w-64"><Field label="Token name" htmlFor="tok-name"><Input id="tok-name" required value={name} onChange={(e) => setName(e.target.value)} placeholder="GitHub Actions" /></Field></div>
            <Button type="submit">Create token</Button>
          </form>
          {token && <Alert variant="success" title="Copy this token now"><span className="break-all font-mono text-xs">{token}</span> <Button variant="link" size="sm" onClick={() => navigator.clipboard?.writeText(token)}><Copy /> Copy</Button></Alert>}
          <table className="w-full text-sm"><tbody>
            {data?.map((t) => (
              <tr key={t.id} className="border-t"><td className="py-2">{t.name}<span className="ml-2 font-mono text-xs text-muted-foreground">{t.prefix}…</span></td>
                <td className="text-xs text-muted-foreground">{t.last_used_at ? `used ${timeAgo(t.last_used_at)}` : "never used"}</td>
                <td className="text-right">{t.revoked ? <Badge>revoked</Badge> : <Button size="sm" variant="ghost" onClick={async () => { await api(`/organizations/${orgId}/api-tokens/${t.id}`, { method: "DELETE" }); mutate(); }}>Revoke</Button>}</td></tr>
            ))}
          </tbody></table>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><div><CardTitle>Trigger runs from a pipeline</CardTitle><CardDescription>Works with GitHub Actions, GitLab CI, Jenkins and Azure DevOps. Ready-made pipeline files are in the repository under docs/ci.</CardDescription></div></CardHeader>
        <CardContent><pre className="overflow-x-auto rounded-md bg-[#0f1117] p-3 font-mono text-xs text-[#e6e8ef]">{curl}</pre></CardContent>
      </Card>
    </div>
  );
}

function AuditLog() {
  const { orgId, role } = useWorkspace();
  const isAdmin = role === "owner" || role === "admin";
  const { data } = useSWR<{ id: string; action: string; user: string | null; resource_type: string | null; details: Record<string, unknown>; created_at: string }[]>(isAdmin ? `/organizations/${orgId}/audit-logs` : null, fetcher);
  if (!isAdmin) return <Alert>Only owners and admins can view the audit log.</Alert>;
  if (!data) return <Spinner />;
  return (
    <Card>
      <CardHeader><div><CardTitle>Audit log</CardTitle><CardDescription>Security-relevant actions, including authorisation confirmations and every self-healing decision</CardDescription></div></CardHeader>
      <CardContent className="px-0">
        <table className="w-full text-sm" data-testid="audit-log"><tbody>
          {data.map((a) => (
            <tr key={a.id} className="border-t align-top">
              <td className="whitespace-nowrap px-5 py-2 text-xs text-muted-foreground">{new Date(a.created_at).toLocaleString()}</td>
              <td className="px-3 py-2 font-mono text-xs">{a.action}</td>
              <td className="px-3 py-2 text-xs">{a.user ?? "system"}</td>
              <td className="px-5 py-2 font-mono text-[11px] text-muted-foreground">{Object.keys(a.details).length ? JSON.stringify(a.details).slice(0, 160) : ""}</td>
            </tr>
          ))}
        </tbody></table>
      </CardContent>
    </Card>
  );
}

function System() {
  const caps = useCapabilities();
  if (!caps) return <Spinner />;
  return (
    <Card>
      <CardHeader><div><CardTitle>AI and execution</CardTitle><CardDescription>What this deployment can do right now</CardDescription></div></CardHeader>
      <CardContent className="grid gap-3 text-sm">
        <p>AI provider: {caps.ai.enabled ? <Badge variant="good">Claude ({caps.ai.model})</Badge> : <Badge>Not configured</Badge>}</p>
        {!caps.ai.enabled && <Alert variant="info">Set <code>LLX_ANTHROPIC_API_KEY</code> on the API and worker to enable Claude for test planning and the assistant. Until then, built-in deterministic agents do the work and the interface says so.</Alert>}
        <p>Browsers: {Object.entries(caps.browsers).map(([b, ok]) => <Badge key={b} variant={ok ? "good" : "default"} className="mr-1">{b}{ok ? "" : " (not installed)"}</Badge>)}</p>
      </CardContent>
    </Card>
  );
}

export default function SettingsPage() {
  const { project } = useWorkspace();
  return (
    <div>
      <PageHeader title="Settings" />
      <Tabs defaultValue="project">
        <TabsList><TabsTrigger value="project">Project</TabsTrigger><TabsTrigger value="team">Team</TabsTrigger><TabsTrigger value="ci">API &amp; CI/CD</TabsTrigger><TabsTrigger value="audit">Audit log</TabsTrigger><TabsTrigger value="system">AI &amp; system</TabsTrigger></TabsList>
        <TabsContent value="project" className="grid gap-6">{project ? <><ProjectSettings key={project.id} /><Environments /></> : <Alert>Create a project first.</Alert>}</TabsContent>
        <TabsContent value="team"><Team /></TabsContent>
        <TabsContent value="ci"><CiTokens /></TabsContent>
        <TabsContent value="audit"><AuditLog /></TabsContent>
        <TabsContent value="system"><System /></TabsContent>
      </Tabs>
    </div>
  );
}
