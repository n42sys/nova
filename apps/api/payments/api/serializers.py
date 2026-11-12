from rest_framework import serializers

from payments.models import PaymentAccount


class PaymentAccountSerializer(serializers.Serializer):
    """What the API shows for a payment account. There is deliberately no field that could
    carry the secret: only `secret_key_hint` (e.g. "sk_live_…a1b2")."""

    id = serializers.UUIDField()
    provider = serializers.ChoiceField(choices=PaymentAccount.Provider.choices)
    public_key = serializers.CharField()
    secret_key_hint = serializers.CharField()
    status = serializers.ChoiceField(choices=PaymentAccount.Status.choices)
    verified_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class PaymentAccountKeysSerializer(serializers.Serializer):
    """Input only. `secret_key` is write-only and never echoed in errors."""

    public_key = serializers.CharField(max_length=200, trim_whitespace=True)
    secret_key = serializers.CharField(
        max_length=500, write_only=True, trim_whitespace=True, style={"input_type": "password"}
    )


class PaymentAccountCreateSerializer(PaymentAccountKeysSerializer):
    provider = serializers.ChoiceField(choices=PaymentAccount.Provider.choices)
