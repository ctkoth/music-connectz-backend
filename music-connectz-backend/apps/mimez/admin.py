from django.contrib import admin

from .models import MimeZSubmission


@admin.register(MimeZSubmission)
class MimeZSubmissionAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "drill_key", "score", "created_at")
    list_filter = ("kind",)
    search_fields = ("user__username", "caption", "drill_key")
