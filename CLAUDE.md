# Nova

Nova is a multi-tenant content and engagement platform built by n42sys. Client staff use it to run blogs, edit website content, build and share forms, and host events with RSVPs, tickets and check-in. It starts as internal tooling for n42sys clients and becomes a public product later, so tenant boundaries are built to SaaS standard from day one.

**First tenant:** Culture & Interest, a collective that hosts listening parties and screenings. It is events-first, so after Phase 1 the build order is: forms → events with free RSVP → paid tickets → blog and page sections.

**Current phase:** Phase 1 (core). Work from `docs/design/phase-1-plan.md`, one task at a time, in order.

## Repo layout

```
apps/api/        Django + DRF backend (uv-managed)
  nova/          settings, urls, asgi, celery
  core/          orgs, sites, users, memberships, site roles, invites, tokens, audit, media
  payments/      PaymentAccount + provider interface (no checkout until Phase 4)
apps/admin/      Next.js App Router studio for client staff
apps/public/     Next.js hosted form/event/ticket pages (empty until Phase 2)
packages/api-types/  TS types generated from the OpenAPI schema
docs/design/     design docs and phase plans
```

## Commands

Run Python commands from `apps/api/`.

```bash
docker compose up -d                      # Postgres 17 + Redis (repo root)
uv sync                                   # install Python deps
uv run python manage.py migrate
uv run python manage.py runserver
uv run python manage.py bootstrap_org --name "Culture & Interest" --slug culture-interest \
    --owner-email <email> --site "Main:main"   # idempotent; --resend for a fresh link
uv run celery -A nova worker -l info
uv run celery -A nova beat -l info         # scheduled jobs (media cleanup)
uv run pytest                             # all tests
uv run pytest core/tests/test_isolation.py -x   # tenant isolation suite
uv run ruff check . --fix && uv run ruff format .
uv run python manage.py spectacular --file ../../packages/api-types/openapi.yaml
pnpm --filter api-types generate          # OpenAPI -> TS types
pnpm --filter admin dev
```

A task is not done until `ruff check`, `ruff format --check` and `pytest` all pass.

## Architecture rules (do not break without asking)

1. **Tenancy.** Every tenant-owned model inherits `core.models.TenantModel` (`organization` FK, guarded manager). App code queries with `Model.objects.for_org(org)`. `Model.unscoped` is only for migrations, management commands and Celery tasks that pass `org_id` explicitly, plus one approved request-path exception: `core/selectors/token_resolution.py`, which resolves secret tokens (invitation token hashes; API token prefixes from T8) to their object and its organization. No other request-handling module may use `.unscoped`; a test enforces this. Never query a tenant model without an org filter.
2. **Site-owned data** carries both `organization` and `site`. Validate in the service that `site.organization_id == organization_id`.
3. **Uniqueness is per tenant.** Use `UniqueConstraint(fields=["site", "slug"])`, never a global unique slug. Only `Organization.slug`, `User.email` and `Site.domain` are global.
4. **Layering.** All writes and permission checks live in `<app>/services.py`. All reads live in `<app>/selectors.py` and take the org (and site where relevant) as arguments. DRF views and serializers stay thin: parse, call a service or selector, serialize. No business logic in views, serializers, signals or `save()` overrides.
5. **Permissions.** Every service that acts on behalf of a user calls `require(ctx, Perm.X, site)` first. Roles resolve per site: `SiteRole` for that site → `Membership.org_role` → no access. Org-only permissions always use `org_role`. `ROLE_PERMS` in `core/permissions.py` is the single source of truth.
6. **Cross-tenant requests return 404**, never 403, so tenants cannot probe for each other.
7. **Audit.** Every service that changes data writes an `AuditLog` entry via `core.audit.audit(ctx, action, target, metadata)`, called inside the same `transaction.atomic()` block as the write it records, so a change and its audit entry commit or roll back together. `AuditLog` is append-only.
8. **Secrets.** Payment secret keys are Fernet-encrypted via `core.crypto` (`MultiFernet`, keys from env). API tokens and invite tokens are stored only as SHA-256 hashes. Raw secrets never appear in API responses, logs, exceptions or audit metadata.
9. **IDs and time.** Primary keys are UUIDv7 (`core.fields.uuid7`). Store all datetimes in UTC; convert with `Site.timezone` (default `Africa/Nairobi`) only at the edges.
10. **Two auth worlds.** Humans use allauth headless sessions (cookie, CSRF). Client sites use bearer API tokens scoped to one site. A view accepts one or the other, never both.
11. **Modules are isolated.** Apps depend on `core`, never on each other's models. Cross-module calls go through the other app's `services.py` / `selectors.py`.
12. **Config, not constants.** Domains, branding and provider keys come from settings/env (`NOVA_BASE_DOMAIN`, etc.). No hard-coded `n42sys` or domain strings.

## Conventions

- Python 3.13+, Django 5.2 LTS, DRF, type hints on all service and selector signatures.
- Services take a `RequestContext` (user, membership, org, ip, actor type) as the first argument.
- Raise domain exceptions from `core.exceptions`; a DRF exception handler maps them to responses.
- Name services as verbs (`invite_member`, `revoke_api_token`), selectors as nouns or `get_`/`list_` (`list_sites`).
- Every model change ships with a migration. Never edit an applied migration; add a new one.
- Tests use `pytest-django` + `factory-boy`. Factories live in `<app>/tests/factories.py`.
- Every new management endpoint must be registered in the tenant isolation suite (`core/tests/test_isolation.py`).
- Every new `Perm` must be added to `ROLE_PERMS`; the matrix test fails otherwise.
- Use `drf-spectacular` `@extend_schema` on every view so generated TS types stay accurate.

## How to work in this repo

- Before starting a task, read its section in `docs/design/phase-1-plan.md` and the matching section of the design doc, `docs/design/phase-1-core-design.md`.
- Write the tests named in the task's acceptance criteria alongside the code, not after.
- Keep changes scoped to the current task. If you spot an unrelated problem, note it at the end of your summary instead of fixing it.
- Ask before adding a dependency not listed in the plan, changing an architecture rule, or changing a migration that has already been applied.
- When a task is done: run the checks above, tick its box in the plan, and summarise what changed and anything left open.

## Do not

- Use `Model.objects.all()` or `.unscoped` in request-handling code (the only exception is `core/selectors/token_resolution.py`).
- Put tokens in browser storage or return secrets from any endpoint.
- Use Django signals for business logic.
- Enable `django.contrib.admin` for Nova data. `User` has no `PermissionsMixin`; ops tooling goes through audited services.
- Add GraphQL, multi-database, schema-per-tenant or Postgres RLS in Phase 1.
- Build checkout, forms, events or blog features before their phase.