from django.contrib import admin

from .models import Attempt, Drill, SkillProgress, SkillTrack

for m in (SkillTrack, Drill, SkillProgress, Attempt):
    admin.site.register(m)
