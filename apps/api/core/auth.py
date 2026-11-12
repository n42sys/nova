from rest_framework import authentication


class SessionAuthentication(authentication.SessionAuthentication):
    """DRF session auth that answers unauthenticated requests with 401, not 403.

    DRF only sends 401 when the authenticator provides a WWW-Authenticate value; the stock
    SessionAuthentication provides none, so DRF downgrades to 403.
    """

    def authenticate_header(self, request) -> str:
        return 'Session realm="api"'


def enforce_csrf(request) -> None:
    """Apply Django's CSRF check even for anonymous requests (DRF skips it for them)."""
    SessionAuthentication().enforce_csrf(request)
