from django.contrib import admin
from .models import Work, Skill, Persona, UserProfile, Referral, AgreementTemplate, CollabRoyaltyAgreement, AgreementChangeLog

admin.site.register(Work)
admin.site.register(Skill)
admin.site.register(Persona)
admin.site.register(UserProfile)
admin.site.register(Referral)
admin.site.register(AgreementTemplate)
admin.site.register(CollabRoyaltyAgreement)
admin.site.register(AgreementChangeLog)
