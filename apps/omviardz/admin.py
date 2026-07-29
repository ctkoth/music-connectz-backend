from django.contrib import admin

from .models import TourProgress


@admin.register(TourProgress)
class TourProgressAdmin(admin.ModelAdmin):
    list_display = ("user", "track", "step_key", "skipped", "completed_at", "updated_at")
    list_filter = ("track", "skipped")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("created_at", "updated_at")
