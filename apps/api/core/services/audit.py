from core.context import RequestContext
from core.permissions import Perm, require
from core.selectors.audit import DEFAULT_LIMIT, AuditLogPage, list_audit_log


def view_audit_log(
    ctx: RequestContext, *, cursor: str | None = None, limit: int = DEFAULT_LIMIT
) -> AuditLogPage:
    """Audit log page for the caller, who needs AUDIT_VIEW."""
    require(ctx, Perm.AUDIT_VIEW)
    return list_audit_log(ctx.organization, cursor=cursor, limit=limit)
