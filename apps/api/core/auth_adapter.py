from allauth.account.adapter import DefaultAccountAdapter


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request) -> bool:
        # No self-serve sign-up in Phase 1. T7 opens sign-up for emails with an open invitation.
        return False
