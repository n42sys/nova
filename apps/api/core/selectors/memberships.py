from core.models import Membership, Organization, User


def get_membership(org: Organization, user: User) -> Membership | None:
    """The user's membership in `org`, with site roles prefetched for `effective_role`."""
    return (
        Membership.objects.for_org(org)
        .filter(user=user)
        .select_related("user")
        .prefetch_related("site_roles")
        .first()
    )


def list_memberships_for_user(user: User) -> list[Membership]:
    """All of the user's own memberships, suspended orgs included, with site roles and sites.

    Org endpoints still 404 for suspended orgs; this list only shows that they exist.
    """
    return list(
        user.memberships.select_related("organization")
        .prefetch_related("site_roles__site")
        .order_by("organization__name")
    )
