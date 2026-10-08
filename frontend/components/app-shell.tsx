"use client";

import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { Bot, ChevronDown, FolderKanban, LogOut, Plus, Settings } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";
import { CreateTestDialog } from "@/components/create-test-dialog";
import { NewProjectDialog } from "@/components/new-project-dialog";
import { Button } from "@/components/ui";
import { logout, useWorkspace } from "@/components/workspace";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/tests", label: "Tests" },
  { href: "/runs", label: "Runs" },
  { href: "/reports", label: "Reports" },
];

function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
      <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-[13px] font-bold text-primary-foreground">LL</span>
      <span className="hidden text-[15px] sm:inline">LorvenLax <span className="font-normal text-muted-foreground">AI Testing</span></span>
    </Link>
  );
}

function ProjectSwitcher() {
  const { projects, project, setProjectId, me, orgId, setOrgId } = useWorkspace();
  const [creating, setCreating] = React.useState(false);
  return (
    <>
      <Dropdown.Root>
        <Dropdown.Trigger asChild>
          <button className="flex max-w-[220px] items-center gap-1.5 rounded-md px-2 py-1.5 text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" data-testid="project-switcher">
            <FolderKanban className="h-4 w-4 text-muted-foreground" />
            <span className="truncate font-medium">{project ? project.name : "No project"}</span>
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
          </button>
        </Dropdown.Trigger>
        <Dropdown.Portal>
          <Dropdown.Content align="start" sideOffset={6} className="z-50 min-w-[240px] rounded-md border bg-card p-1 shadow-lg">
            {me.organizations.length > 1 && (
              <>
                <Dropdown.Label className="px-2 py-1 text-xs text-muted-foreground">Organization</Dropdown.Label>
                {me.organizations.map((o) => (
                  <Dropdown.Item key={o.id} onSelect={() => setOrgId(o.id)} className={cn("cursor-pointer rounded px-2 py-1.5 text-sm outline-none data-[highlighted]:bg-muted", o.id === orgId && "font-medium")}>
                    {o.name}
                  </Dropdown.Item>
                ))}
                <Dropdown.Separator className="my-1 h-px bg-border" />
              </>
            )}
            <Dropdown.Label className="px-2 py-1 text-xs text-muted-foreground">Projects</Dropdown.Label>
            {projects.map((p) => (
              <Dropdown.Item key={p.id} onSelect={() => setProjectId(p.id)} className={cn("cursor-pointer rounded px-2 py-1.5 text-sm outline-none data-[highlighted]:bg-muted", p.id === project?.id && "font-medium text-primary")}>
                {p.name}
              </Dropdown.Item>
            ))}
            <Dropdown.Separator className="my-1 h-px bg-border" />
            <Dropdown.Item onSelect={() => setCreating(true)} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm outline-none data-[highlighted]:bg-muted">
              <Plus className="h-4 w-4" /> New project
            </Dropdown.Item>
          </Dropdown.Content>
        </Dropdown.Portal>
      </Dropdown.Root>
      <NewProjectDialog open={creating} onOpenChange={setCreating} />
    </>
  );
}

function UserMenu() {
  const { me } = useWorkspace();
  return (
    <Dropdown.Root>
      <Dropdown.Trigger asChild>
        <button aria-label="Account menu" className="flex h-8 w-8 items-center justify-center rounded-full bg-secondary text-xs font-semibold uppercase hover:ring-2 hover:ring-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {me.name.slice(0, 2)}
        </button>
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content align="end" sideOffset={6} className="z-50 min-w-[220px] rounded-md border bg-card p-1 shadow-lg">
          <div className="px-2 py-1.5">
            <p className="text-sm font-medium">{me.name}</p>
            <p className="text-xs text-muted-foreground">{me.email}</p>
          </div>
          <Dropdown.Separator className="my-1 h-px bg-border" />
          <Dropdown.Item asChild className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm outline-none data-[highlighted]:bg-muted">
            <Link href="/settings"><Settings className="h-4 w-4" /> Settings</Link>
          </Dropdown.Item>
          <Dropdown.Item onSelect={() => logout()} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm outline-none data-[highlighted]:bg-muted">
            <LogOut className="h-4 w-4" /> Sign out
          </Dropdown.Item>
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { project, canWrite } = useWorkspace();
  const [createOpen, setCreateOpen] = React.useState(false);
  const active = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b bg-card/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-4 sm:px-6">
          <Logo />
          <span className="text-border">/</span>
          <ProjectSwitcher />
          <nav className="ml-2 hidden items-center gap-0.5 md:flex" aria-label="Main">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href}
                className={cn("rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground", active(n.href) && "bg-muted text-foreground")}>
                {n.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="ghost" size="sm" asChild className="hidden sm:inline-flex">
              <Link href="/assistant"><Bot /> Assistant</Link>
            </Button>
            {canWrite && project && (
              <Button size="sm" onClick={() => setCreateOpen(true)} data-testid="create-test">
                <Plus /> Create Test
              </Button>
            )}
            <UserMenu />
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto border-t px-4 py-1.5 md:hidden" aria-label="Main mobile">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} className={cn("rounded-md px-3 py-1 text-sm text-muted-foreground", active(n.href) && "bg-muted text-foreground")}>{n.label}</Link>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6">{children}</main>
      <CreateTestDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}
