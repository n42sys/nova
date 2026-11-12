import type { MeOrganization, Perm, Role } from "./api";

/** UI hints only: the API enforces every permission and is the source of these lists. */
export function can(subject: { permissions: Perm[] } | undefined, perm: Perm): boolean {
  return Boolean(subject?.permissions.includes(perm));
}

export const ROLE_LABELS: Record<Role, string> = {
  owner: "Owner",
  admin: "Admin",
  editor: "Editor",
  event_staff: "Event staff",
};

/** Roles the caller may grant: owners any; admins only roles below admin (T6 rules). */
export function grantableRoles(org: MeOrganization | undefined): Role[] {
  if (org?.org_role === "owner") return ["owner", "admin", "editor", "event_staff"];
  if (org && can(org, "members.manage")) return ["editor", "event_staff"];
  return [];
}

export function canManageTarget(org: MeOrganization | undefined, targetRole: Role | null): boolean {
  if (!org || !can(org, "members.manage")) return false;
  return org.org_role === "owner" || !(targetRole === "owner" || targetRole === "admin");
}
