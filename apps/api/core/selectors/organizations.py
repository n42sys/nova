from core.models import Organization


def get_active_organization(slug: str) -> Organization | None:
    """Active organization by slug. Suspended organizations are treated as not found."""
    return Organization.objects.filter(slug=slug, status=Organization.Status.ACTIVE).first()
