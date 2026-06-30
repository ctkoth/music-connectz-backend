from django.contrib import admin
from .models import Game, OCCMedia


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "genre", "subgenre", "engine", "status", "auto_mode")
    list_filter = ("engine", "status", "genre", "auto_mode")


@admin.register(OCCMedia)
class OCCMediaAdmin(admin.ModelAdmin):
    list_display = ("kind", "owner", "routed_to", "created_at")
    list_filter = ("kind", "routed_to")
