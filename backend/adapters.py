from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialApp
from django.core.exceptions import MultipleObjectsReturned


class SafeSocialAccountAdapter(DefaultSocialAccountAdapter):
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