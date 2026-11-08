from django.contrib import admin

from .models import (MemberFacet, Skill, SkillGate, UserSkill, WorkRating,
                     WorkSkillTag)

for m in (Skill, UserSkill, WorkSkillTag, WorkRating, MemberFacet, SkillGate):
    admin.site.register(m)
