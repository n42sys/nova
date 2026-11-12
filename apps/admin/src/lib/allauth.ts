/**
 * django-allauth headless "browser" endpoints (session cookie + CSRF). These are not part of
 * the DRF OpenAPI schema, so they get this small hand-written wrapper.
 */
import { readCsrfCookie } from "api-types";

import { API_URL } from "./config";

const BASE = `${API_URL}/_allauth/browser/v1`;

export type AuthFlow = { id: string; is_pending?: boolean };
export type AuthResult = {
  status: number;
  ok: boolean;
  /** Pending flows, e.g. "login_by_code" or "verify_email", when status is 401. */
  pending: string[];
  message?: string;
  /** Every error message allauth returned (e.g. all password validator messages). */
  messages: string[];
};

async function ensureCsrfCookie(): Promise<void> {
  if (!readCsrfCookie()) {
    await fetch(`${BASE}/config`, { credentials: "include" });
  }
}

async function call(
  method: string,
  path: string,
  body?: unknown,
  extraHeaders: Record<string, string> = {},
): Promise<AuthResult> {
  await ensureCsrfCookie();
  const response = await fetch(`${BASE}${path}`, {
    method,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(readCsrfCookie() ? { "X-CSRFToken": readCsrfCookie() as string } : {}),
      ...extraHeaders,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const json = await response.json().catch(() => ({}));
  const flows: AuthFlow[] = json?.data?.flows ?? [];
  const errors: { message?: string }[] = json?.errors ?? [];
  return {
    status: response.status,
    ok: response.status === 200,
    pending: flows.filter((flow) => flow.is_pending).map((flow) => flow.id),
    message: errors[0]?.message,
    messages: errors.map((error) => error.message).filter((message): message is string => Boolean(message)),
  };
}

export const allauth = {
  session: () => call("GET", "/auth/session"),
  login: (email: string, password: string) => call("POST", "/auth/login", { email, password }),
  requestCode: (email: string) => call("POST", "/auth/code/request", { email }),
  confirmCode: (code: string) => call("POST", "/auth/code/confirm", { code }),
  signup: (email: string, password: string) => call("POST", "/auth/signup", { email, password }),
  verifyEmail: (key: string) => call("POST", "/auth/email/verify", { key }),
  logout: () => call("DELETE", "/auth/session"),
  /** Always 200, whether or not the address has an account (no enumeration). */
  requestPasswordReset: (email: string) => call("POST", "/auth/password/request", { email }),
  checkPasswordResetKey: (key: string) =>
    call("GET", "/auth/password/reset", undefined, { "X-Password-Reset-Key": key }),
  /** 401 means the password was changed and the user should now sign in. */
  resetPassword: (key: string, password: string) =>
    call("POST", "/auth/password/reset", { key, password }),
};
