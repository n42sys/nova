import { createManagementClient, type Schemas } from "api-types";

import { API_URL } from "./config";

/**
 * The one client for the management API. The browser calls the API directly with the
 * session cookie; the admin app never proxies requests or handles secrets server-side.
 */
export const api = createManagementClient({ baseUrl: API_URL });

export type { Schemas };
export type Me = Schemas["Me"];
export type MeOrganization = Schemas["MeOrganization"];
export type Site = Schemas["Site"];
export type Member = Schemas["Member"];
export type Invitation = Schemas["Invitation"];
export type ApiToken = Schemas["ApiToken"];
export type PaymentAccount = Schemas["PaymentAccount"];
export type Role = Schemas["RoleEnum"];
export type SiteRole = Schemas["SiteRoleEnum"];
export type Perm = Schemas["PermEnum"];
