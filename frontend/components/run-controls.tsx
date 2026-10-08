"use client";

import { Play } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import useSWR from "swr";
import { Alert, Button, Select } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { ApiError, api, fetcher } from "@/lib/api";
import type { Environment, Execution } from "@/lib/types";

interface Capabilities { browsers: Record<string, boolean>; ai: { enabled: boolean; model: string | null; note: string | null } }

export function useCapabilities() {
  return useSWR<Capabilities>("/capabilities", fetcher).data;
}

export function RunButton({ testCaseIds, label = "Run selected", suiteId, size = "default", onStarted }:
  { testCaseIds: string[]; label?: string; suiteId?: string; size?: "default" | "sm"; onStarted?: (e: Execution) => void }) {
  const { project } = useWorkspace();
  const router = useRouter();
  const caps = useCapabilities();
  const { data: envs } = useSWR<Environment[]>(project ? `/projects/${project.id}/environments` : null, fetcher);
  const [browser, setBrowser] = React.useState("chromium");
  const [envId, setEnvId] = React.useState("");
  const [workers, setWorkers] = React.useState(2);
  const [retries, setRetries] = React.useState(0);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [showOptions, setShowOptions] = React.useState(false);

  async function run() {
    if (!project) return;
    setBusy(true);
    setError(null);
    try {
      const e = await api<Execution>(`/projects/${project.id}/executions`, {
        json: { test_case_ids: testCaseIds, suite_id: suiteId, browser, environment_id: envId || null, workers, retries },
      });
      onStarted?.(e);
      router.push(`/runs/${e.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.detail && typeof err.detail === "object" && "tests" in (err.detail as object)) {
        const d = err.detail as { message: string; tests: { title: string; errors: string[] }[] };
        setError(`${d.message} ${d.tests.map((t) => `"${t.title}": ${t.errors[0]}`).join("; ")}`);
      } else setError((err as Error).message);
      setBusy(false);
    }
  }

  const disabled = (!testCaseIds.length && !suiteId) || busy;
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button size={size} onClick={run} loading={busy} disabled={disabled} data-testid="run-tests"><Play /> {label}{testCaseIds.length ? ` (${testCaseIds.length})` : ""}</Button>
        <Button size={size} variant="ghost" onClick={() => setShowOptions((s) => !s)} type="button">Run options</Button>
      </div>
      {showOptions && (
        <div className="grid grid-cols-2 gap-2 rounded-md border bg-muted/40 p-3 sm:grid-cols-4">
          <label className="grid gap-1 text-xs font-medium">Browser
            <Select value={browser} onChange={(e) => setBrowser(e.target.value)}>
              {(["chromium", "firefox", "webkit"] as const).map((b) => (
                <option key={b} value={b} disabled={caps ? !caps.browsers[b] : false}>{b}{caps && !caps.browsers[b] ? " (not installed)" : ""}</option>
              ))}
            </Select>
          </label>
          <label className="grid gap-1 text-xs font-medium">Environment
            <Select value={envId} onChange={(e) => setEnvId(e.target.value)}>
              <option value="">Default</option>
              {envs?.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
            </Select>
          </label>
          <label className="grid gap-1 text-xs font-medium">Parallel workers
            <Select value={workers} onChange={(e) => setWorkers(Number(e.target.value))}>{[1, 2, 4].map((n) => <option key={n} value={n}>{n === 1 ? "1 (sequential)" : n}</option>)}</Select>
          </label>
          <label className="grid gap-1 text-xs font-medium">Retries
            <Select value={retries} onChange={(e) => setRetries(Number(e.target.value))}>{[0, 1, 2].map((n) => <option key={n} value={n}>{n}</option>)}</Select>
          </label>
        </div>
      )}
      {error && <Alert variant="error">{error}</Alert>}
    </div>
  );
}
