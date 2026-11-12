"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { TimezoneOptions } from "@/components/timezones";
import { Alert, Button, Card, Field, Input, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { can } from "@/lib/perms";
import { useResource } from "@/lib/resource";
import { useOrg } from "@/lib/session";

export default function SitesPage() {
  const { org: slug } = useParams<{ org: string }>();
  const org = useOrg(slug);
  const sites = useResource(
    () => api.GET("/api/manage/orgs/{org}/sites/", { params: { path: { org: slug } } }),
    [slug],
  );
  const [form, setForm] = useState({ name: "", slug: "", timezone: "Africa/Nairobi" });
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    const { error: createError } = await api.POST("/api/manage/orgs/{org}/sites/", {
      params: { path: { org: slug } },
      body: form,
    });
    setBusy(false);
    if (createError) return setError(errorMessage(createError));
    setForm({ name: "", slug: "", timezone: "Africa/Nairobi" });
    await sites.reload();
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Sites" subtitle={org?.name} />
      <Card>
        {sites.loading && !sites.data ? <Loading /> : sites.error ? (
          <Alert>{errorMessage(sites.error)}</Alert>
        ) : sites.data?.length ? (
          <ul className="divide-y divide-zinc-100">
            {sites.data.map((site) => (
              <li key={site.id} className="flex items-center justify-between py-2.5">
                <div>
                  <Link className="font-medium hover:underline" href={`/orgs/${slug}/sites/${site.id}`}>{site.name}</Link>
                  <span className="ml-2 text-sm text-zinc-500">{site.slug} · {site.timezone}</span>
                </div>
                <StatusBadge value={site.status} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-zinc-500">No sites yet.</p>
        )}
      </Card>
      {can(org, "sites.manage") ? (
        <Card title="Create a site">
          <form className="grid gap-4 sm:grid-cols-3" onSubmit={create}>
            <Field label="Name"><Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="Slug" hint="Lowercase letters, numbers and dashes.">
              <Input required pattern="[a-z0-9-]+" value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} />
            </Field>
            <Field label="Time zone">
              <Input list="timezones" required value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} />
            </Field>
            <TimezoneOptions id="timezones" />
            <div className="sm:col-span-3 space-y-3">
              {error ? <Alert>{error}</Alert> : null}
              <Button type="submit" disabled={busy}>Create site</Button>
            </div>
          </form>
        </Card>
      ) : null}
    </div>
  );
}
