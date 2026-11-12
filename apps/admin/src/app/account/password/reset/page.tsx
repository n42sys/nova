"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Alert, Button, Card, Field, Input } from "@/components/ui";
import { allauth } from "@/lib/allauth";

/** Target of HEADLESS_FRONTEND_URLS["account_reset_password"]. */
export default function RequestPasswordResetPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const result = await allauth.requestPasswordReset(email);
      if (result.ok) setSent(true);
      else setError(result.status === 429 ? "Too many attempts. Try again later." : result.message ?? "Could not send the email.");
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-sm p-8">
      <Card title="Reset your password">
        {sent ? (
          <div className="space-y-4">
            {/* Same message whether or not the address has an account. */}
            <Alert kind="success">
              If {email} has an account, we have sent it a link to choose a new password.
            </Alert>
            <Link className="text-sm underline" href="/login">Back to sign in</Link>
          </div>
        ) : (
          <form className="space-y-4" onSubmit={submit}>
            {error ? <Alert>{error}</Alert> : null}
            <Field label="Email">
              <Input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <div className="flex items-center justify-between">
              <Button type="submit" disabled={busy}>Send reset link</Button>
              <Link className="text-sm text-zinc-600 underline" href="/login">Back to sign in</Link>
            </div>
          </form>
        )}
      </Card>
    </main>
  );
}
