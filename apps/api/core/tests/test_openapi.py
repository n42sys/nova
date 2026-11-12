from pathlib import Path

from django.conf import settings
from django.core.management import call_command


def test_openapi_schema_validates_without_warnings(tmp_path):
    """T11: `spectacular --validate --fail-on-warn` must stay green for every task."""
    call_command(
        "spectacular", "--validate", "--fail-on-warn", "--file", str(tmp_path / "openapi.yaml")
    )

    schema = (tmp_path / "openapi.yaml").read_text()
    assert "sessionAuth" in schema
    assert "RoleEnum" in schema and "SiteStatusEnum" in schema


def test_committed_schema_is_up_to_date(tmp_path):
    """packages/api-types/openapi.yaml must match the API, so the TS types cannot drift.

    Fix with: pnpm --filter api-types schema && pnpm --filter api-types generate
    """
    committed = Path(settings.BASE_DIR).parent.parent / "packages/api-types/openapi.yaml"
    call_command("spectacular", "--file", str(tmp_path / "openapi.yaml"))

    assert committed.read_text() == (tmp_path / "openapi.yaml").read_text(), (
        "openapi.yaml is stale: run `pnpm --filter api-types schema` and `generate`"
    )
