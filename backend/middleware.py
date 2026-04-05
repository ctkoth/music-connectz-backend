from django.conf import settings
from django.http import HttpResponseRedirect

class OAuthRouteFailSafeMiddleware:
    """
    Ensure OAuth/account routes never surface raw 500s to users.

    If an unexpected server exception occurs under /accounts/, redirect to the
    configured social login error URL so users consistently see a safe screen.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            return self.get_response(request)
        except Exception:
            if request.path.startswith('/accounts/'):
                error_url = (
                    getattr(settings, 'SOCIALACCOUNT_ERROR_URL', '')
                    or 'https://musicconnectz.net/?login_error=1'
                )
                return HttpResponseRedirect(error_url)
            raise
class CanonicalOAuthHostMiddleware:
    """
    Force OAuth/account routes onto a single canonical host.

    This prevents provider redirect_uri mismatches when requests start on
    different backend hostnames.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        enforce = bool(getattr(settings, 'OAUTH_CANONICAL_ENFORCE', False))
        canonical_host = (getattr(settings, 'OAUTH_CANONICAL_HOST', '') or '').strip().lower()
        canonical_scheme = (getattr(settings, 'OAUTH_CANONICAL_SCHEME', 'https') or 'https').strip().lower()

        if enforce and canonical_host and request.path.startswith('/accounts/'):
            current_host = (request.get_host() or '').split(':')[0].strip().lower()
            if current_host and current_host != canonical_host:
                query = request.META.get('QUERY_STRING', '')
                qs = f'?{query}' if query else ''
                target = f"{canonical_scheme}://{canonical_host}{request.path}{qs}"
                return HttpResponseRedirect(target)

        return self.get_response(request)
