from functools import cache
from typing import Any
from zoneinfo import available_timezones

from django.db import IntegrityError, transaction

from core.audit import audit
from core.context import RequestContext
from core.exceptions import Conflict, ValidationFailed
from core.models import Site
from core.permissions import Perm, require
from core.services._changes import apply_changes


@cache
def _timezones() -> frozenset[str]:
    return frozenset(available_timezones())


def _validate_timezone(timezone: str) -> None:
    if timezone not in _timezones():
        raise ValidationFailed("Unknown timezone.", details={"timezone": [timezone]})


def _check_slug_free(ctx: RequestContext, slug: str, *, exclude: Site | None = None) -> None:
    sites = Site.objects.for_org(ctx.organization).filter(slug=slug)
    if exclude is not None:
        sites = sites.exclude(id=exclude.id)
    if sites.exists():
        raise Conflict("A site with this slug already exists.", details={"slug": [slug]})


def create_site(
    ctx: RequestContext,
    *,
    name: str,
    slug: str,
    timezone: str | None = None,
    default_locale: str | None = None,
    settings: dict[str, Any] | None = None,
) -> Site:
    require(ctx, Perm.SITES_MANAGE)
    site = Site(organization=ctx.organization, name=name, slug=slug)
    if timezone is not None:
        _validate_timezone(timezone)
        site.timezone = timezone
    if default_locale is not None:
        site.default_locale = default_locale
    if settings is not None:
        site.settings = settings
    _check_slug_free(ctx, slug)
    try:
        with transaction.atomic():
            site.save(force_insert=True)
            audit(ctx, "site.create", site, {"name": name, "slug": slug})
    except IntegrityError as exc:  # lost a race on (organization, slug)
        raise Conflict("A site with this slug already exists.", details={"slug": [slug]}) from exc
    return site


def update_site(ctx: RequestContext, site: Site, **changes: Any) -> Site:
    """Update name, slug, timezone, default_locale and/or settings."""
    require(ctx, Perm.SITES_MANAGE, site)
    allowed = {"name", "slug", "timezone", "default_locale", "settings"}
    if unknown := set(changes) - allowed:
        raise ValidationFailed("Unknown fields.", details={"fields": sorted(unknown)})
    if "timezone" in changes:
        _validate_timezone(changes["timezone"])
    if "slug" in changes:
        _check_slug_free(ctx, changes["slug"], exclude=site)
    try:
        with transaction.atomic():
            diff = apply_changes(site, changes)
            if diff:
                site.save(update_fields=[*diff, "updated_at"])
                audit(ctx, "site.update", site, {"changes": diff})
    except IntegrityError as exc:
        raise Conflict(
            "A site with this slug already exists.", details={"slug": [site.slug]}
        ) from exc
    return site


def archive_site(ctx: RequestContext, site: Site) -> Site:
    """Soft delete: Phase 1 never removes sites. Archiving an archived site is a no-op."""
    require(ctx, Perm.SITES_MANAGE, site)
    if site.status == Site.Status.ARCHIVED:
        return site
    with transaction.atomic():
        site.status = Site.Status.ARCHIVED
        site.save(update_fields=["status", "updated_at"])
        audit(ctx, "site.archive", site, {"slug": site.slug})
    return site
