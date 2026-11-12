// Type-level checks for the generated schema and clients (`pnpm --filter api-types typecheck`).
// Every @ts-expect-error must stay an error; if one stops failing, tsc reports it.
import { createDeliveryClient, createManagementClient, type Schemas } from "../src/index";

const api = createManagementClient({ baseUrl: "https://api.example.test" });

export async function sites(): Promise<Schemas["Site"][] | undefined> {
  const { data } = await api.GET("/api/manage/orgs/{org}/sites/", {
    params: { path: { org: "culture-interest" } },
  });
  return data;
}

export async function createSite() {
  const { data, error } = await api.POST("/api/manage/orgs/{org}/sites/", {
    params: { path: { org: "culture-interest" } },
    body: { name: "Listening Room", slug: "listening", timezone: "Africa/Nairobi" },
  });
  const slug: string | undefined = data?.slug;
  return { slug, error };
}

export async function paymentAccounts() {
  const { data } = await api.GET("/api/manage/orgs/{org}/payment-accounts/", {
    params: { path: { org: "culture-interest" } },
  });
  const hint: string | undefined = data?.[0]?.secret_key_hint;
  // @ts-expect-error the API never returns the secret key
  const secret = data?.[0]?.secret_key;
  return { hint, secret };
}

export async function mistakes() {
  // @ts-expect-error unknown path
  await api.GET("/api/manage/orgs/{org}/nope/", { params: { path: { org: "x" } } });
  // @ts-expect-error missing required path parameter
  await api.GET("/api/manage/orgs/{org}/sites/", { params: { path: {} } });
  await api.POST("/api/manage/orgs/{org}/sites/", {
    params: { path: { org: "x" } },
    // @ts-expect-error slug is required
    body: { name: "No slug" },
  });
}

export async function delivery() {
  const client = createDeliveryClient({ baseUrl: "https://api.example.test", token: "nova_dlv_x" });
  const { data } = await client.GET("/api/v1/site/");
  const timezone: string | undefined = data?.timezone;
  return timezone;
}

export const roles: Schemas["RoleEnum"][] = ["owner", "admin", "editor", "event_staff"];
// @ts-expect-error not a role
export const badRole: Schemas["RoleEnum"] = "superuser";
