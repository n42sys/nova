"""Fixtures for every app's tests (core and payments)."""

import boto3
import pytest
from allauth.account.models import EmailAddress
from django.conf import settings
from django.db import connection
from moto import mock_aws

from core import storage
from core.tests.factories import UserFactory
from core.tests.support import PASSWORD, BrowserClient
from core.tests.tenant_testapp.models import Widget


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """Create the test-only tenant_testapp table once migrations have run."""
    with django_db_blocker.unblock(), connection.schema_editor() as editor:
        editor.create_model(Widget)


@pytest.fixture
def browser():
    return BrowserClient()


@pytest.fixture
def verified_user(db):
    user = UserFactory(password=PASSWORD)
    EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
    return user


@pytest.fixture(scope="session")
def _moto_s3():
    """One moto in-memory S3 (standing in for R2) for the session, with the media bucket."""
    with mock_aws():
        client = boto3.client(
            "s3",
            region_name=settings.R2_REGION,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        )
        client.create_bucket(Bucket=settings.R2_BUCKET)
        storage._client.cache_clear()  # build the app's client inside the mock
        yield client
        storage._client.cache_clear()


@pytest.fixture
def s3(_moto_s3):
    """Request this to use object storage; the bucket is emptied after each test."""
    yield _moto_s3
    listing = _moto_s3.list_objects_v2(Bucket=settings.R2_BUCKET).get("Contents", [])
    if listing:
        _moto_s3.delete_objects(
            Bucket=settings.R2_BUCKET,
            Delete={"Objects": [{"Key": item["Key"]} for item in listing]},
        )
