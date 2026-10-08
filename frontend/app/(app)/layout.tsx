"use client";

import { AppShell } from "@/components/app-shell";
import { WorkspaceProvider } from "@/components/workspace";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <WorkspaceProvider>
      <AppShell>{children}</AppShell>
    </WorkspaceProvider>
  );
}
