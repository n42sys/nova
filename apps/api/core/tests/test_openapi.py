from django.core.management import call_command


def test_openapi_schema_validates_without_warnings(tmp_path):
    """T11: `spectacular --validate --fail-on-warn` must stay green for every task."""
    call_command(
        "spectacular", "--validate", "--fail-on-warn", "--file", str(tmp_path / "openapi.yaml")
    )

    schema = (tmp_path / "openapi.yaml").read_text()
    assert "sessionAuth" in schema
    assert "RoleEnum" in schema and "SiteStatusEnum" in schema
