"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import { Alert, Button, Card, Field, Input } from "@/components/ui";
import { allauth, type AuthResult } from "@/lib/allauth";
import { safeNext } from "@/lib/redirect";

function failure(result: AuthResult): string {
  if (result.pending.includes("verify_email")) return "Verify your email address first (check your inbox).";
  return result.message ?? "Those details did not work.";
}

function LoginForm() {
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const [mode, setMode] = useState<"password" | "code">("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [codeSent, setCodeSent] = useState(false);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<AuthResult>, onPending?: (result: AuthResult) => boolean) {
    setBusy(true);
    setError(undefined);
    try {
      const result = await action();
      if (result.ok) return router.replace(next);
      if (onPending?.(result)) return;
      setError(failure(result));
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  function submitPassword(event: FormEvent) {
    event.preventDefault();
    void run(() => allauth.login(email, password));
  }

  function submitCodeRequest(event: FormEvent) {
    event.preventDefault();
    void run(
      () => allauth.requestCode(email),
      (result) => {
        if (result.pending.includes("login_by_code")) {
          setCodeSent(true);
          return true;
        }
        return false;
      },
    );
  }

  function submitCode(event: FormEvent) {
    event.preventDefault();
    void run(() => allauth.confirmCode(code.trim()));
  }

  return (
    <Card title="Sign in">
      <div className="mb-4 flex gap-2 text-sm">
        <Button variant={mode === "password" ? "primary" : "secondary"} type="button" onClick={() => setMode("password")}>
          Password
        </Button>
        <Button variant={mode === "code" ? "primary" : "secondary"} type="button" onClick={() => setMode("code")}>
          Email me a code
        </Button>
      </div>
      {error ? <div className="mb-4"><Alert>{error}</Alert></div> : null}
      {mode === "password" ? (
        <form className="space-y-4" onSubmit={submitPassword}>
          <Field label="Email">
            <Input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="Password">
            <Input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          <div className="flex items-center justify-between">
            <Button type="submit" disabled={busy}>Sign in</Button>
            <Link className="text-sm text-zinc-600 underline" href="/account/password/reset">
              Forgot password?
            </Link>
          </div>
        </form>
      ) : codeSent ? (
        <form className="space-y-4" onSubmit={submitCode}>
          <Alert kind="info">We sent a sign-in code to {email}.</Alert>
          <Field label="Code">
            <Input autoComplete="one-time-code" required value={code} onChange={(e) => setCode(e.target.value)} />
          </Field>
          <Button type="submit" disabled={busy}>Sign in</Button>
        </form>
      ) : (
        <form className="space-y-4" onSubmit={submitCodeRequest}>
          <Field label="Email">
            <Input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Button type="submit" disabled={busy}>Send code</Button>
        </form>
      )}
    </Card>
  );
}

export default function LoginPage() {
  return (
    <main className="mx-auto max-w-sm p-8">
      <Suspense>
        <LoginForm />
      </Suspense>
    </main>
  );
}
