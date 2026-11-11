# Nova

Nova is a multi-tenant content and engagement platform. Client staff use it to run blogs, edit website content, build and share forms, and host events with RSVPs, tickets and check-in.

It starts as internal tooling for n42sys clients and becomes a public product later, so tenant boundaries are built to SaaS standard from day one. The first tenant is **Culture & Interest**, a collective that hosts listening parties and screenings.

## Concepts

- **Organization**: a client, and the tenant boundary. Every tenant-owned row carries an `organization_id`.
- **Site**: a website or property owned by an organization. One organization can have several.
- **User**: a person. Users are global; one person can work across several organizations.
- **Membership**: links a user to an organization, with an optional organization-wide role.
- **Site role**: overrides the organization role on one site, e.g. `editor` on the main site and `event_staff` on the events site.
- **Roles**: `owner` ⊃ `admin` ⊃ `editor`, plus `event_staff` as a narrow side role. Permissions are checked in the service layer.

## Roadmap

| Phase | Scope |
| --- | --- |
| 1 — Core (current) | Organizations, sites, members and roles, invitations, login, audit log, API tokens, media, payment accounts, management API, thin admin, VPS deployment |
| 2 | Forms |
| 3 | Events with free RSVP |
| 4 | Paid tickets (each organization's own Paystack account), QR tickets, check-in |
| 5 | Blog and page sections |

## Stack

| Area | Choice |
| --- | --- |
| Backend | Python 3.13, Django 5.2 LTS, Django REST Framework |
| API schema | drf-spectacular (OpenAPI) → openapi-typescript types in `packages/api-types` |
| Auth | django-allauth headless (session cookies) for people; scoped bearer API tokens for client sites |
| Database | PostgreSQL 17, one shared schema with an `organization_id` on every tenant row |
| Background jobs | Celery with Redis |
| Media storage | Cloudflare R2 through the S3 API (boto3, django-storages), presigned browser uploads |
| Email | Resend |
| Secrets | Fernet (`MultiFernet`, keys from env) for payment keys; SHA-256 hashes for tokens |
| Payments | Paystack first, one account per organization; Nova never holds funds |
| Frontend | Next.js App Router, TypeScript, Tailwind (`apps/admin`, `apps/public`) |
| Tooling | uv (Python), pnpm workspace (JS), ruff, pytest + pytest-django + factory-boy |
| Hosting | Single VPS, Docker Compose, Caddy (automatic HTTPS), nightly `pg_dump` to R2 |

## Repository layout

```text
apps/api/            Django + DRF backend (uv project)
  nova/              settings (base/dev/test/prod), urls, asgi/wsgi, celery
  core/              organizations, sites, users, memberships, roles, permissions, audit, ...
  payments/          payment accounts and provider interface
apps/admin/          Next.js studio for client staff (Phase 1, T12)
apps/public/         Next.js hosted form/event/ticket pages (Phase 2+)
packages/api-types/  TypeScript types generated from the OpenAPI schema (Phase 1, T11)
docs/design/         design docs and phase plans
```

The admin, public and api-types packages are added as their tasks come up; see the plan.

## Getting started

Requirements: Docker, [uv](https://docs.astral.sh/uv/), and (for the frontends) Node.js with pnpm.

```bash
docker compose up -d          # Postgres 17 on :55432, Redis 7 on :56379

cd apps/api
cp .env.example .env          # optional; dev settings have local defaults
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
uv run celery -A nova worker -l info
```

Checks (all must pass before a task is done):

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest
```

Host ports can be changed with `NOVA_PG_PORT` and `NOVA_REDIS_PORT`; update `DATABASE_URL` and `REDIS_URL` to match.

## How the backend is organised

- **Tenancy.** Tenant models inherit `core.models.TenantModel`. Their `objects` manager refuses unscoped queries; code calls `Model.objects.for_org(org)`.
- **Layering.** Writes and permission checks live in services, reads in selectors. Views and serializers stay thin.
- **Permissions.** Services call `require(ctx, Perm.X, site)`. `ROLE_PERMS` in `core/permissions.py` is the single source of truth, and a matrix test checks it against the design doc.
- **Audit.** Every data change writes an append-only `AuditLog` entry.
- **Isolation.** Cross-tenant requests return 404, never 403. A test suite hits every management endpoint across tenants.

## Further reading

- [`docs/design/phase-1-core-design.md`](docs/design/phase-1-core-design.md): data model, roles, auth and the reasoning behind them
- [`docs/design/phase-1-plan.md`](docs/design/phase-1-plan.md): Phase 1 tasks and their acceptance criteria
- [`CLAUDE.md`](CLAUDE.md): architecture rules and conventions for contributors
