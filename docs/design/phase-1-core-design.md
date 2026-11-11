# Nova — Phase 1 Core Design

Companion to `docs/design/phase-1-plan.md`. The plan says *what to build in what order*; this doc says *how the core is shaped and why*. If the two disagree, stop and ask.

## Overview

Phase 1 delivers Nova's core: multi-tenant organizations and sites, user membership with per-site roles, invitations, media, API tokens, an audit log, and encrypted payment-account storage. Every later module (forms, events, tickets, blog) builds on it and depends on nothing else.

**Constraints that shape every decision**

- **Client staff manage their own sites.** Permissions must be real and enforced, not cosmetic.
- **Internal tooling now, product later.** Build SaaS-grade tenant boundaries now; defer sign-up, billing and custom domains.
- **Payments go direct to each client.** Nova never holds funds; each organization brings its own payment account (Paystack first).

**In scope:** organizations, sites, users, memberships, site roles, invitations, login, media library on R2, scoped API tokens, audit log, `PaymentAccount` with encrypted secrets (no checkout), Management REST API, thin admin, VPS deployment.

**Out of scope:** forms, events, tickets, blog, page sections; self-serve sign-up, billing, custom domain provisioning; a polished admin UI.

**Build order after Phase 1** (first tenant is Culture & Interest, events-first): forms → events with free RSVP → paid tickets → blog and page sections.

## Tenancy model

Nova uses one shared Postgres schema with an `organization_id` on every tenant-owned row. An **Organization** is a client; it owns one or more **Sites**. Users join organizations through **Memberships**, so one person can work across several clients.

**Why shared schema, not schema-per-tenant:** migrations run once, cross-tenant ops (support work, later analytics) stay simple, and it scales to hundreds of tenants without connection or migration pain. Isolation comes from discipline in code, backed by tests.

**Scoping rules**

1. Every tenant-owned model inherits `TenantModel`, which carries `organization` (FK, indexed, non-null).
2. Its `objects` manager refuses unscoped queries: code must call `.for_org(org)`. The `unscoped` manager exists for migrations, management commands and tasks only, and is grepped for in review.
3. The current organization is resolved once per request (from the URL for the management API, from the token for the delivery API) and passed explicitly into services. No thread-local magic.
4. Site-owned data carries both `organization` and `site`; services verify the site belongs to that organization.
5. Unique constraints are per tenant, e.g. `UniqueConstraint(fields=["site", "slug"])`, never a global unique slug.

```python
class TenantManager(models.Manager):
    def get_queryset(self):
        raise ImproperlyConfigured("Use .for_org(org) or .unscoped")

    def for_org(self, org):
        return super().get_queryset().filter(organization=org)

class TenantModel(BaseModel):
    organization = models.ForeignKey("core.Organization", on_delete=models.PROTECT, db_index=True)
    unscoped = models.Manager()   # declared first: Django internals use it
    objects = TenantManager()      # app code: Model.objects.for_org(org)

    class Meta:
        abstract = True
        default_manager_name = "unscoped"
```

`on_delete=PROTECT` because organizations are suspended, never deleted, in Phase 1.

`default_manager_name = "unscoped"` matters: Django's admin, related-object access and serialization use the default manager, so pointing it at the plain manager keeps those internals off the guard. Traversing from an already-scoped object (`site.api_tokens.all()`) stays inside the tenant.

Postgres row-level security can be layered on later as defense in depth; the code-level rules stay the primary boundary.

## Core data model

Ten models make up the core. All primary keys are UUIDv7 (time-ordered, safe to expose in URLs); all timestamps are UTC with `created_at` / `updated_at`.

| Model | Key fields | Constraints and notes |
| --- | --- | --- |
| `Organization` | `name`, `slug`, `features` (JSONB), `status` (active, suspended) | Global unique `slug`. `features` toggles modules now, becomes plan limits later. Not a `TenantModel`: it is the tenant. |
| `Site` | `organization`, `name`, `slug`, `domain` (nullable), `timezone`, `default_locale`, `settings` (JSONB), `status` (active, archived) | Unique `(organization, slug)`; unique `domain` when set. `timezone` defaults to `Africa/Nairobi`. |
| `User` | `email`, `name`, `is_staff`, `last_login` | Custom user model, email as username. Global, not tenant-owned. `is_staff` = n42sys ops only. |
| `Membership` | `user`, `organization`, `org_role` (nullable) | Unique `(user, organization)`. `org_role` applies to every site and to org-level actions. Null means site-only access. |
| `SiteRole` | `membership`, `site`, `role` | Unique `(membership, site)`. Overrides `org_role` on that site. Site must belong to the membership's org. `owner` is not allowed here. |
| `Invitation` | `organization`, `email`, `org_role` (nullable), `site_roles` (JSONB), `token_hash`, `invited_by`, `expires_at`, `accepted_at`, `revoked_at` | Token stored hashed. Expires in 7 days. One open invite per `(organization, email)`. `site_roles` becomes `SiteRole` rows on accept. |
| `MediaAsset` | `organization`, `site` (nullable), `file_key`, `mime_type`, `size_bytes`, `width`, `height`, `alt_text`, `uploaded_by` | File lives in R2; row holds metadata. Org-wide when `site` is null. |
| `ApiToken` | `organization`, `site`, `name`, `kind` (delivery, preview), `prefix`, `token_hash`, `last_used_at`, `revoked_at` | Shown once on creation. Lookup by `prefix`, verify against hash. Scoped to one site. |
| `AuditLog` | `organization`, `actor_user`, `actor_token`, `action`, `target_type`, `target_id`, `metadata` (JSONB), `ip`, `created_at` | Append-only. Indexed on `(organization, created_at)`. |
| `PaymentAccount` | `organization`, `provider` (paystack, daraja), `public_key`, `secret_key_encrypted`, `status` (pending, verified, disabled), `verified_at` | Secret is Fernet-encrypted and never returned by any API. Unique `(organization, provider)`. |

**Effective role on a site** = the `SiteRole` for that site if one exists, otherwise `org_role`, otherwise no access. Org-level actions use `org_role` only. Example: someone can be `editor` on a client's main site and `event_staff` on its events site, with no org role at all.

**Deliberate omissions:** no `Plan` or `Subscription` models yet; `features` covers module toggles until billing exists.

## Roles and permissions

Four fixed roles, checked in the service layer so the API, admin UI and background jobs share one rule set. Owner ⊃ admin ⊃ editor; event staff is a narrow side role.

| Action | Owner | Admin | Editor | Event staff |
| --- | --- | --- | --- | --- |
| View sites and content | Yes | Yes | Yes | Assigned events only |
| Create and edit content, forms, events | Yes | Yes | Yes | No |
| Publish and unpublish | Yes | Yes | Yes | No |
| Upload media | Yes | Yes | Yes | No |
| Delete media | Yes | Yes | No | No |
| View form submissions and attendee lists | Yes | Yes | Yes | Assigned events only |
| Check in tickets | Yes | Yes | Yes | Yes |
| Create sites, change site settings | Yes | Yes | No | No |
| Create and revoke API tokens | Yes | Yes | No | No |
| Invite members, change roles below own (org-only) | Yes | Yes (not to owner) | No | No |
| View audit log (org-only) | Yes | Yes | No | No |
| Add or change payment accounts (org-only) | Yes | No | No | No |
| Transfer ownership, delete organization (org-only) | Yes | No | No | No |

Rows marked *org-only* always use `org_role`, never a site override. Every organization must always have at least one owner; services refuse to demote or remove the last one. n42sys staff (`User.is_staff`) get no silent bypass; support access will be an explicit, audited action.

**Enforcement pattern**

```python
ROLE_PERMS: dict[Role, frozenset[Perm]] = {...}  # single source of truth, mirrors the table
ORG_ONLY_PERMS: frozenset[Perm] = frozenset({Perm.MEMBERS_MANAGE, Perm.AUDIT_VIEW, Perm.PAYMENTS_MANAGE, ...})

def require(ctx: RequestContext, perm: Perm, site: Site | None = None) -> None:
    if perm in ORG_ONLY_PERMS or site is None:
        role = ctx.membership.org_role
    else:
        role = ctx.membership.effective_role(site)  # SiteRole -> org_role -> None
    if role is None or perm not in ROLE_PERMS[role]:
        raise PermissionDenied(perm)
```

The permission matrix test keeps a literal copy of the table above and asserts `ROLE_PERMS` matches it, so doc and code can't drift silently.

## Auth, invitations and API tokens

Humans authenticate with sessions; client sites authenticate with API tokens. The two never mix.

**Human login**

- `django-allauth` headless: email + password, plus login-by-code.
- Session cookie, `HttpOnly`, `Secure`, `SameSite=Lax`, CSRF on unsafe methods. Admin and API share a parent domain (`admin.<NOVA_BASE_DOMAIN>`, `api.<NOVA_BASE_DOMAIN>`), so no tokens live in browser storage.
- TOTP for owners is optional in Phase 1 and required before Nova becomes a product.

**Invitation flow**

1. An owner or admin invites an email with an `org_role` and/or site roles. Nova stores a hashed token and emails a link via Resend.
2. The invitee opens the link. New email: set name and password. Existing account: log in.
3. On accept, Nova checks hash, expiry, revocation and that the logged-in email matches, then creates or updates the `Membership`, creates `SiteRole` rows and marks the invite accepted, in one transaction.
4. Re-inviting the same email revokes the open invite. Every step is audited.

**API tokens**

- Format `nova_dlv_{prefix}_{secret}` (delivery) or `nova_prv_{prefix}_{secret}` (preview). Prefix stored in clear for lookup; secret stored only as SHA-256.
- Delivery tokens read published data; preview tokens also see drafts. Both are server-side only.
- One site per token. Revocation is immediate; `last_used_at` updates at most once a minute. Rate-limited per token.

**API surfaces**

| Surface | Base path | Auth | Purpose |
| --- | --- | --- | --- |
| Management | `/api/manage/orgs/{org}/…` | Session | Admin UI and internal tools; all writes |
| Delivery | `/api/v1/…` | Bearer token | Client sites read published data (public form submission later) |
| Auth | `/_allauth/browser/v1/…` | Session | Login, logout, password reset, login codes |

Cross-tenant management requests return 404, not 403, so tenants can't probe for each other.

## Code layout

```
apps/api/
  nova/        settings/{base,dev,test,prod}.py, urls, asgi, wsgi, celery
  core/        models/, services/, selectors/, api/, permissions.py, audit.py, crypto.py, tests/
  payments/    models.py, providers/{base,paystack}.py, services.py, api/, tests/
```

Each app: `models` (data), `services` (all writes + permission checks + audit), `selectors` (org-scoped reads), `api/` (thin DRF views and serializers), `tests/`.

| Concern | Choice |
| --- | --- |
| Runtime | Python 3.13+, Django 5.2 LTS, DRF |
| API schema | `drf-spectacular` → `openapi-typescript` into `packages/api-types` |
| Auth | `django-allauth` headless |
| Database | PostgreSQL 17 |
| Jobs | Redis + Celery |
| Media | Cloudflare R2 via S3 API, presigned browser uploads |
| Email | Resend |
| Secret encryption | Fernet via `MultiFernet`, keys from env |
| Hosting | Single VPS, Docker Compose, Caddy |

## Testing strategy

- **Tenant isolation suite:** two orgs with identical data; every management endpoint is hit by a member of A using B's IDs and must return 404 with no B data. Unregistered endpoints fail the suite.
- **Permission matrix test:** every `(Role, Perm)` pair checked against the table above.
- **Service tests over view tests:** logic lives in services; API tests check wiring, status codes and serialization.
- **Secret hygiene test:** raw payment secrets and API tokens never appear in responses, logs or audit metadata.

## Resolved decisions

- **Domain:** its own production domain (name TBD), configured via `NOVA_BASE_DOMAIN`.
- **Hosting:** single VPS with Docker Compose and nightly `pg_dump` to R2.
- **Per-site roles:** `Membership.org_role` plus `SiteRole` overrides.
- **First tenant:** Culture & Interest (listening parties and screenings).