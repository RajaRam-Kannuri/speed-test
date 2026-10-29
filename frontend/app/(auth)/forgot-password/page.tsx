"use client";

import { ArrowLeft, MailCheck, ShieldQuestion } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { Alert, Button, Card, CardContent, Field, Input, Spinner } from "@/components/ui";
import { api } from "@/lib/api";

function BackToSignIn() {
  return (
    <Link href="/login" className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline">
      <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Back to sign in
    </Link>
  );
}

export default function ForgotPasswordPage() {
  const [emailEnabled, setEmailEnabled] = React.useState<boolean | null>(null);
  const [email, setEmail] = React.useState("");
  const [sentTo, setSentTo] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    api<{ email_enabled: boolean }>("/auth/password-reset/options")
      .then((r) => setEmailEnabled(r.email_enabled))
      .catch(() => setEmailEnabled(false));
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/password-reset/request", { json: { email } });
      setSentTo(email);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (emailEnabled === null) {
    return <Card><CardContent className="flex justify-center py-12"><Spinner /></CardContent></Card>;
  }

  if (!emailEnabled) {
    return (
      <Card>
        <CardContent className="pt-6">
          <span className="mb-4 flex h-10 w-10 items-center justify-center rounded-full bg-accent text-primary"><ShieldQuestion className="h-5 w-5" aria-hidden /></span>
          <h1 className="mb-1 text-lg font-semibold">Forgot your password?</h1>
          <p className="mb-4 text-sm text-muted-foreground">
            Ask an owner or admin of your workspace to send you a reset link. They can do this from <strong className="font-medium text-foreground">Settings → Team</strong>.
          </p>
          <p className="mb-6 text-sm text-muted-foreground">The link lets you choose a new password and works once.</p>
          <BackToSignIn />
        </CardContent>
      </Card>
    );
  }

  if (sentTo) {
    return (
      <Card>
        <CardContent className="pt-6">
          <span className="mb-4 flex h-10 w-10 items-center justify-center rounded-full bg-accent text-primary"><MailCheck className="h-5 w-5" aria-hidden /></span>
          <h1 className="mb-1 text-lg font-semibold">Check your email</h1>
          <p className="mb-4 text-sm text-muted-foreground">
            If an account exists for <strong className="font-medium text-foreground">{sentTo}</strong>, we have sent a link to reset its password. The link expires in 60 minutes.
          </p>
          <p className="mb-6 text-sm text-muted-foreground">
            Didn&apos;t get it? Check your spam folder, or{" "}
            <button type="button" className="font-medium text-primary hover:underline" onClick={() => setSentTo(null)}>try a different email</button>.
          </p>
          <BackToSignIn />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="pt-6">
        <h1 className="mb-1 text-lg font-semibold">Forgot your password?</h1>
        <p className="mb-5 text-sm text-muted-foreground">Enter the email you sign in with and we&apos;ll send you a link to reset your password.</p>
        <form onSubmit={submit} className="grid gap-4">
          <Field label="Email" htmlFor="email">
            <Input id="email" type="email" autoComplete="username" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          {error && <Alert variant="error">{error}</Alert>}
          <Button type="submit" loading={busy} className="w-full">Send reset link</Button>
        </form>
        <div className="mt-5 text-center"><BackToSignIn /></div>
      </CardContent>
    </Card>
  );
}
