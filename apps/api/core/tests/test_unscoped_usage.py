"""Rule 1: `.unscoped` is banned from request-handling code except token resolution."""

import re
from pathlib import Path

from django.conf import settings

ALLOWED = {Path("core/selectors/token_resolution.py")}
EXCLUDED_PARTS = {"tests", "migrations", "management", ".venv"}
EXCLUDED_NAMES = {"tasks.py"}  # Celery tasks pass org_id explicitly
PATTERN = re.compile(r"\w\.unscoped\b")  # attribute access, e.g. `Invitation.unscoped`


def test_unscoped_is_used_only_in_token_resolution():
    root = Path(settings.BASE_DIR)
    offenders = []
    for path in root.rglob("*.py"):
        relative = path.relative_to(root)
        if EXCLUDED_PARTS.intersection(relative.parts) or relative.name in EXCLUDED_NAMES:
            continue
        if relative in ALLOWED:
            continue
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if PATTERN.search(line):
                offenders.append(f"{relative}:{number}: {line.strip()}")

    assert offenders == []


def test_token_resolution_module_exists_and_uses_unscoped():
    source = (Path(settings.BASE_DIR) / "core/selectors/token_resolution.py").read_text()

    assert PATTERN.search(source)
