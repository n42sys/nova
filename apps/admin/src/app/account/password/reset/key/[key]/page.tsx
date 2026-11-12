"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Alert, Button, Card, Field, Input, Loading } from "@/components/ui";
import { allauth } from "@/lib/allauth";

/** Target of HEADLESS_FRONTEND_URLS["account_reset_password_from_key"]. */
export default function ResetPasswordPage() {
  const { key } = useParams<{ key: string }>();
  const [keyState, setKeyState] = useState<"checking" | "valid" | "invalid">("checking");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void allauth
      .checkPasswordResetKey(key)
      .then((result) => setKeyState(result.ok ? "valid" : "invalid"))
      .catch(() => setKeyState("invalid"));
  }, [key]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password !== confirm) return setErrors(["The two passwords do not match."]);
    setBusy(true);
    setErrors([]);
    try {
      const result = await allauth.resetPassword(key, password);
      // 200: changed and signed in; 401: changed, sign in next. Anything else failed.
      if (result.status === 200 || result.status === 401) setDone(true);
      else setErrors(result.messages.length ? result.messages : ["Could not reset your password."]);
    } catch {
      setErrors(["Could not reach the server."]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-sm p-8">
      <Card title="Choose a new password">
        {keyState === "checking" ? (
          <Loading />
        ) : done ? (
          <Alert kind="success">
            Your password has been changed. <Link className="underline" href="/login">Sign in</Link>.
          </Alert>
        ) : keyState === "invalid" ? (
          <div className="space-y-4">
            <Alert>This reset link is invalid or has already been used.</Alert>
            <Link className="text-sm underline" href="/account/password/reset">Request a new link</Link>
          </div>
        ) : (
          <form className="space-y-4" onSubmit={submit}>
            {errors.length ? (
              <Alert>
                <ul className="list-disc pl-4">{errors.map((message) => <li key={message}>{message}</li>)}</ul>
              </Alert>
            ) : null}
            <Field label="New password" hint="At least 8 characters, not a common password.">
              <Input type="password" autoComplete="new-password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
            <Field label="Confirm new password">
              <Input type="password" autoComplete="new-password" required minLength={8} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            </Field>
            <Button type="submit" disabled={busy}>Change password</Button>
          </form>
        )}
      </Card>
    </main>
  );
}
