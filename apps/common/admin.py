from django.contrib import admin
from .models import UserFlags


@admin.register(UserFlags)
class UserFlagsAdmin(admin.ModelAdmin):
    list_display = ("user", "age_status", "updated_at")
    list_filter = ("age_status",)
    search_fields = ("user__username",)
