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
