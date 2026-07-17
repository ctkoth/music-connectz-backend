from rest_framework import serializers

from .models import Transaction, Wallet


class WalletSerializer(serializers.ModelSerializer):
    money = serializers.FloatField(read_only=True)

    class Meta:
        model = Wallet
        fields = ["money_cents", "money", "energy", "spinaz", "updated_at"]


class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = ["id", "kind", "amount_cents", "dev_tax_cents", "note", "created_at"]
