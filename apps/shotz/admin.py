from django.contrib import admin
from .models import Clip, Footage, Location, Project, Render, ShotListItem, Storyboard
for m in (Project, Clip, Footage, Storyboard, ShotListItem, Location, Render):
    admin.site.register(m)
