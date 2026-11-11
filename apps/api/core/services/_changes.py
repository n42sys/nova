from typing import Any

from django.db import models


def apply_changes(instance: models.Model, changes: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Set changed fields on `instance`; return {field: {"from", "to"}} for the audit log."""
    diff = {}
    for name, value in changes.items():
        old = getattr(instance, name)
        if old != value:
            setattr(instance, name, value)
            diff[name] = {"from": old, "to": value}
    return diff
