from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.utils import timezone
from rest_framework import authentication, exceptions, permissions, throttling

from core.models import ApiToken
from core.selectors.token_resolution import resolve_api_token


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


class ApiTokenAuthentication(authentication.BaseAuthentication):
    """`Authorization: Bearer nova_dlv_…` / `nova_prv_…`. Delivery views only.

    Authenticates as (AnonymousUser, ApiToken): a token is never a person. Any presented
    token that does not resolve (malformed, unknown, wrong kind, revoked, archived site,
    suspended org) is a 401 with the same body.
    """

    keyword = "Bearer"
    last_used_interval = 60  # seconds between last_used_at writes per token

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode("latin-1")
        if not header:
            return None
        keyword, _, raw = header.partition(" ")
        if keyword != self.keyword or not raw.strip():
            raise exceptions.AuthenticationFailed("Invalid API token.")
        token = resolve_api_token(raw.strip())
        if token is None:
            raise exceptions.AuthenticationFailed("Invalid API token.")
        self._touch(token)
        return AnonymousUser(), token

    def authenticate_header(self, request) -> str:
        return 'Bearer realm="api"'

    def _touch(self, token: ApiToken) -> None:
        """Record use at most once per interval per token (cache.add is atomic)."""
        if cache.add(f"api-token-used:{token.id}", 1, self.last_used_interval):
            now = timezone.now()
            ApiToken.objects.for_org(token.organization_id).filter(id=token.id).update(
                last_used_at=now
            )
            token.last_used_at = now


class HasApiToken(permissions.BasePermission):
    def has_permission(self, request, view) -> bool:
        return isinstance(request.auth, ApiToken)


class ApiTokenRateThrottle(throttling.SimpleRateThrottle):
    """Per-token rate limit keyed by the token's prefix (NOVA_API_TOKEN_RATE, default 600/min)."""

    scope = "api_token"

    def get_rate(self) -> str:
        return settings.NOVA_API_TOKEN_RATE

    def get_cache_key(self, request, view) -> str | None:
        if not isinstance(request.auth, ApiToken):
            return None
        return self.cache_format % {"scope": self.scope, "ident": request.auth.prefix}
