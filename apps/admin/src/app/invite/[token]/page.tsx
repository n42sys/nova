"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Alert, Button, Card, Field, Input, Loading } from "@/components/ui";
import { allauth } from "@/lib/allauth";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { ROLE_LABELS } from "@/lib/perms";
import { useResource } from "@/lib/resource";

export default function InvitePage() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const preview = useResource(
    () => api.GET("/api/manage/invitations/{token}/", { params: { path: { token } } }),
    [token],
  );
  const [loggedIn, setLoggedIn] = useState<boolean>();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void allauth.session().then((result) => setLoggedIn(result.ok));
  }, []);

  async function accept() {
    const { data, error: acceptError } = await api.POST("/api/manage/invitations/{token}/accept/", {
      params: { path: { token } },
    });
    if (data) router.replace(`/orgs/${data.slug}`);
    else setError(errorMessage(acceptError));
  }

  async function onAccept() {
    setBusy(true);
    setError(undefined);
    await accept();
    setBusy(false);
  }

  async function onSignup(event: FormEvent) {
    event.preventDefault();
    if (!preview.data) return;
    setBusy(true);
    setError(undefined);
    // Claiming records the invitation in this session, which opens sign-up for its email.
    const claim = await api.POST("/api/manage/invitations/{token}/claim/", { params: { path: { token } } });
    if (!claim.response.ok) {
      // The schema documents only 204, so `error` is typed `never`, but openapi-fetch still
      // parses the error body into it at runtime.
      setError(errorMessage((claim as { error?: unknown }).error));
      return setBusy(false);
    }
    const signup = await allauth.signup(preview.data.email, password);
    if (!signup.ok) {
      setError(signup.message ?? "Could not create your account.");
      return setBusy(false);
    }
    await accept();
    setBusy(false);
  }

  async function onLogout() {
    await allauth.logout();
    setLoggedIn(false);
  }

  if (preview.loading || loggedIn === undefined) return <main className="mx-auto max-w-md p-8"><Loading /></main>;
  if (preview.error || !preview.data) {
    return (
      <main className="mx-auto max-w-md p-8">
        <Alert>{errorMessage(preview.error, "This invitation link is not valid.")}</Alert>
      </main>
    );
  }

  const invitation = preview.data;
  const roles = [
    invitation.org_role ? `${ROLE_LABELS[invitation.org_role]} across the organization` : null,
    ...invitation.site_roles.map((item) => `${ROLE_LABELS[item.role]} on ${item.site_name}`),
  ].filter(Boolean);

  return (
    <main className="mx-auto max-w-md p-8">
      <Card title={`Join ${invitation.organization.name}`}>
        <div className="space-y-4 text-sm">
          <p>
            {invitation.invited_by_name ? `${invitation.invited_by_name} invited ` : "You were invited as "}
            <strong>{invitation.email}</strong>.
          </p>
          <ul className="list-disc pl-5">
            {roles.map((role) => <li key={role}>{role}</li>)}
          </ul>
          {error ? <Alert>{error}</Alert> : null}
          {loggedIn ? (
            <div className="flex gap-2">
              <Button disabled={busy} onClick={onAccept}>Accept invitation</Button>
              <Button variant="secondary" onClick={onLogout}>Use another account</Button>
            </div>
          ) : invitation.account_exists ? (
            <p>
              <Link className="font-medium underline" href={`/login?next=${encodeURIComponent(`/invite/${token}`)}`}>
                Sign in as {invitation.email}
              </Link>{" "}
              to accept.
            </p>
          ) : (
            <form className="space-y-4" onSubmit={onSignup}>
              <Field label="Email"><Input value={invitation.email} disabled /></Field>
              <Field label="Choose a password" hint="At least 8 characters.">
                <Input type="password" autoComplete="new-password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
              </Field>
              <Button type="submit" disabled={busy}>Create account and join</Button>
            </form>
          )}
        </div>
      </Card>
    </main>
  );
}
