from django.db import models

from core.models import TenantModel


class Widget(TenantModel):
    name = models.CharField(max_length=50)

    class Meta(TenantModel.Meta):
        # Django syncs migration-less apps *before* applying migrations, so this table can't be
        # created then (its FK targets core_organization). core/tests/conftest.py creates it after.
        managed = False
