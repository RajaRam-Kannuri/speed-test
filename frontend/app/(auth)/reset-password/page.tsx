"use client";

import { ArrowLeft, LinkIcon } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { NewPasswordFields, passwordChecks } from "@/components/new-password";
import { Alert, Button, Card, CardContent, Spinner } from "@/components/ui";
import { api } from "@/lib/api";

function ResetForm() {
  const router = useRouter();
  const token = useSearchParams().get("token") || "";
  const [account, setAccount] = React.useState<{ email: string; name: string } | null | undefined>(undefined);
  const [password, setPassword] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (!token) { setAccount(null); return; }
    api<{ email: string; name: string }>("/auth/password-reset/check", { json: { token } })
      .then(setAccount)
      .catch(() => setAccount(null));
  }, [token]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!passwordChecks(password, confirm).every((c) => c.ok)) {
      setError(password !== confirm ? "The passwords do not match." : "Use at least 10 characters, including letters and numbers.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api("/auth/password-reset/confirm", { json: { token, password } });
      router.replace("/login?reset=1");
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  if (account === undefined) {
    return <Card><CardContent className="flex justify-center py-12"><Spinner /></CardContent></Card>;
  }

  if (account === null) {
    return (
      <Card>
        <CardContent className="pt-6">
          <span className="mb-4 flex h-10 w-10 items-center justify-center rounded-full bg-[#fdf2f2] text-[#8f2424]"><LinkIcon className="h-5 w-5" aria-hidden /></span>
          <h1 className="mb-1 text-lg font-semibold">This link has expired</h1>
          <p className="mb-6 text-sm text-muted-foreground">
            Reset links work once and only for a limited time. Request a new link and use the most recent email you receive.
          </p>
          <Button asChild className="w-full"><Link href="/forgot-password">Request a new link</Link></Button>
          <div className="mt-5 text-center">
            <Link href="/login" className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"><ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Back to sign in</Link>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="pt-6">
        <h1 className="mb-1 text-lg font-semibold">Choose a new password</h1>
        <p className="mb-5 text-sm text-muted-foreground">
          For <strong className="font-medium text-foreground">{account.email}</strong>. You&apos;ll be signed out on other devices.
        </p>
        <form onSubmit={submit} className="grid gap-4">
          <NewPasswordFields password={password} confirm={confirm} onPassword={setPassword} onConfirm={setConfirm} autoFocus />
          {error && <Alert variant="error">{error}</Alert>}
          <Button type="submit" loading={busy} className="w-full">Update password</Button>
        </form>
      </CardContent>
    </Card>
  );
}

export default function ResetPasswordPage() {
  return (
    <React.Suspense>
      <ResetForm />
    </React.Suspense>
  );
}
