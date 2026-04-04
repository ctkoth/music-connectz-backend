from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from django.conf import settings
from django.http import HttpResponseRedirect

class SafeSocialAccountAdapter(DefaultSocialAccountAdapter):
    def _oauth_error_response(self):
        error_url = (
            getattr(settings, 'SOCIALACCOUNT_ERROR_URL', '')
            or 'https://musicconnectz.net/?login_error=1'
        )
        return HttpResponseRedirect(error_url)
    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)

        if not getattr(user, 'email', ''):
            user.email = ''

        if not getattr(user, 'username', ''):
            social_uid = getattr(getattr(sociallogin, 'account', None), 'uid', '') or 'user'
            user.username = f"{sociallogin.account.provider}_{social_uid}"[:150]

        return user

    def get_app(self, request, provider, client_id=None):
        """
        Avoid startup/login crashes when both DB SocialApp and env APP config exist
        for the same provider by preferring the DB-backed app where possible.
        """
        from allauth.socialaccount.models import SocialApp

        apps = self.list_apps(request, provider=provider, client_id=client_id)
        if len(apps) == 0:
<<<<<<< HEAD
            # Unconfigured providers should fail gracefully as a login error,
            # not as an internal server error.
            raise ImmediateHttpResponse(self._oauth_error_response())
        if len(apps) == 1:
            return apps[0]

=======
            raise SocialApp.DoesNotExist()
        if len(apps) == 1:
            return apps[0]

        from django.conf import settings

>>>>>>> dec631da98253f85bff28b8e054535819adb2224
        visible_apps = [
            app for app in apps
            if not ((getattr(app, "settings", None) or {}).get("hidden"))
        ]
        candidates = visible_apps or apps

        # If env APP config exists, prefer the app matching that client_id.
        # This avoids stale DB SocialApp rows causing provider redirect_uri mismatches.
        env_app = getattr(settings, "SOCIALACCOUNT_PROVIDERS", {}).get(provider, {}).get("APP", {})
        env_client_id = (env_app.get("client_id") or "").strip()
        if env_client_id:
            env_matches = [app for app in candidates if (app.client_id or "").strip() == env_client_id]
            if env_matches:
                ranked_env = sorted(
                    env_matches,
                    key=lambda app: (
                        0 if not getattr(app, "pk", None) else 1,
                        getattr(app, "pk", 0) or 0,
                    ),
                )
                return ranked_env[0]

        # Prefer DB-backed SocialApp objects (have a primary key) over env-only APP config.
        db_candidates = [app for app in candidates if getattr(app, "pk", None)]
        if len(db_candidates) == 1:
            return db_candidates[0]

        # Collapse exact duplicates by provider/provider_id/client_id, preferring DB rows.
        deduped = {}
        for app in candidates:
            key = (app.provider, getattr(app, "provider_id", None), app.client_id)
            chosen = deduped.get(key)
            if chosen is None:
                deduped[key] = app
                continue
            if not getattr(chosen, "pk", None) and getattr(app, "pk", None):
                deduped[key] = app

        resolved = list(deduped.values())
        if len(resolved) == 1:
            return resolved[0]

<<<<<<< HEAD
        if len(resolved) == 0:
            raise ImmediateHttpResponse(self._oauth_error_response())

=======
>>>>>>> dec631da98253f85bff28b8e054535819adb2224
        # Final safety net: pick deterministic app instead of raising 500.
        ranked = sorted(
            resolved,
            key=lambda app: (
                0 if getattr(app, "pk", None) else 1,
                getattr(app, "pk", 0) or 0,
                app.client_id or "",
            ),
        )
        return ranked[0]