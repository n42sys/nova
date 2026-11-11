import ipaddress

from django.conf import settings
from django.http import HttpRequest


def get_client_ip(request: HttpRequest) -> str | None:
    """Client IP, reading X-Forwarded-For only as far as NOVA_TRUSTED_PROXY_COUNT allows."""
    candidate = request.META.get("REMOTE_ADDR")
    proxies = settings.NOVA_TRUSTED_PROXY_COUNT
    if proxies:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if len(hops) >= proxies:
            candidate = hops[-proxies]
    try:
        return str(ipaddress.ip_address(candidate)) if candidate else None
    except ValueError:
        return None
