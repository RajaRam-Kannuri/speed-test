"use client";

import { Check, Circle } from "lucide-react";
import * as React from "react";
import { Field, PasswordInput } from "@/components/ui";
import { cn } from "@/lib/utils";

// Mirrors the server rule (backend/app/security/passwords.py: password_problem).
export function passwordChecks(password: string, confirm: string) {
  return [
    { label: "At least 10 characters", ok: password.length >= 10 },
    { label: "Contains a letter", ok: /[A-Za-z]/.test(password) },
    { label: "Contains a number", ok: /\d/.test(password) },
    { label: "Both passwords match", ok: password.length > 0 && password === confirm },
  ];
}

export function NewPasswordFields({ password, confirm, onPassword, onConfirm, autoFocus }: {
  password: string; confirm: string; onPassword: (v: string) => void; onConfirm: (v: string) => void; autoFocus?: boolean;
}) {
  const checks = passwordChecks(password, confirm);
  return (
    <>
      <Field label="New password" htmlFor="new-password">
        <PasswordInput id="new-password" autoComplete="new-password" required autoFocus={autoFocus} value={password} onChange={(e) => onPassword(e.target.value)} />
      </Field>
      <Field label="Confirm new password" htmlFor="confirm-password">
        <PasswordInput id="confirm-password" autoComplete="new-password" required value={confirm} onChange={(e) => onConfirm(e.target.value)} />
      </Field>
      <ul className="grid gap-1 text-xs" aria-label="Password requirements">
        {checks.map((c) => (
          <li key={c.label} className={cn("flex items-center gap-1.5", c.ok ? "text-[#0f5f0f]" : "text-muted-foreground")}>
            {c.ok ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Circle className="h-3 w-3" aria-hidden />}
            <span>{c.label}</span><span className="sr-only">{c.ok ? "(met)" : "(not met)"}</span>
          </li>
        ))}
      </ul>
    </>
  );
}
