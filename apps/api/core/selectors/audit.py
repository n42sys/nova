from core.models import AuditLog, Organization
from core.pagination import DEFAULT_LIMIT, MAX_LIMIT, Page, paginate

AuditLogPage = Page

__all__ = ["DEFAULT_LIMIT", "MAX_LIMIT", "AuditLogPage", "list_audit_log"]


def list_audit_log(
    org: Organization, *, cursor: str | None = None, limit: int = DEFAULT_LIMIT
) -> Page:
    """Newest-first audit entries for `org`, cursor-paginated on (created_at, id)."""
    queryset = AuditLog.objects.for_org(org).select_related("actor_user")
    return paginate(queryset, cursor=cursor, limit=limit)
