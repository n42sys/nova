"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Alert, Button, Card, Loading, PageHeader, Select } from "@/components/ui";
import { api, type Member, type MeOrganization, type Role, type Site, type SiteRole } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { ROLE_LABELS, canManageTarget, grantableRoles } from "@/lib/perms";
import { useResource } from "@/lib/resource";
import { useOrg, useSession } from "@/lib/session";

function MemberRow({
  member,
  sites,
  org,
  slug,
  isSelf,
  onChange,
}: {
  member: Member;
  sites: Site[];
  org: MeOrganization;
  slug: string;
  isSelf: boolean;
  onChange: (error?: unknown) => Promise<void>;
}) {
  const manageable = !isSelf && canManageTarget(org, member.org_role);
  const grantable = grantableRoles(org);
  const siteRoleOptions = grantable.filter((role): role is SiteRole => role !== "owner");
  const roleOf = (siteId: string) => member.site_roles.find((item) => item.site_id === siteId)?.role ?? "";
  const path = { org: slug, membership_id: member.id };

  async function setOrgRole(value: string) {
    const { error } = await api.PATCH("/api/manage/orgs/{org}/members/{membership_id}/", {
      params: { path },
      body: { org_role: (value || null) as Role | null },
    });
    await onChange(error);
  }

  async function setSiteRole(siteId: string, value: string) {
    const params = { path: { ...path, site_id: siteId } };
    const { error } = value
      ? await api.PUT("/api/manage/orgs/{org}/members/{membership_id}/site-roles/{site_id}/", { params, body: { role: value as SiteRole } })
      : await api.DELETE("/api/manage/orgs/{org}/members/{membership_id}/site-roles/{site_id}/", { params });
    await onChange(error);
  }

  async function remove() {
    if (!window.confirm(`Remove ${member.user.email} from this organization?`)) return;
    const { error } = await api.DELETE("/api/manage/orgs/{org}/members/{membership_id}/", { params: { path } });
    await onChange(error);
  }

  return (
    <tr className="align-top">
      <td className="py-3 pr-4">
        <div className="font-medium">{member.user.name || member.user.email}</div>
        <div className="text-zinc-500">{member.user.email}{isSelf ? " (you)" : ""}</div>
      </td>
      <td className="py-3 pr-4">
        <Select disabled={!manageable} value={member.org_role ?? ""} onChange={(e) => setOrgRole(e.target.value)}>
          <option value="">Site roles only</option>
          {(["owner", "admin", "editor", "event_staff"] as Role[]).map((role) => (
            <option key={role} value={role} disabled={!grantable.includes(role) && role !== member.org_role}>
              {ROLE_LABELS[role]}
            </option>
          ))}
        </Select>
      </td>
      <td className="py-3 pr-4">
        {member.org_role === "owner" ? (
          <span className="text-zinc-500">Owner on every site</span>
        ) : (
          <div className="space-y-1.5">
            {sites.map((site) => {
              const current = roleOf(site.id);
              return (
                <div key={site.id} className="flex items-center gap-2">
                  <span className="w-32 truncate">{site.name}</span>
                  <Select
                    disabled={!manageable || (current === "admin" && org.org_role !== "owner")}
                    value={current}
                    onChange={(e) => setSiteRole(site.id, e.target.value)}
                  >
                    <option value="">{member.org_role ? `Org role (${ROLE_LABELS[member.org_role]})` : "No access"}</option>
                    {(["admin", "editor", "event_staff"] as SiteRole[]).map((role) => (
                      <option key={role} value={role} disabled={!siteRoleOptions.includes(role) && role !== current}>
                        {ROLE_LABELS[role]}
                      </option>
                    ))}
                  </Select>
                </div>
              );
            })}
          </div>
        )}
      </td>
      <td className="py-3 text-right">
        {manageable ? <Button variant="danger" onClick={remove}>Remove</Button> : null}
      </td>
    </tr>
  );
}

export default function MembersPage() {
  const { org: slug } = useParams<{ org: string }>();
  const org = useOrg(slug);
  const me = useSession();
  const members = useResource(() => api.GET("/api/manage/orgs/{org}/members/", { params: { path: { org: slug } } }), [slug]);
  const sites = useResource(() => api.GET("/api/manage/orgs/{org}/sites/", { params: { path: { org: slug } } }), [slug]);
  const [error, setError] = useState<string>();

  async function onChange(changeError?: unknown) {
    setError(changeError ? errorMessage(changeError) : undefined);
    await Promise.all([members.reload(), me.reload()]);
  }

  if (!org || (members.loading && !members.data)) return <Loading />;
  if (members.error) return <Alert>{errorMessage(members.error)}</Alert>;
  return (
    <div className="space-y-6">
      <PageHeader title="Members" subtitle="A site role overrides the org role on that site." />
      {error ? <Alert>{error}</Alert> : null}
      <Card>
        <table className="w-full text-sm">
          <thead className="text-left text-zinc-500">
            <tr><th className="pb-2">Member</th><th className="pb-2">Org role</th><th className="pb-2">Site roles</th><th /></tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {members.data?.map((member) => (
              <MemberRow
                key={member.id}
                member={member}
                sites={sites.data ?? []}
                org={org}
                slug={slug}
                isSelf={member.user.id === me.data?.id}
                onChange={onChange}
              />
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
