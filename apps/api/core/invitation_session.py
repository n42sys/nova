"""Remember, in the visitor's session, an invitation they claimed with its raw token.

`POST /api/manage/invitations/{token}/claim/` calls `remember_invitation`. The allauth adapter
then opens sign-up only for that session, only for the invited email, and treats that email
as verified: holding the emailed token proves the address.
"""

import uuid

from django.http import HttpRequest

from core.models import Invitation
from core.selectors.invitations import get_open_invitation

SESSION_KEY = "nova_pending_invitation"


def remember_invitation(request: HttpRequest, invitation: Invitation) -> None:
    request.session[SESSION_KEY] = {
        "org_id": str(invitation.organization_id),
        "invitation_id": str(invitation.id),
    }


def get_pending_invitation(request: HttpRequest | None) -> Invitation | None:
    """The session's claimed invitation, if it is still open; otherwise None."""
    if request is None or not hasattr(request, "session"):
        return None
    pending = request.session.get(SESSION_KEY)
    if not pending:
        return None
    try:
        org_id = uuid.UUID(pending["org_id"])
        invitation_id = uuid.UUID(pending["invitation_id"])
    except (KeyError, TypeError, ValueError):
        return None
    return get_open_invitation(org_id, invitation_id)


def forget_invitation(request: HttpRequest) -> None:
    request.session.pop(SESSION_KEY, None)
