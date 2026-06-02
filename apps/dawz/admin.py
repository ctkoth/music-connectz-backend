from django.contrib import admin

from .models import DawProposal, DawVote


@admin.register(DawProposal)
class DawProposalAdmin(admin.ModelAdmin):
    list_display = ("name", "comparable_to", "status", "order")
    list_editable = ("status", "order")


admin.site.register(DawVote)
