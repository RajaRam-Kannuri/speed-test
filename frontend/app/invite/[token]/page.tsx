"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import * as React from "react";
import { Alert, Button, Card, CardContent } from "@/components/ui";
import { ApiError, api } from "@/lib/api";

export default function InvitePage() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const [error, setError] = React.useState<string | null>(null);
  const [needLogin, setNeedLogin] = React.useState(false);
  const [busy, setBusy] = React.useState(false);

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ organization_id: string }>(`/invitations/${token}/accept`, { method: "POST" });
      try { localStorage.setItem("llx.org", res.organization_id); } catch { /* ignore */ }
      router.replace("/");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setNeedLogin(true);
      else setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <CardContent className="grid gap-4 pt-6">
          <h1 className="text-lg font-semibold">Join an organization</h1>
          <p className="text-sm text-muted-foreground">You were invited to collaborate on LorvenLax. Accept to get access to the organization&apos;s projects.</p>
          {needLogin && (
            <Alert variant="warning" title="Sign in first">
              Sign in or <Link className="underline" href="/register">create an account</Link> with the invited email, then open this link again.
              <div className="mt-2"><Link className="font-medium underline" href={`/login?next=/invite/${token}`}>Sign in</Link></div>
            </Alert>
          )}
          {error && <Alert variant="error">{error}</Alert>}
          <Button onClick={accept} loading={busy}>Accept invitation</Button>
        </CardContent>
      </Card>
    </div>
  );
}
