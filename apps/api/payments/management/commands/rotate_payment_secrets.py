import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core import crypto
from payments.models import PaymentAccount

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Re-encrypt every payment secret with the newest key in NOVA_FERNET_KEYS. "
        "Prepend the new key, run this, then remove the old key."
    )

    def handle(self, *args, **options) -> None:
        # A management command may use `unscoped` (rule 1): it works across organizations.
        rotated = 0
        with transaction.atomic():
            accounts = PaymentAccount.unscoped.select_for_update().order_by("id")
            for account in accounts:
                try:
                    account.secret_key_encrypted = crypto.rotate(account.secret_key_encrypted)
                except crypto.DecryptionError as exc:
                    raise CommandError(
                        f"Payment account {account.id} could not be decrypted with any configured "
                        "key; nothing was changed."
                    ) from exc
                account.save(update_fields=["secret_key_encrypted", "updated_at"])
                rotated += 1
        logger.info("rotate_payment_secrets re-encrypted %d payment secret(s)", rotated)
        self.stdout.write(self.style.SUCCESS(f"Re-encrypted {rotated} payment secret(s)."))
