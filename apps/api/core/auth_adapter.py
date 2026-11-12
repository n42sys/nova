from allauth.account.adapter import DefaultAccountAdapter
from django import forms

from core.invitation_session import get_pending_invitation


class AccountAdapter(DefaultAccountAdapter):
    """No self-serve sign-up. Only a session that claimed a valid invitation may sign up,
    only with the invited email, and only that email counts as verified."""

    def is_open_for_signup(self, request) -> bool:
        return get_pending_invitation(request) is not None

    def clean_email(self, email: str) -> str:
        email = super().clean_email(email)
        request = self.request
        if request is None or request.user.is_authenticated:
            return email  # not a sign-up (e.g. adding an address to an existing account)
        invitation = get_pending_invitation(request)
        if invitation is not None and email.strip().lower() != invitation.email:
            raise forms.ValidationError(
                "Sign up with the email address the invitation was sent to."
            )
        return email

    def is_email_verified(self, request, email: str) -> bool:
        """Verified only if it equals the claimed, still-open invitation's normalised email."""
        invitation = get_pending_invitation(request)
        return invitation is not None and email.strip().lower() == invitation.email
