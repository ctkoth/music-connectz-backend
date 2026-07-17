from django.contrib import admin

from .models import Membership, PaymentIntent, Transaction, Upload, Wallet


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "tier", "since")
    list_filter = ("tier",)
    search_fields = ("user__username", "user__email")


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("user", "money", "energy", "spinaz", "updated_at")
    search_fields = ("user__username",)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "amount_cents", "dev_tax_cents", "note", "created_at")
    list_filter = ("kind",)
    search_fields = ("user__username", "note")


@admin.register(Upload)
class UploadAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "size_bytes", "content_type", "created_at")
    search_fields = ("user__username", "name")


@admin.register(PaymentIntent)
class PaymentIntentAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "amount_cents", "net_cents", "dev_tax_cents", "status", "created_at")
    list_filter = ("provider", "status")
    search_fields = ("user__username", "provider_ref")
