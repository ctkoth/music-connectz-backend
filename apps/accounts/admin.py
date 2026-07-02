from django.contrib import admin

from .models import OAuthIdentity, Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "created_at")
    search_fields = ("user__username", "user__email", "phone")


@admin.register(OAuthIdentity)
class OAuthIdentityAdmin(admin.ModelAdmin):
    list_display = ("provider", "provider_uid", "user", "email", "created_at")
    list_filter = ("provider",)
    search_fields = ("provider_uid", "email", "user__username")
