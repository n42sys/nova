"use client";

import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert, Button, Card, Field, Input, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { api, type PaymentAccount } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { can } from "@/lib/perms";
import { useResource } from "@/lib/resource";
import { useOrg } from "@/lib/session";

/** Keys go straight from this form to the API; the secret is never shown again (only a hint). */
function KeysForm({ submitLabel, onSubmit }: { submitLabel: string; onSubmit: (keys: { public_key: string; secret_key: string }) => Promise<boolean> }) {
  const [keys, setKeys] = useState({ public_key: "", secret_key: "" });

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (await onSubmit(keys)) setKeys({ public_key: "", secret_key: "" });
  }

  return (
    <form className="grid gap-4 sm:grid-cols-2" onSubmit={submit} autoComplete="off">
      <Field label="Public key"><Input required placeholder="pk_live_…" value={keys.public_key} onChange={(e) => setKeys({ ...keys, public_key: e.target.value })} /></Field>
      <Field label="Secret key" hint="Stored encrypted. It is never shown again.">
        <Input required type="password" autoComplete="new-password" placeholder="sk_live_…" value={keys.secret_key} onChange={(e) => setKeys({ ...keys, secret_key: e.target.value })} />
      </Field>
      <div className="sm:col-span-2"><Button type="submit">{submitLabel}</Button></div>
    </form>
  );
}

function AccountCard({ account, slug, onDone }: { account: PaymentAccount; slug: string; onDone: (error?: unknown, success?: string) => Promise<void> }) {
  const [replacing, setReplacing] = useState(false);
  const params = { params: { path: { org: slug, account_id: account.id } } };

  return (
    <Card title={account.provider === "paystack" ? "Paystack" : account.provider} actions={<StatusBadge value={account.status} />}>
      <dl className="mb-4 grid grid-cols-2 gap-2 text-sm">
        <dt className="text-zinc-500">Public key</dt><dd><code>{account.public_key}</code></dd>
        <dt className="text-zinc-500">Secret key</dt><dd><code>{account.secret_key_hint}</code></dd>
        <dt className="text-zinc-500">Verified</dt><dd>{account.verified_at ? new Date(account.verified_at).toLocaleString() : "Not yet"}</dd>
      </dl>
      <div className="flex flex-wrap gap-2">
        {account.status !== "disabled" ? (
          <Button onClick={async () => {
            const { error } = await api.POST("/api/manage/orgs/{org}/payment-accounts/{account_id}/verify/", params);
            await onDone(error, "Keys verified with Paystack.");
          }}>Verify keys</Button>
        ) : null}
        <Button variant="secondary" onClick={() => setReplacing(!replacing)}>{replacing ? "Cancel" : "Replace keys"}</Button>
        {account.status !== "disabled" ? (
          <Button variant="danger" onClick={async () => {
            if (!window.confirm("Disable this payment account?")) return;
            const { error } = await api.DELETE("/api/manage/orgs/{org}/payment-accounts/{account_id}/", params);
            await onDone(error, "Payment account disabled.");
          }}>Disable</Button>
        ) : null}
      </div>
      {replacing ? (
        <div className="mt-4 border-t border-zinc-100 pt-4">
          <KeysForm submitLabel="Save new keys" onSubmit={async (keys) => {
            const { error } = await api.PATCH("/api/manage/orgs/{org}/payment-accounts/{account_id}/", { ...params, body: keys });
            await onDone(error, "Keys replaced. Verify them to start using the account.");
            if (!error) setReplacing(false);
            return !error;
          }} />
        </div>
      ) : null}
    </Card>
  );
}

export default function PaymentsPage() {
  const { org: slug } = useParams<{ org: string }>();
  const org = useOrg(slug);
  const path = { params: { path: { org: slug } } };
  const accounts = useResource(() => api.GET("/api/manage/orgs/{org}/payment-accounts/", path), [slug]);
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string }>();

  async function onDone(error?: unknown, success?: string) {
    setMessage(error ? { kind: "error", text: errorMessage(error) } : success ? { kind: "success", text: success } : undefined);
    await accounts.reload();
  }

  if (!org) return <Loading />;
  if (!can(org, "payments.manage")) return <Alert>Only owners can manage payment accounts.</Alert>;
  if (accounts.loading && !accounts.data) return <Loading />;
  const hasPaystack = accounts.data?.some((account) => account.provider === "paystack");
  return (
    <div className="space-y-6">
      <PageHeader title="Payments" subtitle="Payments go straight to your own Paystack account." />
      {message ? <Alert kind={message.kind}>{message.text}</Alert> : null}
      {accounts.data?.map((account) => <AccountCard key={account.id} account={account} slug={slug} onDone={onDone} />)}
      {!hasPaystack ? (
        <Card title="Connect Paystack">
          <KeysForm submitLabel="Save keys" onSubmit={async (keys) => {
            const { error } = await api.POST("/api/manage/orgs/{org}/payment-accounts/", { ...path, body: { provider: "paystack", ...keys } });
            await onDone(error, "Paystack keys saved. Verify them next.");
            return !error;
          }} />
        </Card>
      ) : null}
    </div>
  );
}
