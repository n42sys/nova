import uuid

import uuid6
from django.db import models


def uuid7() -> uuid.UUID:
    """Time-ordered UUIDv7, used as the default for every primary key."""
    return uuid.UUID(int=uuid6.uuid7().int)


class LowercaseCharField(models.CharField):
    """CharField that stores and looks up values in lowercase (e.g. domain names)."""

    def to_python(self, value):
        value = super().to_python(value)
        return value.lower() if isinstance(value, str) else value

    def get_prep_value(self, value):
        return self.to_python(super().get_prep_value(value))

    def pre_save(self, model_instance, add):
        value = self.to_python(getattr(model_instance, self.attname))
        setattr(model_instance, self.attname, value)
        return value
