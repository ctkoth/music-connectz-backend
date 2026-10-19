from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.admin.exceptions import NotRegistered
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.http import HttpResponseRedirect
from django.urls import reverse

from .models import OAuthIdentity, Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "created_at")
    search_fields = ("user__username", "user__email", "phone")


@admin.register(OAuthIdentity)
class OAuthIdentityAdmin(admin.ModelAdmin):
    list_display = ("provider", "provider_uid", "user", "email", "created_at")
    list_filter = ("provider",)
    search_fields = ("provider_uid", "email", "user__username")


User = get_user_model()


class UserAdmin(DjangoUserAdmin):
    """Django's own user admin, with deletion sent through the one way to delete.

    The stock one calls `user.delete()`: no Stripe cancel and no file purge, so a
    fifth door brought both bugs back (`erasure.py` says exactly this about a
    fifth door). A refusal leaves the account where it is and says why.

    Bulk delete is removed rather than rerouted. Django reports "Successfully
    deleted N" from the size of the selection whatever happened to each one, and
    a count that overstates what was deleted, on accounts, is worse than making
    the owner do them one at a time.
    """

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    def delete_model(self, request, obj):
        from apps.accounts.erasure import delete_user
        from apps.economy.stripe_cancel import CancelFailed
        try:
            delete_user(obj)
        except CancelFailed as exc:
            request._erase_refused = True
            messages.error(request, f"{obj.get_username()} was not deleted. {exc.detail}")

    def response_delete(self, request, obj_display, obj_id):
        if getattr(request, "_erase_refused", False):
            return HttpResponseRedirect(reverse("admin:auth_user_change", args=[obj_id]))
        return super().response_delete(request, obj_display, obj_id)


try:
    admin.site.unregister(User)
except NotRegistered:
    pass
admin.site.register(User, UserAdmin)
