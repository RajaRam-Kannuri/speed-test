"use client";

import { Bot, Globe, Plug } from "lucide-react";
import Link from "next/link";
import { Dialog, DialogContent } from "@/components/ui";

const OPTIONS = [
  { href: "/create/website", icon: Globe, title: "Test a Website", body: "Enter a URL. We explore the site, suggest tests, and run them in a cloud browser." },
  { href: "/create/api", icon: Plug, title: "Test an API", body: "Upload an OpenAPI or Postman file, or enter an endpoint. We generate and run API checks." },
  { href: "/assistant", icon: Bot, title: "Describe a Test", body: "Write what you want to test in plain English. The assistant builds the steps for you." },
];

export function CreateOptions({ onPick }: { onPick?: () => void }) {
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {OPTIONS.map(({ href, icon: Icon, title, body }) => (
        <Link key={href} href={href} onClick={onPick}
          className="group rounded-lg border bg-card p-4 text-left transition hover:border-primary/50 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <span className="mb-3 inline-flex h-9 w-9 items-center justify-center rounded-md bg-accent text-accent-foreground">
            <Icon className="h-[18px] w-[18px]" />
          </span>
          <p className="text-sm font-semibold group-hover:text-primary">{title}</p>
          <p className="mt-1 text-[13px] leading-5 text-muted-foreground">{body}</p>
        </Link>
      ))}
    </div>
  );
}

export function CreateTestDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Create a test" description="Choose how you want to start. You can review everything before it runs." className="max-w-3xl">
        <CreateOptions onPick={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}
