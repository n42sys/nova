# Nova — Phase 1 execution plan

Place this file at `docs/design/phase-1-plan.md`. Work through the tasks in order; each one builds on the last. Tick a task's box only when its acceptance criteria pass and `ruff` + `pytest` are green.

Design reference: `docs/design/phase-1-core-design.md` (data model, role matrix, auth flows). Where this plan and the design doc disagree, stop and ask.

**Phase 1 is done when** Culture & Interest can be set up end to end (org, sites, members with site roles, invitations, API token, media, payment account) and the tenant isolation suite passes.

---

## Environment variables

Keep `.env.example` in `apps/api/` in sync with this list.

| Variable | Purpose |
| --- | --- |
| `DJANGO_SETTINGS_MODULE` | `nova.settings.dev` / `.test` / `.prod` |
| `SECRET_KEY` | Django secret |
| `DATABASE_URL` | `postgres://nova:nova@localhost:55432/nova` |
| `REDIS_URL` | `redis://localhost:56379/0` |
| `NOVA_BASE_DOMAIN` | Production domain (TBD), e.g. `nova.example` |
| `NOVA_ADMIN_URL` | Admin app origin, used in invite and login-code emails |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `CORS_ALLOWED_ORIGINS` | Comma-separated |
| `NOVA_FERNET_KEYS` | Comma-separated Fernet keys, newest first |
| `NOVA_API_TOKEN_RATE` | Requests per API token, DRF rate syntax (default `600/min`) |
| `NOVA_TRUSTED_PROXY_COUNT` | Reverse proxies in front of the API (1 behind Caddy); used for the client IP |
| `RESEND_API_KEY`, `NOVA_EMAIL_FROM` | Transactional email |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_URL` | Media storage |
| `R2_ENDPOINT_URL` | Optional S3 endpoint override (defaults to the R2 endpoint for `R2_ACCOUNT_ID`) |
| `NOVA_MEDIA_MAX_BYTES` | Largest accepted upload in bytes (default 25 MB) |

---

## T0 — Repo bootstrap

Set up the monorepo, the Django project and tooling. No models yet.

- pnpm workspace at the root (`pnpm-workspace.yaml` listing `apps/*`, `packages/*`).
- `docker-compose.yml` at the root with `postgres:17` and `redis:7` only, named volumes, healthchecks.
- `apps/api` as a `uv` project. Dependencies: `django~=5.2`, `djangorestframework`, `drf-spectacular`, `django-allauth[headless]`, `django-environ`, `django-cors-headers`, `django-storages[s3]`, `boto3`, `celery[redis]`, `psycopg[binary]`, `cryptography`, `resend`, `uuid6`, `httpx`. Dev: `pytest`, `pytest-django`, `factory-boy`, `ruff`.
- Settings split into `nova/settings/{base,dev,test,prod}.py`, all read via `django-environ`.
- `nova/celery.py` wired up; `CELERY_TASK_ALWAYS_EAGER = True` in test settings.
- `ruff` config in `pyproject.toml` (line length 100, isort rules on). `pytest.ini` / `[tool.pytest.ini_options]` pointing at test settings.
- Empty `core` and `payments` apps created and installed.

**Acceptance**
- [x] `docker compose up -d` brings up healthy Postgres and Redis.
- [x] `uv run python manage.py check` passes (do **not** run `migrate` yet).
- [x] `uv run pytest` runs and reports no tests collected without error.
- [x] `ruff check` and `ruff format --check` pass.

## T1 — Core foundations, custom User and Organization

Must be finished before the first `migrate`.

- `core/fields.py`: `uuid7()` default using `uuid6.uuid7`.
- `core/models/base.py`: `BaseModel` (UUIDv7 `id`, `created_at`, `updated_at`), and `TenantModel(BaseModel)` with the guarded manager from the design doc (`unscoped` declared first, `default_manager_name = "unscoped"`, `objects.for_org(org)`, `objects.get_queryset()` raises `ImproperlyConfigured`). `organization` FK uses `on_delete=PROTECT`: organizations are suspended, never deleted, in Phase 1.
- `core/models/organization.py`: `Organization` (`name`, unique `slug`, `features` JSONB default `{}`, `status` active/suspended). Not a `TenantModel`: it is the tenant.
- `core/models/user.py`: custom `User` (email as username, `name`, `is_staff`), `AUTH_USER_MODEL = "core.User"`.
- `core/context.py`: `RequestContext` dataclass (`user`, `membership`, `organization`, `ip`, `actor_type`: user | token | system).
- `core/exceptions.py`: `NovaError`, `NotFound`, `PermissionDenied`, `ValidationFailed`, `Conflict`, plus a DRF exception handler mapping them to 404/403/400/409 JSON.
- First migration created and applied.

**Acceptance**
- [x] `migrate` succeeds on a fresh database.
- [x] Test: a throwaway `TenantModel` subclass (test-only app `core/tests/tenant_testapp`, installed only in test settings, no migrations) raises on `.objects.all()` and filters correctly with `.for_org()`.
- [x] Test: `User.objects.create_user(email=...)` works; email is case-insensitive unique.
- [x] Test: exception handler returns the right status and a stable JSON shape `{"error": {"code", "message", "details"}}`.

## T2 — Sites, memberships, site roles

`Organization` lands in T1.

- `Site(TenantModel)` (`name`, `slug`, `domain` nullable unique, `timezone` default `Africa/Nairobi`, `default_locale` default `en`, `settings` JSONB). Unique `(organization, slug)`.
- `Membership(TenantModel)` (`user`, `org_role` nullable). Unique `(organization, user)`.
- `SiteRole(TenantModel)` (`membership`, `site`, `role`). Unique `(membership, site)`. Service-level check that `site.organization_id == membership.organization_id`.
- `Role` TextChoices: `owner`, `admin`, `editor`, `event_staff`. `owner` is valid only as an `org_role`.
- `Membership.effective_role(site) -> Role | None`: `SiteRole` → `org_role` → `None`. Avoid N+1: prefetch site roles in the selector that loads the membership.
- Factories for `Site`, `Membership` and `SiteRole` (`Organization` and `User` factories exist from T1).

**Acceptance**
- [x] Tests for every constraint above, including the cross-org `SiteRole` rejection.
- [x] Tests for `effective_role`: site override wins; falls back to `org_role`; `None` when neither exists; `owner` cannot be a site role.

## T3 — Permissions

- `core/permissions.py`: `Perm` StrEnum covering every action in the design doc's role matrix, `ROLE_PERMS`, `ORG_ONLY_PERMS`, and `require(ctx, perm, site=None)` exactly as specified in the design doc.
- `Perm` values for later modules (forms, events, content, check-in) are declared now so the matrix is complete; their services come in later phases.
- Last-owner protection lives in the membership services (T6), not here.

**Acceptance**
- [x] Matrix test: parametrised over every `(Role, Perm)` pair, asserts allow/deny matches a literal copy of the design doc table kept in the test file.
- [x] Test: an org-only perm ignores a site override (an `event_staff` site role can never reach `PAYMENTS_MANAGE` via a site).
- [x] Test: a member with only a `SiteRole` on site A is denied on site B.

## T4 — Audit log

- `AuditLog(TenantModel)`: `actor_user` (nullable), `actor_token` (nullable), `action`, `target_type`, `target_id`, `metadata` JSONB, `ip`, `created_at`. Index `(organization, created_at)`.
- No `update`/`delete` path: override `save()` to refuse updates on existing rows and block queryset `.update()`/`.delete()` via a custom queryset.
- `core/audit.py`: `audit(ctx, action, target, metadata=None)`. Strips any key named like `*secret*`, `*token*`, `*password*` from metadata before writing.
- Selector `list_audit_log(org, *, cursor, limit)` with cursor pagination on `(created_at, id)`.

**Acceptance**
- [x] Test: updating or deleting an audit row raises.
- [x] Test: sensitive metadata keys are stripped.

## T5 — Auth and request context

- `django-allauth` headless only (`HEADLESS_ONLY = True`), email login, login-by-code enabled, email verification mandatory, `HEADLESS_FRONTEND_URLS` pointing at `NOVA_ADMIN_URL`. Allauth emails sent through Resend via a custom email backend that enqueues a Celery task.
- Session cookie: `HttpOnly`, `Secure` (prod), `SameSite=Lax`, cookie domain set to the shared parent domain in prod. CSRF enforced. CORS allows the admin origin with credentials.
- `GET /api/manage/me/`: user profile plus a list of organizations with `org_role` and site roles.
- `OrgScopedAPIView` base class: resolves `{org}` slug from the URL, loads the user's `Membership` for that org (prefetching site roles) or raises `NotFound`, builds `RequestContext` on `self.ctx`. All management views inherit it.
- `n42sys` staff access (`is_staff`) is **not** a bypass: it requires an explicit `support_session` service (Phase 1 can stub this as "not implemented").

**Acceptance**
- [x] Test: login, `/me/`, logout flow through the headless endpoints.
- [x] Test: a user with no membership in org B gets 404 on any `/api/manage/orgs/{b}/…` URL.
- [x] Test: unauthenticated management requests get 401 (not 403).

## T6 — Management API: org, sites, members

All under `/api/manage/orgs/{org}/`. Services in `core/services/`, selectors in `core/selectors/`.

| Method | Path | Perm |
| --- | --- | --- |
| GET, PATCH | `/` (org details, name only for now) | view / `ORG_MANAGE` |
| GET, POST | `/sites/` | view / `SITES_MANAGE` |
| GET, PATCH, DELETE | `/sites/{site_id}/` | view / `SITES_MANAGE` |
| GET | `/members/` | `MEMBERS_VIEW` |
| PATCH, DELETE | `/members/{membership_id}/` (change `org_role`, remove) | `MEMBERS_MANAGE` |
| PUT, DELETE | `/members/{membership_id}/site-roles/{site_id}/` | `MEMBERS_MANAGE` |
| GET | `/audit-log/` | `AUDIT_VIEW` |

Rules: admins grant only `editor` or `event_staff` (org role or site role), cannot change, remove or edit the site roles of members whose `org_role` is admin or owner, and only owners grant, change or remove `owner` and `admin`; the last owner cannot be demoted or removed; a member cannot change their own role; site delete is a soft delete (`status = archived`) in Phase 1. Every write is audited.

- Promoting a member to `owner` deletes their `SiteRole` rows in the same transaction (owners never hold site roles).
- The site service validates `timezone` against `zoneinfo.available_timezones()`.
- Public member services wrap `core.services.memberships._set_site_role` with `require()` and `audit()`.
- There is no `ORG_VIEW` perm: `GET /` is open to any member of the org, and `GET /sites/` returns only sites where the member has `SITE_VIEW`. Test it with a site-only member (null `org_role`).

- `core/tests/test_isolation.py`: fixtures build org A and org B with identical data (sites, members, site roles). A parametrised test hits **every** management endpoint as a member of A against B's IDs and slugs and asserts 404 with no B data in the body. Adding an endpoint without registering it here must fail a test (collect URL patterns under `/api/manage/` and compare against the registered list).

**Acceptance**
- [x] Service tests for each rule above.
- [x] Isolation suite green and covering every route.

## T7 — Invitations

- `Invitation(TenantModel)` per design doc, with `org_role` (nullable) and `site_roles` JSONB (`[{"site_id", "role"}]`). Validation: at least one of `org_role` or `site_roles`; `owner` only as `org_role`. Only owners can invite as `owner` or `admin` (org or site role); admins invite only `editor` / `event_staff`.
- Token: 32 random bytes, URL-safe; store SHA-256 hash; 7-day expiry; re-inviting the same email revokes the previous open invite.
- Endpoints: `GET/POST /api/manage/orgs/{org}/invitations/`, `DELETE …/invitations/{id}/`, `POST …/invitations/{id}/resend/`, and public `GET /api/manage/invitations/{token}/` (read-only preview: org name, inviter, role), `POST /api/manage/invitations/{token}/claim/` (CSRF-protected; remembers the invitation in the session so the invitee can sign up) and `POST /api/manage/invitations/{token}/accept/` (requires a logged-in user whose email matches).
- Tokens are resolved only in `core/selectors/token_resolution.py`, the one request-path module allowed to use `.unscoped` (rule 1).
- Accept runs in one transaction: create `Membership` (or update an existing one, merging roles so no effective role is ever lowered), create `SiteRole` rows through `_set_site_role`, mark accepted, mark the email verified, audit.
- Invite email sent by a Celery task through Resend, linking to `{NOVA_ADMIN_URL}/invite/{token}`.
- The allauth account adapter (`core.auth_adapter.AccountAdapter`, closed since T5) opens sign-up only for an email with a valid open invitation. Accepting an invitation marks that email as verified.

**Acceptance**
- [x] Tests: expired, revoked, already-accepted and wrong-email tokens all fail cleanly.
- [x] Test: accepting an invite with site roles produces the right `effective_role` per site.
- [x] Test: the raw token never appears in the database or audit log.

## T8 — API tokens and the delivery skeleton

- `ApiToken(TenantModel)` per design doc. Format `nova_dlv_{prefix}_{secret}` / `nova_prv_{prefix}_{secret}`; `prefix` 8 chars stored in clear and indexed; secret hashed with SHA-256; compare with `hmac.compare_digest`.
- Management endpoints: `GET/POST /api/manage/orgs/{org}/sites/{site_id}/tokens/`, `DELETE …/tokens/{id}/` (revoke). POST returns the raw token once.
- `core/auth.py`: DRF `ApiTokenAuthentication` for `Authorization: Bearer …`. Rejects revoked tokens. Updates `last_used_at` at most once per minute (cache key per token).
- Throttling: DRF throttle keyed by token prefix, `600/min` default.
- `DeliveryAPIView` base: token auth only, no session; exposes `self.site` and `self.organization`.
- Smoke endpoint `GET /api/v1/site/` returning the token's site name, slug, timezone, locale.

**Acceptance**
- [x] Tests: valid token works; revoked, malformed and wrong-prefix tokens get 401; a delivery token cannot call management endpoints and a session cannot call delivery endpoints.
- [x] Test: a token for site A only ever sees site A.

## T9 — Media

R2 does not support presigned POST, so uploads use a presigned PUT.

- `MediaAsset(TenantModel)` per design doc, `site` nullable, plus `status` (`pending`, `ready`, `deleting`, `invalid`).
- `POST /api/manage/orgs/{org}/media/uploads/`: validates mime type (images, PDF, audio/video allowlist) and declared size (default 25 MB, `NOVA_MEDIA_MAX_BYTES`), creates `MediaAsset(status=pending)` with `file_key` under `orgs/{org_id}/{uuid7}/{filename}`, and returns a presigned PUT URL (15-minute expiry, `Content-Type` signed in).
- `POST …/media/` confirms the upload: `head_object`; if the object is missing, 400; if its size or type does not match, delete the object and return 400; otherwise set `status=ready`. Image dimensions are read in a Celery task (Pillow); if Pillow cannot open the file, the task sets `status=invalid`, deletes the R2 object and logs it.
- `GET …/media/` (cursor-paginated, filter by site and mime prefix, **only `ready` assets**), `PATCH …/media/{id}/` (alt text), `DELETE …/media/{id}/` (marks `deleting`; a Celery task deletes the object, then hard-deletes the row).
- A daily Celery beat task (static `CELERY_BEAT_SCHEDULE`, no extra dependency) deletes `pending` assets older than 24 hours and their R2 objects.
- Tests mock S3 with `moto[s3]` (dev dependency).

**Acceptance**
- [x] Tests: disallowed type and oversize rejected; confirm fails if the object is missing; keys are always under the caller's org prefix; editor can upload but not delete.

## T10 — Payment accounts

- `core/crypto.py`: `encrypt(str) -> bytes`, `decrypt(bytes) -> str` using `MultiFernet` built from `NOVA_FERNET_KEYS`. Management command `rotate_payment_secrets` re-encrypts all rows with the newest key.
- `PaymentAccount(TenantModel)` per design doc.
- `payments/providers/base.py`: `PaymentProvider` Protocol with `verify_credentials(account) -> None` (raises on failure). Checkout methods are added in Phase 4.
- `payments/providers/paystack.py`: `verify_credentials` makes one authenticated, read-only request to the Paystack API with `httpx` (choose the endpoint from Paystack's current docs; mock it in tests).
- Endpoints (owner only): `GET/POST /api/manage/orgs/{org}/payment-accounts/`, `PATCH …/{id}/` (replace keys), `POST …/{id}/verify/`, `DELETE …/{id}/` (sets `disabled`). Responses expose `provider`, `public_key`, `status`, `verified_at`, and a masked hint like `sk_live_…a1b2` — never the secret.

**Acceptance**
- [ ] Secret hygiene test: create an account and an API token, then assert neither raw secret appears in any API response body, captured log record (`caplog`) or audit metadata.
- [ ] Test: non-owners get 403 on every payment-account endpoint (404 if from another org).
- [ ] Test: key rotation command decrypts old rows and re-encrypts with the new key.

## T11 — OpenAPI and shared types

- `@extend_schema` on every view; component names stable.
- `packages/api-types`: `package.json` with a `generate` script running `openapi-typescript openapi.yaml -o src/schema.d.ts`; export a typed `openapi-fetch` client factory.
- Add a test that generates the schema and fails on spectacular warnings. (Added early in T6 as `core/tests/test_openapi.py`; every task keeps it green.)

**Acceptance**
- [ ] `spectacular --validate --fail-on-warn` passes.
- [ ] `pnpm --filter api-types generate && pnpm --filter api-types build` succeeds.

## T12 — Thin admin app

Enough UI to run Culture & Interest's setup; polish comes in later phases.

- `apps/admin`: Next.js App Router, TypeScript, Tailwind, the `api-types` client with `credentials: "include"`.
- Screens: login (password + login code), accept invite, organization switcher, sites list/create/edit, members list with org role and per-site roles editor, invitations, API tokens (show raw token once with a copy button), payment accounts (owner only).
- Route handlers never proxy secrets; forms post straight to the API.
- Hide UI for actions the current role lacks, but rely on the API for enforcement.

**Acceptance**
- [ ] Manual run-through: invite a second user as `editor` on one site and `event_staff` on another, accept, and confirm what each screen allows.

## T13 — Deployment (VPS)

- `apps/api/Dockerfile` (uv, gunicorn with uvicorn workers), `apps/admin/Dockerfile` (Next.js standalone output).
- `deploy/docker-compose.prod.yml`: Caddy (automatic HTTPS for `admin.`, `api.` and `public.` subdomains of `NOVA_BASE_DOMAIN`), api, celery worker, admin, postgres 17, redis.
- Nightly `pg_dump` to R2 (a small container with a cron schedule), 14-day retention.
- `deploy/README.md` with the first-deploy and update steps.
- Redis is reachable only on the internal Docker network and has `requirepass` set (`REDIS_URL` carries the password).
- `NOVA_TRUSTED_PROXY_COUNT=1` behind Caddy; set it to `2` if Cloudflare is ever put in front of Caddy.
- The R2 bucket's CORS rule must allow `PUT` (with `Content-Type`) from the admin origin, for presigned media uploads.
- Run a `celery beat` process alongside the worker (media cleanup schedule from T9).
- Serve media (`R2_PUBLIC_URL`) from a host outside the session cookie's parent domain (not a subdomain of `NOVA_BASE_DOMAIN`), so uploaded files can never read or set the admin session cookie.

**Acceptance**
- [ ] Fresh VPS deploy reaches a working login over HTTPS.
- [ ] A backup file appears in R2 and restores into a scratch database.

## T14 — Seed Culture & Interest

- Management command `bootstrap_org --name "Culture & Interest" --slug culture-interest --owner-email <email> --site "Main:main"` creating the org, its first site, and an owner invitation.
- Org `features`: `{"forms": true, "events": true, "content": true}`.

**Acceptance**
- [ ] Command is idempotent (re-running does not duplicate anything).
- [ ] The owner receives the invite, accepts, and completes setup through the admin.

---

## After Phase 1

Next: Phase 2 (forms), then Phase 3 (events with free RSVP, reusing forms for registration questions), then Phase 4 (paid tickets via each org's Paystack account, reservations, QR tickets, check-in), then Phase 5 (blog and page sections). Each gets its own design doc and plan in `docs/design/` before code.

Carried forward from Phase 1:

- **Backlog: leave organization endpoint** (with the last-owner rule). Members cannot remove themselves through the member endpoints.
- **Backlog: SVG uploads with sanitisation.** SVG is excluded from the T9 allowlist because it can carry script; allow it only once uploads are sanitised server-side.
- **Phase 3 needs an event staff assignment model.** `EVENTS_VIEW_ASSIGNED` and `ATTENDEES_VIEW_ASSIGNED` (granted to event staff) must filter to the member's assigned events unless the broad `EVENTS_VIEW` / `ATTENDEES_VIEW` is also held. `TICKETS_CHECK_IN` for event staff must likewise be limited to assigned events.
