"""
Payment Log Serializer

Used to serialize PaymentLog model instances for API responses.
Handles transaction history, payment status, and audit information.
"""

from rest_framework import serializers


class PaymentLogSerializer(serializers.ModelSerializer):
    """
    Serializes PaymentLog instances.
    
    Includes:
    - User information
    - Payment provider details
    - Transaction amount and currency
    - Order/transaction IDs
    - Timestamps
    """
    
    # Add related user info if needed
    user_username = serializers.CharField(source='user.username', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    
    class Meta:
        model = 'backend.PaymentLog'  # Update if model is in different app
        fields = [
            'id',
            'user',
            'user_username',
            'user_email',
            'provider',  # e.g., 'paypal', 'stripe'
            'order_id',
            'amount',
            'currency',
            'status',  # e.g., 'completed', 'pending', 'failed'
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'user',
            'user_username', 
            'user_email',
            'created_at',
            'updated_at',
        ]
