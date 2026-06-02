from django.contrib import admin

from .models import Asset, BrandKit, Comment, Palette, Project, Template, Version

for m in (Project, Asset, Template, BrandKit, Palette, Comment, Version):
    admin.site.register(m)
