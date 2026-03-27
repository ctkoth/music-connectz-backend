from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialApp
from django.core.exceptions import MultipleObjectsReturned
from django.shortcuts import redirect
import logging


logger = logging.getLogger(__name__)
FRONTEND_URL = "https://musicconnectz.net"


class SafeSocialAccountAdapter(DefaultSocialAccountAdapter):
    def authentication_error(self, request, provider_id, error=None, exception=None, extra_context=None):
        logger.error(
            "OAuth login failure: provider=%s error=%s exception=%s",
            provider_id,
            error,
            exception,
            exc_info=exception is not None,
        )
        return redirect(f"{FRONTEND_URL}/?login_error=1&provider={provider_id}")

    def get_app(self, request, provider, client_id=None):
        try:
            return super().get_app(request, provider, client_id=client_id)
        except MultipleObjectsReturned:
            provider_id = provider.id if hasattr(provider, "id") else str(provider)
            qs = SocialApp.objects.filter(provider=provider_id)
            if client_id:
                qs = qs.filter(client_id=client_id)

            site = getattr(request, "site", None)
            if site is not None:
                site_qs = qs.filter(sites=site).order_by("id")
                if site_qs.exists():
                    return site_qs.first()

            fallback = qs.order_by("id").first()
            if fallback is not None:
                return fallback

            raise