"use client";

import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert, Button, Card, Field, Input, Loading, PageHeader, Select, StatusBadge } from "@/components/ui";
import { api, type Invitation, type Role, type SiteRole } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { ROLE_LABELS, can, grantableRoles } from "@/lib/perms";
import { useResource } from "@/lib/resource";
import { useOrg } from "@/lib/session";

export default function InvitationsPage() {
  const { org: slug } = useParams<{ org: string }>();
  const org = useOrg(slug);
  const path = { params: { path: { org: slug } } };
  const invitations = useResource(() => api.GET("/api/manage/orgs/{org}/invitations/", path), [slug]);
  const sites = useResource(() => api.GET("/api/manage/orgs/{org}/sites/", path), [slug]);
  const [email, setEmail] = useState("");
  const [orgRole, setOrgRole] = useState<string>("");
  const [siteRoles, setSiteRoles] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string }>();

  const manage = can(org, "members.manage");
  const grantable = grantableRoles(org);
  const siteGrantable = grantable.filter((role): role is SiteRole => role !== "owner");
  const isOwner = org?.org_role === "owner";
  const privileged = (invitation: Invitation) =>
    invitation.org_role === "owner" || invitation.org_role === "admin" || invitation.site_roles.some((item) => item.role === "admin");

  async function invite(event: FormEvent) {
    event.preventDefault();
    const body = {
      email,
      org_role: (orgRole || null) as Role | null,
      site_roles: Object.entries(siteRoles)
        .filter(([, role]) => role)
        .map(([site_id, role]) => ({ site_id, role: role as SiteRole })),
    };
    const { error } = await api.POST("/api/manage/orgs/{org}/invitations/", { ...path, body });
    if (error) return setMessage({ kind: "error", text: errorMessage(error) });
    setMessage({ kind: "success", text: `Invitation sent to ${email}.` });
    setEmail("");
    setOrgRole("");
    setSiteRoles({});
    await invitations.reload();
  }

  async function act(invitation: Invitation, action: "revoke" | "resend") {
    const params = { params: { path: { org: slug, invitation_id: invitation.id } } };
    const { error } =
      action === "revoke"
        ? await api.DELETE("/api/manage/orgs/{org}/invitations/{invitation_id}/", params)
        : await api.POST("/api/manage/orgs/{org}/invitations/{invitation_id}/resend/", params);
    setMessage(error ? { kind: "error", text: errorMessage(error) } : { kind: "success", text: action === "revoke" ? "Invitation revoked." : "Invitation re-sent with a new link." });
    await invitations.reload();
  }

  const siteName = (id: string) => sites.data?.find((site) => site.id === id)?.name ?? "Unknown site";

  if (!org || (invitations.loading && !invitations.data)) return <Loading />;
  if (invitations.error) return <Alert>{errorMessage(invitations.error)}</Alert>;
  return (
    <div className="space-y-6">
      <PageHeader title="Invitations" subtitle="Invitations expire after 7 days." />
      {message ? <Alert kind={message.kind}>{message.text}</Alert> : null}
      {manage ? (
        <Card title="Invite someone">
          <form className="space-y-4" onSubmit={invite}>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Email"><Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
              <Field label="Org role" hint="Applies to every site unless a site role overrides it.">
                <Select value={orgRole} onChange={(e) => setOrgRole(e.target.value)}>
                  <option value="">None (site roles only)</option>
                  {grantable.map((role) => <option key={role} value={role}>{ROLE_LABELS[role]}</option>)}
                </Select>
              </Field>
            </div>
            {orgRole !== "owner" ? (
              <div className="space-y-2">
                <span className="text-sm font-medium text-zinc-700">Site roles</span>
                {sites.data?.map((site) => (
                  <div key={site.id} className="flex items-center gap-2 text-sm">
                    <span className="w-40 truncate">{site.name}</span>
                    <Select value={siteRoles[site.id] ?? ""} onChange={(e) => setSiteRoles({ ...siteRoles, [site.id]: e.target.value })}>
                      <option value="">—</option>
                      {siteGrantable.map((role) => <option key={role} value={role}>{ROLE_LABELS[role]}</option>)}
                    </Select>
                  </div>
                ))}
              </div>
            ) : null}
            <Button type="submit">Send invitation</Button>
          </form>
        </Card>
      ) : null}
      <Card title="Sent invitations">
        {invitations.data?.length ? (
          <table className="w-full text-sm">
            <thead className="text-left text-zinc-500">
              <tr><th className="pb-2">Email</th><th className="pb-2">Roles</th><th className="pb-2">Status</th><th /></tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {invitations.data.map((invitation) => (
                <tr key={invitation.id}>
                  <td className="py-2">{invitation.email}</td>
                  <td className="py-2">
                    {[
                      invitation.org_role ? `${ROLE_LABELS[invitation.org_role]} (org)` : null,
                      ...invitation.site_roles.map((item) => `${ROLE_LABELS[item.role]} on ${siteName(item.site_id)}`),
                    ].filter(Boolean).join(", ")}
                  </td>
                  <td className="py-2"><StatusBadge value={invitation.status} /></td>
                  <td className="py-2 text-right">
                    {manage && (isOwner || !privileged(invitation)) && (invitation.status === "open" || invitation.status === "expired") ? (
                      <div className="flex justify-end gap-2">
                        <Button variant="secondary" onClick={() => act(invitation, "resend")}>Resend</Button>
                        <Button variant="danger" onClick={() => act(invitation, "revoke")}>Revoke</Button>
                      </div>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-sm text-zinc-500">No invitations yet.</p>
        )}
      </Card>
    </div>
  );
}
