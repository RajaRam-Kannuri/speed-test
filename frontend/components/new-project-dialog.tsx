"use client";

import * as React from "react";
import { Alert, Button, Dialog, DialogContent, Field, Input, Textarea } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";

export function NewProjectForm({ onCreated }: { onCreated?: (p: Project) => void }) {
  const { orgId, refreshProjects, setProjectId } = useWorkspace();
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [baseUrl, setBaseUrl] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const p = await api<Project>(`/organizations/${orgId}/projects`, { json: { name, description, base_url: baseUrl || null } });
      await refreshProjects();
      setProjectId(p.id);
      onCreated?.(p);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="grid gap-4">
      <Field label="Project name" htmlFor="project-name">
        <Input id="project-name" required value={name} onChange={(e) => setName(e.target.value)} placeholder="Customer portal" autoFocus />
      </Field>
      <Field label="Application URL (optional)" htmlFor="project-url" hint="Relative paths in tests are resolved against this address.">
        <Input id="project-url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://staging.example.com" />
      </Field>
      <Field label="Description (optional)" htmlFor="project-desc">
        <Textarea id="project-desc" value={description} onChange={(e) => setDescription(e.target.value)} rows={2} />
      </Field>
      {error && <Alert variant="error">{error}</Alert>}
      <div className="flex justify-end">
        <Button type="submit" loading={busy}>Create project</Button>
      </div>
    </form>
  );
}

export function NewProjectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="New project" description="A project groups the tests, runs and environments for one application.">
        <NewProjectForm onCreated={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}
