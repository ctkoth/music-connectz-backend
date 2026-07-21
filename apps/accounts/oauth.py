"""
Server-side OAuth verification for Google, GitHub, and Apple.

Each verifier returns a normalized dict:
    {"provider", "uid", "email", "name", "avatar_url"}
or raises OAuthError with a user-safe message.

Env vars expected (set on Render):
    GOOGLE_OAUTH_CLIENT_ID
    GITHUB_OAUTH_CLIENT_ID, GITHUB_OAUTH_CLIENT_SECRET
    APPLE_OAUTH_CLIENT_ID         (the Services ID / audience)
"""
import os

import requests


class OAuthError(Exception):
    pass


def _env(name):
    return os.environ.get(name, "").strip()


# ---------------------------------------------------------------- Google ----
def verify_google(credential: str):
    """Verify a Google ID token (the `credential` from Google Identity Services)."""
    if not credential:
        raise OAuthError("Missing Google credential.")
    client_id = _env("GOOGLE_OAUTH_CLIENT_ID")
    if not client_id:
        # Fail closed: without our client-ID we cannot verify the token was
        # issued for THIS app, so any valid Google token would be accepted.
        raise OAuthError("Google sign-in is not configured on the server.")
    try:
        resp = requests.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": credential},
            timeout=10,
        )
    except requests.RequestException:
        raise OAuthError("Could not reach Google to verify sign-in.")
    if resp.status_code != 200:
        raise OAuthError("Google rejected that sign-in token.")
    data = resp.json()
    if data.get("aud") != client_id:
        raise OAuthError("Google token audience mismatch.")
    if data.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise OAuthError("Google token issuer mismatch.")
    if data.get("email_verified") in ("false", False):
        raise OAuthError("Google email is not verified.")
    return {
        "provider": "google",
        "uid": data["sub"],
        "email": (data.get("email") or "").lower(),
        "name": data.get("name") or "",
        "avatar_url": data.get("picture") or "",
    }


# ---------------------------------------------------------------- GitHub ----
def exchange_github(code: str, redirect_uri: str = ""):
    """Exchange a GitHub OAuth `code` for an access token, then load the user."""
    if not code:
        raise OAuthError("Missing GitHub code.")
    client_id = _env("GITHUB_OAUTH_CLIENT_ID")
    client_secret = _env("GITHUB_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise OAuthError("GitHub sign-in is not configured on the server.")

    try:
        token_resp = requests.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            timeout=10,
        )
    except requests.RequestException:
        raise OAuthError("Could not reach GitHub to verify sign-in.")
    token = token_resp.json().get("access_token")
    if not token:
        raise OAuthError("GitHub did not return an access token.")

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    user = requests.get("https://api.github.com/user", headers=headers, timeout=10).json()

    email = user.get("email") or ""
    if not email:
        emails = requests.get(
            "https://api.github.com/user/emails", headers=headers, timeout=10
        ).json()
        if isinstance(emails, list):
            primary = next(
                (e for e in emails if e.get("primary") and e.get("verified")), None
            )
            email = (primary or {}).get("email", "") if primary else ""

    return {
        "provider": "github",
        "uid": str(user.get("id")),
        "email": email.lower(),
        "name": user.get("name") or user.get("login") or "",
        "avatar_url": user.get("avatar_url") or "",
    }


# ----------------------------------------------------------------- Apple ----
def verify_apple(id_token: str):
    """Verify an Apple identity token (JWT) against Apple's public keys."""
    if not id_token:
        raise OAuthError("Missing Apple identity token.")
    try:
        import jwt
        from jwt import PyJWKClient
    except Exception:
        raise OAuthError("Apple sign-in requires PyJWT on the server.")

    client_id = _env("APPLE_OAUTH_CLIENT_ID")
    if not client_id:
        # Fail closed: without our audience we can't confirm the token was
        # minted for THIS app.
        raise OAuthError("Apple sign-in is not configured on the server.")
    try:
        jwk_client = PyJWKClient("https://appleid.apple.com/auth/keys")
        signing_key = jwk_client.get_signing_key_from_jwt(id_token)
        data = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=client_id,
            issuer="https://appleid.apple.com",
            options={"verify_aud": True},
        )
    except Exception:
        raise OAuthError("Apple rejected that sign-in token.")

    return {
        "provider": "apple",
        "uid": data["sub"],
        "email": (data.get("email") or "").lower(),
        "name": "",
        "avatar_url": "",
    }


# ------------------------------------------------- Generic OAuth2 (code) ----
# Standard "authorization code" providers that all follow the same shape:
# swap the `code` for an access token at token_url, then load the profile from
# userinfo_url. Per-provider quirks (Basic vs body client auth, client_key
# naming, response field mapping) live in this registry. Public client IDs come
# from <PREFIX>_OAUTH_CLIENT_ID and secrets from <PREFIX>_OAUTH_CLIENT_SECRET,
# so a provider stays cleanly "not configured" (fail-closed) until both are set.
def _first_image(u):
    imgs = u.get("images") or []
    return (imgs[0] or {}).get("url", "") if imgs else ""


OAUTH2_PROVIDERS = {
    "spotify": {
        "token_url": "https://accounts.spotify.com/api/token",
        "userinfo_url": "https://api.spotify.com/v1/me",
        "basic_auth": True,  # client creds go in an HTTP Basic header
        "map": lambda u: {"uid": str(u.get("id")), "email": (u.get("email") or ""),
                          "name": u.get("display_name") or "", "avatar_url": _first_image(u)},
    },
    "microsoft": {
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "userinfo_url": "https://graph.microsoft.com/v1.0/me",
        "map": lambda u: {"uid": str(u.get("id")),
                          "email": (u.get("mail") or u.get("userPrincipalName") or ""),
                          "name": u.get("displayName") or "", "avatar_url": ""},
    },
    "facebook": {
        "token_url": "https://graph.facebook.com/v18.0/oauth/access_token",
        "userinfo_url": "https://graph.facebook.com/me?fields=id,name,email,picture.type(large)",
        "map": lambda u: {"uid": str(u.get("id")), "email": (u.get("email") or ""),
                          "name": u.get("name") or "",
                          "avatar_url": (((u.get("picture") or {}).get("data")) or {}).get("url", "")},
    },
    "soundcloud": {
        "token_url": "https://secure.soundcloud.com/oauth/token",
        "userinfo_url": "https://api.soundcloud.com/me",
        "map": lambda u: {"uid": str(u.get("id") or u.get("urn") or ""),
                          "email": (u.get("email") or ""),
                          "name": u.get("username") or u.get("full_name") or "",
                          "avatar_url": u.get("avatar_url") or ""},
    },
    "twitter": {
        "token_url": "https://api.twitter.com/2/oauth2/token",
        "userinfo_url": "https://api.twitter.com/2/users/me?user.fields=profile_image_url",
        "basic_auth": True,  # confidential client authenticates with Basic + PKCE verifier
        "map": lambda u: (lambda d: {"uid": str(d.get("id")), "email": "",
                                     "name": d.get("name") or d.get("username") or "",
                                     "avatar_url": d.get("profile_image_url") or ""})(u.get("data") or u),
    },
}


def exchange_oauth2(provider: str, code: str, redirect_uri: str = "", code_verifier: str = ""):
    """Swap an authorization `code` for an access token, then load + normalize
    the member's profile. Used for every standard code-flow provider."""
    cfg = OAUTH2_PROVIDERS.get(provider)
    if not cfg:
        raise OAuthError(f"Unsupported provider '{provider}'.")
    if not code:
        raise OAuthError(f"Missing {provider} code.")
    client_id = _env(f"{provider.upper()}_OAUTH_CLIENT_ID")
    client_secret = _env(f"{provider.upper()}_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise OAuthError(f"{provider.title()} sign-in is not configured on the server.")

    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
    }
    if code_verifier:
        body["code_verifier"] = code_verifier
    headers = {"Accept": "application/json"}
    auth = None
    if cfg.get("basic_auth"):
        auth = (client_id, client_secret)  # HTTP Basic
    else:
        body["client_secret"] = client_secret

    try:
        token_resp = requests.post(cfg["token_url"], data=body, headers=headers, auth=auth, timeout=10)
        token = (token_resp.json() or {}).get("access_token")
    except requests.RequestException:
        raise OAuthError(f"Could not reach {provider.title()} to verify sign-in.")
    except ValueError:
        raise OAuthError(f"{provider.title()} returned an unexpected token response.")
    if not token:
        raise OAuthError(f"{provider.title()} did not return an access token.")

    try:
        profile = requests.get(
            cfg["userinfo_url"], headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, timeout=10
        ).json()
    except (requests.RequestException, ValueError):
        raise OAuthError(f"Could not load your {provider.title()} profile.")

    info = cfg["map"](profile or {})
    if not info.get("uid"):
        raise OAuthError(f"{provider.title()} did not return a user id.")
    info["provider"] = provider
    info["email"] = (info.get("email") or "").lower()
    return info
