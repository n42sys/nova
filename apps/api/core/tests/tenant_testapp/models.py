from django.db import models

from core.models import TenantModel


class Widget(TenantModel):
    # No DB-level FK: its table is created outside migrations, and a constraint would stop
    # transactional tests from TRUNCATE-ing core_organization between tests.
    organization = models.ForeignKey(
        "core.Organization", on_delete=models.PROTECT, db_constraint=False
    )
    name = models.CharField(max_length=50)

    class Meta(TenantModel.Meta):
        # Django syncs migration-less apps *before* applying migrations, so this table can't be
        # created then (its FK targets core_organization). the root conftest.py creates it after.
        managed = False
