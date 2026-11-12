import uuid

from core.models import ApiToken, Organization, Site


def list_api_tokens(org: Organization, site: Site) -> list[ApiToken]:
    return list(ApiToken.objects.for_org(org).filter(site=site).order_by("-created_at", "-id"))


def get_api_token(org: Organization, site: Site, token_id: uuid.UUID) -> ApiToken | None:
    return ApiToken.objects.for_org(org).filter(site=site, id=token_id).first()
