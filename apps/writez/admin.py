from django.contrib import admin

from .models import BarSet, Brief, Hook, Project, Reference, RhymeStack, Version

for m in (Project, Hook, BarSet, RhymeStack, Reference, Brief, Version):
    admin.site.register(m)
