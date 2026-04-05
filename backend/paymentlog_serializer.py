from rest_framework import serializers
from .models import PaymentLog

class PaymentLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentLog
        fields = (
            'id', 'user', 'provider', 'order_id', 'amount', 'currency', 'status', 'raw_data', 'created_at',
        )
        read_only_fields = fields
