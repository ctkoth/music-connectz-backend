from django.contrib import admin

from .models import Badge, Drill, EarnedBadge, TrainingEvent, TrainingProfile


@admin.register(TrainingProfile)
class TrainingProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "app_key", "xp", "level", "current_streak", "longest_streak", "drills_completed")
    list_filter = ("app_key",)
    search_fields = ("user__username", "user__email")

    @admin.display(description="Level")
    def level(self, obj):
        return obj.level


@admin.register(Drill)
class DrillAdmin(admin.ModelAdmin):
    list_display = ("app_key", "key", "title", "category", "xp", "order", "is_active")
    list_filter = ("app_key", "category", "is_active")
    search_fields = ("key", "title")


@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display = ("app_key", "code", "name", "rule", "threshold", "order")
    list_filter = ("app_key", "rule")
    search_fields = ("code", "name")


@admin.register(EarnedBadge)
class EarnedBadgeAdmin(admin.ModelAdmin):
    list_display = ("profile", "badge", "earned_at")
    search_fields = ("profile__user__username",)


@admin.register(TrainingEvent)
class TrainingEventAdmin(admin.ModelAdmin):
    list_display = ("profile", "drill_key", "score", "xp_awarded", "created_at")
    search_fields = ("profile__user__username", "drill_key")
