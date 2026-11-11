import uuid

from core.fields import uuid7


def test_uuid7_is_a_plain_version_7_uuid():
    value = uuid7()

    assert type(value) is uuid.UUID
    assert value.version == 7


def test_uuid7_is_time_ordered():
    values = [uuid7() for _ in range(100)]

    assert values == sorted(values)
