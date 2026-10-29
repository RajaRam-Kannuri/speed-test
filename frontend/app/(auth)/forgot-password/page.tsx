"use client";

import Link from "next/link";
import * as React from "react";
import { Card, CardContent } from "@/components/ui";

const COMMAND = "docker compose exec api python -m app.manage reset-password you@example.com";

export default function ForgotPasswordPage() {
  const [copied, setCopied] = React.useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(COMMAND);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <Card>
      <CardContent className="pt-6">
        <h1 className="mb-1 text-lg font-semibold">Reset your password</h1>
        <p className="mb-4 text-sm text-muted-foreground">
          This installation does not send email, so passwords are reset by whoever runs the server. Ask your
          administrator, or if that is you, run this in the folder that holds <code>docker-compose.yml</code>:
        </p>
        <div className="relative mb-3 rounded-md border bg-muted px-3 py-2.5 pr-16 font-mono text-xs leading-5 break-words">
          {COMMAND}
          <button type="button" onClick={copy} className="absolute right-2 top-2 rounded px-1.5 py-0.5 text-xs font-medium text-primary hover:underline">
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
        <ul className="mb-5 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
          <li>Replace the email with the one you sign in with.</li>
          <li>You will be asked to type the new password twice. Add <code>--generate</code> to get a random one instead.</li>
          <li>Every device signed in to the account is signed out.</li>
        </ul>
        <p className="text-center text-sm text-muted-foreground">
          <Link href="/login" className="font-medium text-primary hover:underline">Back to sign in</Link>
        </p>
      </CardContent>
    </Card>
  );
}
