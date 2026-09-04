from rest_framework import serializers

from .models import Transaction, Wallet


class WalletSerializer(serializers.ModelSerializer):
    money = serializers.FloatField(read_only=True)

    class Meta:
        model = Wallet
        # `royalties` was missing here, so every surface that reads a wallet —
        # which is most of them — could not see a balance the member had
        # genuinely accrued. A number that exists and cannot be seen is the
        # one kind of balance worse than no balance at all.
        fields = ["money_cents", "money", "energy", "spinaz", "promptz",
                  "royalties_cents", "royalties", "updated_at"]


class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = ["id", "kind", "amount_cents", "dev_tax_cents", "note", "created_at"]
