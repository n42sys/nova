import re

from django.db import IntegrityError, transaction
from django.utils import timezone

from core import crypto
from core.audit import audit
from core.context import RequestContext
from core.exceptions import Conflict, ProviderUnavailable, ValidationFailed
from core.permissions import Perm, require
from payments.models import PaymentAccount
from payments.providers import get_provider
from payments.providers.base import CredentialsRejected
from payments.selectors import list_payment_accounts

# Expected key shapes per provider. Paystack keys are pk_/sk_ + test|live; both must match.
_KEY_PATTERNS = {
    PaymentAccount.Provider.PAYSTACK: (
        re.compile(r"pk_(test|live)_[A-Za-z0-9]{20,}"),
        re.compile(r"sk_(test|live)_[A-Za-z0-9]{20,}"),
    ),
}
_HINT_PREFIX = re.compile(r"[a-z]{2}_(?:test|live)_")
SUPPORTED_PROVIDERS = frozenset({PaymentAccount.Provider.PAYSTACK})


def secret_hint(secret: str) -> str:
    """A masked hint such as "sk_live_…a1b2": the provider's key prefix, if it has one, and
    the last four characters. Nothing else of the secret is kept in clear."""
    prefix = match.group(0) if (match := _HINT_PREFIX.match(secret)) else ""
    return f"{prefix}…{secret[-4:]}"


def _require_supported(provider: str) -> None:
    if provider not in SUPPORTED_PROVIDERS:
        raise ValidationFailed(
            "This payment provider is not supported yet.", details={"provider": [provider]}
        )


def _validate_keys(provider: str, public_key: str, secret_key: str) -> None:
    """Raise ValidationFailed without ever echoing the secret."""
    _require_supported(provider)
    public_pattern, secret_pattern = _KEY_PATTERNS[provider]
    public_match = public_pattern.fullmatch(public_key)
    secret_match = secret_pattern.fullmatch(secret_key)
    if public_match is None:
        raise ValidationFailed(
            "Public key has the wrong format.", details={"public_key": ["invalid"]}
        )
    if secret_match is None:
        raise ValidationFailed(
            "Secret key has the wrong format.", details={"secret_key": ["invalid"]}
        )
    if public_match.group(1) != secret_match.group(1):
        raise ValidationFailed(
            "Public and secret keys must both be test keys or both be live keys.",
            details={"secret_key": ["mode_mismatch"]},
        )


def _metadata(account: PaymentAccount) -> dict:
    # Keys named like *secret* are stripped by audit(); the hint goes in as key_hint.
    return {
        "provider": account.provider,
        "public_key": account.public_key,
        "key_hint": account.secret_key_hint,
        "status": account.status,
    }


def create_payment_account(
    ctx: RequestContext, *, provider: str, public_key: str, secret_key: str
) -> PaymentAccount:
    require(ctx, Perm.PAYMENTS_MANAGE)
    provider = PaymentAccount.Provider(provider)
    public_key, secret_key = public_key.strip(), secret_key.strip()
    _validate_keys(provider, public_key, secret_key)
    if PaymentAccount.objects.for_org(ctx.organization).filter(provider=provider).exists():
        raise Conflict("This organization already has an account with that provider.")
    account = PaymentAccount(
        organization=ctx.organization,
        provider=provider,
        public_key=public_key,
        secret_key_encrypted=crypto.encrypt(secret_key),
        secret_key_hint=secret_hint(secret_key),
    )
    try:
        with transaction.atomic():
            account.save(force_insert=True)
            audit(ctx, "payment_account.create", account, _metadata(account))
    except IntegrityError as exc:
        raise Conflict("This organization already has an account with that provider.") from exc
    return account


def replace_payment_account_keys(
    ctx: RequestContext, account: PaymentAccount, *, public_key: str, secret_key: str
) -> PaymentAccount:
    """Swap both keys. The account needs verifying again (and is re-enabled if disabled)."""
    require(ctx, Perm.PAYMENTS_MANAGE)
    public_key, secret_key = public_key.strip(), secret_key.strip()
    _validate_keys(account.provider, public_key, secret_key)
    with transaction.atomic():
        account = (
            PaymentAccount.objects.for_org(ctx.organization).select_for_update().get(id=account.id)
        )
        previous_hint = account.secret_key_hint
        account.public_key = public_key
        account.secret_key_encrypted = crypto.encrypt(secret_key)
        account.secret_key_hint = secret_hint(secret_key)
        account.status = PaymentAccount.Status.PENDING
        account.verified_at = None
        account.save()
        audit(
            ctx,
            "payment_account.replace_keys",
            account,
            {**_metadata(account), "previous_key_hint": previous_hint},
        )
    return account


def verify_payment_account(ctx: RequestContext, account: PaymentAccount) -> PaymentAccount:
    """Ask the provider whether the keys work; mark the account verified if they do."""
    require(ctx, Perm.PAYMENTS_MANAGE)
    if account.status == PaymentAccount.Status.DISABLED:
        raise Conflict("This account is disabled. Replace its keys to enable it again.")
    provider = get_provider(account.provider)
    if provider is None:
        raise Conflict("Verification is not available for this provider yet.")
    try:
        provider.verify_credentials(account)
    except CredentialsRejected:
        with transaction.atomic():
            account.status = PaymentAccount.Status.PENDING
            account.verified_at = None
            account.save(update_fields=["status", "verified_at", "updated_at"])
            audit(ctx, "payment_account.verify_failed", account, _metadata(account))
        raise ValidationFailed(
            "The provider rejected these keys.", details={"provider": account.provider}
        ) from None
    except ProviderUnavailable:
        # Re-raised with a fixed message: a provider's own text never reaches the client.
        raise ProviderUnavailable(details={"provider": account.provider}) from None
    with transaction.atomic():
        account.status = PaymentAccount.Status.VERIFIED
        account.verified_at = timezone.now()
        account.save(update_fields=["status", "verified_at", "updated_at"])
        audit(ctx, "payment_account.verify", account, _metadata(account))
    return account


def disable_payment_account(ctx: RequestContext, account: PaymentAccount) -> PaymentAccount:
    """Soft delete: keep the row (and audit history); disabling twice is a no-op."""
    require(ctx, Perm.PAYMENTS_MANAGE)
    if account.status == PaymentAccount.Status.DISABLED:
        return account
    with transaction.atomic():
        account.status = PaymentAccount.Status.DISABLED
        account.save(update_fields=["status", "updated_at"])
        audit(ctx, "payment_account.disable", account, _metadata(account))
    return account


def view_payment_accounts(ctx: RequestContext) -> list[PaymentAccount]:
    require(ctx, Perm.PAYMENTS_MANAGE)
    return list_payment_accounts(ctx.organization)
