import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

pytestmark = pytest.mark.django_db

User = get_user_model()


def test_create_user_with_email():
    user = User.objects.create_user(email="ada@example.com", password="s3cret-pass")

    assert user.email == "ada@example.com"
    assert user.id.version == 7
    assert user.check_password("s3cret-pass")
    assert user.is_active
    assert not user.is_staff


def test_create_user_lowercases_email():
    user = User.objects.create_user(email="  Ada@Example.COM ")

    assert user.email == "ada@example.com"
    assert not user.has_usable_password()


def test_create_user_requires_email():
    with pytest.raises(ValueError):
        User.objects.create_user(email="")


def test_email_is_case_insensitive_unique_via_manager():
    User.objects.create_user(email="ada@example.com")

    with pytest.raises(IntegrityError):
        User.objects.create_user(email="ADA@example.com")


def test_email_is_case_insensitive_unique_at_db_level():
    User.objects.create_user(email="ada@example.com")

    with pytest.raises(IntegrityError):
        User(email="Ada@Example.com").save()


def test_natural_key_lookup_is_case_insensitive():
    user = User.objects.create_user(email="ada@example.com")

    assert User.objects.get_by_natural_key("ADA@Example.com") == user


def test_create_superuser_sets_is_staff():
    user = User.objects.create_superuser(email="ops@example.com", password="s3cret-pass")

    assert user.is_staff
