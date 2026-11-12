"use client";

import { useParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { TimezoneOptions } from "@/components/timezones";
import { Alert, Button, Card, CopyButton, Field, Input, Loading, PageHeader, Select, StatusBadge } from "@/components/ui";
import { api, type Site } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { can } from "@/lib/perms";
import { useResource } from "@/lib/resource";

function SiteForm({ site, org, onSaved }: { site: Site; org: string; onSaved: () => Promise<void> }) {
  const editable = can(site, "sites.manage");
  const [form, setForm] = useState({
    name: site.name,
    slug: site.slug,
    timezone: site.timezone,
    default_locale: site.default_locale,
  });
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string }>();
  useEffect(() => {
    setForm({ name: site.name, slug: site.slug, timezone: site.timezone, default_locale: site.default_locale });
  }, [site]);

  const path = { params: { path: { org, site_id: site.id } } };

  async function save(event: FormEvent) {
    event.preventDefault();
    const { error } = await api.PATCH("/api/manage/orgs/{org}/sites/{site_id}/", { ...path, body: form });
    setMessage(error ? { kind: "error", text: errorMessage(error) } : { kind: "success", text: "Saved." });
    if (!error) await onSaved();
  }

  async function archive() {
    if (!window.confirm(`Archive ${site.name}? Its API tokens stop working.`)) return;
    const { error } = await api.DELETE("/api/manage/orgs/{org}/sites/{site_id}/", path);
    if (error) setMessage({ kind: "error", text: errorMessage(error) });
    else await onSaved();
  }

  return (
    <Card title="Site settings" actions={<StatusBadge value={site.status} />}>
      <form className="grid gap-4 sm:grid-cols-2" onSubmit={save}>
        <Field label="Name"><Input required disabled={!editable} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="Slug"><Input required pattern="[a-z0-9-]+" disabled={!editable} value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} /></Field>
        <Field label="Time zone"><Input list="timezones" required disabled={!editable} value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} /></Field>
        <Field label="Default locale"><Input required disabled={!editable} value={form.default_locale} onChange={(e) => setForm({ ...form, default_locale: e.target.value })} /></Field>
        <TimezoneOptions id="timezones" />
        <div className="sm:col-span-2 space-y-3">
          {message ? <Alert kind={message.kind}>{message.text}</Alert> : null}
          {editable ? (
            <div className="flex gap-2">
              <Button type="submit">Save</Button>
              {site.status === "active" ? <Button type="button" variant="danger" onClick={archive}>Archive site</Button> : null}
            </div>
          ) : (
            <p className="text-sm text-zinc-500">You can view this site but not change its settings.</p>
          )}
        </div>
      </form>
    </Card>
  );
}

function ApiTokens({ site, org }: { site: Site; org: string }) {
  const path = { params: { path: { org, site_id: site.id } } };
  const tokens = useResource(() => api.GET("/api/manage/orgs/{org}/sites/{site_id}/tokens/", path), [org, site.id]);
  const [form, setForm] = useState<{ name: string; kind: "delivery" | "preview" }>({ name: "", kind: "delivery" });
  const [created, setCreated] = useState<{ name: string; token: string }>();
  const [error, setError] = useState<string>();

  async function create(event: FormEvent) {
    event.preventDefault();
    setError(undefined);
    const { data, error: createError } = await api.POST("/api/manage/orgs/{org}/sites/{site_id}/tokens/", { ...path, body: form });
    if (createError || !data) return setError(errorMessage(createError));
    setCreated({ name: data.name, token: data.token }); // held in memory only, never stored
    setForm({ name: "", kind: "delivery" });
    await tokens.reload();
  }

  async function revoke(id: string, name: string) {
    if (!window.confirm(`Revoke "${name}"? Sites using it stop working immediately.`)) return;
    const { error: revokeError } = await api.DELETE("/api/manage/orgs/{org}/sites/{site_id}/tokens/{token_id}/", {
      params: { path: { org, site_id: site.id, token_id: id } },
    });
    if (revokeError) setError(errorMessage(revokeError));
    await tokens.reload();
  }

  return (
    <Card title="API tokens">
      <div className="space-y-4">
        {created ? (
          <Alert kind="success">
            <p className="mb-2 font-medium">Copy the token for “{created.name}” now. It will not be shown again.</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 break-all rounded bg-white px-2 py-1 text-xs">{created.token}</code>
              <CopyButton value={created.token} />
              <Button variant="secondary" onClick={() => setCreated(undefined)}>Done</Button>
            </div>
          </Alert>
        ) : null}
        {error ? <Alert>{error}</Alert> : null}
        {tokens.loading && !tokens.data ? <Loading /> : (
          <table className="w-full text-sm">
            <thead className="text-left text-zinc-500">
              <tr><th className="py-1">Name</th><th>Kind</th><th>Prefix</th><th>Last used</th><th /></tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {tokens.data?.map((token) => (
                <tr key={token.id}>
                  <td className="py-2">{token.name}</td>
                  <td>{token.kind}</td>
                  <td><code>{token.prefix}</code></td>
                  <td>{token.last_used_at ? new Date(token.last_used_at).toLocaleString() : "Never"}</td>
                  <td className="text-right">
                    {token.revoked_at ? <StatusBadge value="revoked" /> : <Button variant="danger" onClick={() => revoke(token.id, token.name)}>Revoke</Button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <form className="flex flex-wrap items-end gap-3" onSubmit={create}>
          <Field label="Name"><Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Kind">
            <Select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as "delivery" | "preview" })}>
              <option value="delivery">Delivery (published content)</option>
              <option value="preview">Preview (includes drafts)</option>
            </Select>
          </Field>
          <Button type="submit">Create token</Button>
        </form>
      </div>
    </Card>
  );
}

export default function SitePage() {
  const { org, siteId } = useParams<{ org: string; siteId: string }>();
  const site = useResource(
    () => api.GET("/api/manage/orgs/{org}/sites/{site_id}/", { params: { path: { org, site_id: siteId } } }),
    [org, siteId],
  );

  if (site.loading && !site.data) return <Loading />;
  if (!site.data) return <Alert>{errorMessage(site.error, "Site not found.")}</Alert>;
  return (
    <div className="space-y-6">
      <PageHeader title={site.data.name} subtitle={`Your access: ${site.data.permissions.length} permissions on this site`} />
      <SiteForm site={site.data} org={org} onSaved={site.reload} />
      {can(site.data, "api_tokens.manage") ? <ApiTokens site={site.data} org={org} /> : null}
    </div>
  );
}
