import re
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.core.validators import validate_email, validate_slug
from django.db import transaction
from django.utils import timezone

from core.audit import audit
from core.context import ActorType, RequestContext
from core.exceptions import ValidationFailed
from core.models import Invitation, Membership, Organization, Role, Site
from core.services.invitations import _issue_invitation, _reissue_invitation

DEFAULT_FEATURES = ("forms", "events", "content")
_FEATURE = re.compile(r"[a-z][a-z0-9_]*")


@dataclass
class BootstrapResult:
    organization: Organization
    org_created: bool
    name_differs: bool  # existing org kept its name; the requested one was ignored
    features_added: list[str] = field(default_factory=list)
    sites_created: list[str] = field(default_factory=list)
    sites_existing: list[str] = field(default_factory=list)
    # "owner_exists" | "invitation_sent" | "invitation_pending" | "invitation_resent"
    owner: str = ""


def _system_ctx(org: Organization) -> RequestContext:
    return RequestContext(
        user=None, membership=None, organization=org, ip=None, actor_type=ActorType.SYSTEM
    )


def _validate(
    name: str, slug: str, owner_email: str, sites: list[tuple[str, str]], features: list[str]
) -> None:
    errors: dict[str, list[str]] = {}
    if not name.strip():
        errors.setdefault("name", []).append("required")
    for label, value in [("slug", slug), *(("site", site_slug) for _, site_slug in sites)]:
        try:
            validate_slug(value)
        except ValidationError:
            errors.setdefault(label, []).append(f"invalid slug {value!r}")
    try:
        validate_email(owner_email)
    except ValidationError:
        errors.setdefault("owner_email", []).append("invalid")
    if not sites:
        errors.setdefault("site", []).append("at least one site is required")
    if any(not site_name.strip() for site_name, _ in sites):
        errors.setdefault("site", []).append("site names are required")
    if len({site_slug for _, site_slug in sites}) != len(sites):
        errors.setdefault("site", []).append("duplicate site slug")
    if bad := [feature for feature in features if not _FEATURE.fullmatch(feature)]:
        errors.setdefault("features", []).append(f"invalid: {', '.join(bad)}")
    if errors:
        raise ValidationFailed("Invalid bootstrap arguments.", details=errors)


def bootstrap_organization(
    *,
    name: str,
    slug: str,
    owner_email: str,
    sites: list[tuple[str, str]],
    features: list[str] = list(DEFAULT_FEATURES),  # noqa: B006  (never mutated)
    resend: bool = False,
) -> BootstrapResult:
    """Create (or complete) an organization, its sites and an owner invitation. Idempotent.

    Ops tooling, not a user action: it runs as the system actor, so there is no permission
    check, but every change is audited. Re-running never duplicates anything: the org and
    sites are matched by slug (existing ones are left as they are, apart from turning on
    requested features), and no invitation is sent if the owner is already a member or has
    an open owner invitation, unless `resend` asks for a fresh link.
    """
    owner_email = owner_email.strip().lower()
    _validate(name, slug, owner_email, sites, features)

    with transaction.atomic():
        org, org_created = Organization.objects.select_for_update().get_or_create(
            slug=slug,
            defaults={"name": name.strip(), "features": dict.fromkeys(features, True)},
        )
        ctx = _system_ctx(org)
        result = BootstrapResult(
            organization=org,
            org_created=org_created,
            name_differs=not org_created and org.name != name.strip(),
        )
        if org_created:
            audit(ctx, "org.bootstrap", org, {"name": org.name, "slug": slug, "features": features})
        else:
            result.features_added = [f for f in features if org.features.get(f) is not True]
            if result.features_added:
                previous = dict(org.features)
                org.features = {**org.features, **dict.fromkeys(result.features_added, True)}
                org.save(update_fields=["features", "updated_at"])
                audit(
                    ctx,
                    "org.update",
                    org,
                    {"changes": {"features": {"from": previous, "to": org.features}}},
                )

        for site_name, site_slug in sites:
            site, site_created = Site.objects.for_org(org).get_or_create(
                organization=org, slug=site_slug, defaults={"name": site_name.strip()}
            )
            if site_created:
                audit(ctx, "site.create", site, {"name": site.name, "slug": site.slug})
                result.sites_created.append(site_slug)
            else:
                result.sites_existing.append(site_slug)

        if (
            Membership.objects.for_org(org)
            .filter(org_role=Role.OWNER, user__email__iexact=owner_email)
            .exists()
        ):
            result.owner = "owner_exists"
        else:
            open_invitation = (
                Invitation.objects.for_org(org)
                .filter(
                    email=owner_email,
                    org_role=Role.OWNER,
                    accepted_at__isnull=True,
                    revoked_at__isnull=True,
                    expires_at__gt=timezone.now(),
                )
                .first()
            )
            if open_invitation is None:
                _issue_invitation(ctx, email=owner_email, org_role=Role.OWNER, site_roles=[])
                result.owner = "invitation_sent"
            elif resend:
                _reissue_invitation(ctx, open_invitation)
                result.owner = "invitation_resent"
            else:
                result.owner = "invitation_pending"
    return result
