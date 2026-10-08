"use client";

import { useRouter } from "next/navigation";
import * as React from "react";
import useSWR from "swr";
import { ApiError, api, fetcher } from "@/lib/api";
import type { Me, Project } from "@/lib/types";

interface Workspace {
  me: Me;
  orgId: string;
  role: string;
  projects: Project[];
  project: Project | null;
  setProjectId: (id: string) => void;
  setOrgId: (id: string) => void;
  refreshProjects: () => Promise<unknown>;
  refreshMe: () => Promise<unknown>;
  canWrite: boolean;
}

const Ctx = React.createContext<Workspace | null>(null);

function stored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function store(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable */
  }
}

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { data: me, error, mutate: refreshMe } = useSWR<Me>("/auth/me", fetcher, { shouldRetryOnError: false });
  const [orgId, setOrgIdState] = React.useState<string | null>(null);
  const [projectId, setProjectIdState] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (error instanceof ApiError && error.status === 401) router.replace("/login");
  }, [error, router]);

  React.useEffect(() => {
    if (!me) return;
    const saved = stored("llx.org");
    const valid = me.organizations.find((o) => o.id === saved) ?? me.organizations[0];
    if (valid) setOrgIdState(valid.id);
  }, [me]);

  const { data: projects, mutate: refreshProjects } = useSWR<Project[]>(orgId ? `/organizations/${orgId}/projects` : null, fetcher);

  React.useEffect(() => {
    if (!projects) return;
    const saved = stored("llx.project");
    const valid = projects.find((p) => p.id === saved) ?? projects[0];
    setProjectIdState(valid ? valid.id : null);
  }, [projects]);

  if (error && !(error instanceof ApiError && error.status === 401)) {
    return <div className="p-10 text-sm text-destructive">Could not load your account: {String(error.message)}</div>;
  }
  if (!me || !orgId || !projects) {
    return <div className="flex h-screen items-center justify-center text-sm text-muted-foreground">Loading workspace…</div>;
  }
  const org = me.organizations.find((o) => o.id === orgId)!;
  const value: Workspace = {
    me,
    orgId,
    role: org.role,
    projects,
    project: projects.find((p) => p.id === projectId) ?? null,
    setProjectId: (id) => {
      store("llx.project", id);
      setProjectIdState(id);
    },
    setOrgId: (id) => {
      store("llx.org", id);
      setOrgIdState(id);
      setProjectIdState(null);
    },
    refreshProjects,
    refreshMe,
    canWrite: org.role !== "viewer",
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useWorkspace(): Workspace {
  const ctx = React.useContext(Ctx);
  if (!ctx) throw new Error("useWorkspace must be used inside WorkspaceProvider");
  return ctx;
}

export async function logout() {
  await api("/auth/logout", { method: "POST" }).catch(() => undefined);
  window.location.href = "/login";
}
