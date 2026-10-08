"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { Alert, Button, Card, CardContent, Field, Input } from "@/components/ui";
import { api } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = React.useState({ name: "", email: "", password: "", organization_name: "" });
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/register", { json: form });
      router.replace("/");
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardContent className="pt-6">
        <h1 className="mb-1 text-lg font-semibold">Create your account</h1>
        <p className="mb-5 text-sm text-muted-foreground">Start testing your website or API in a few minutes.</p>
        <form onSubmit={submit} className="grid gap-4">
          <Field label="Your name" htmlFor="name"><Input id="name" required value={form.name} onChange={set("name")} autoComplete="name" /></Field>
          <Field label="Work email" htmlFor="email"><Input id="email" type="email" required value={form.email} onChange={set("email")} autoComplete="email" /></Field>
          <Field label="Password" htmlFor="password" hint="At least 10 characters, with letters and numbers.">
            <Input id="password" type="password" required minLength={10} value={form.password} onChange={set("password")} autoComplete="new-password" />
          </Field>
          <Field label="Company or team name" htmlFor="org"><Input id="org" required value={form.organization_name} onChange={set("organization_name")} /></Field>
          {error && <Alert variant="error">{error}</Alert>}
          <Button type="submit" loading={busy} className="w-full">Create account</Button>
        </form>
        <p className="mt-5 text-center text-sm text-muted-foreground">
          Already have an account? <Link href="/login" className="font-medium text-primary hover:underline">Sign in</Link>
        </p>
      </CardContent>
    </Card>
  );
}
