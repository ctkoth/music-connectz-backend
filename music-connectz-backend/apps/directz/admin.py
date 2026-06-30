from django.contrib import admin

from .models import DirectZDraft


@admin.register(DirectZDraft)
class DirectZDraftAdmin(admin.ModelAdmin):
    list_display = ("user", "focus", "title", "scene_count", "score", "created_at")
    list_filter = ("focus",)
    search_fields = ("user__username", "title", "drill_key")
