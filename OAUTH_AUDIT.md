# OAuth audit

Every sign-in path in `apps/accounts/` — `oauth.py`, `views.py`, `models.py`,
`passwords.py` — plus the JWT settings they issue into. This is the login door,
so a mistake here is an account takeover, not a bug report.

504 tests pass.

## Providers

| Provider | Flow | Verified how | Email trusted? |
|---|---|---|---|
| Google | ID token | `tokeninfo` — checks `aud`, `iss`, `email_verified` | ✅ yes |
| Apple | ID token | JWT signature vs Apple's public keys, `aud` + `iss` | ✅ yes |
| GitHub | Auth code | Server-side exchange, then `/user` | ✅ (GitHub only publishes verified addresses) |
| Spotify · Microsoft · Facebook · SoundCloud · Twitter | Auth code | Server-side exchange, then userinfo | ❌ **never** |

---

## What's right

**Every provider is verified server-side.** No endpoint accepts a client's claim
about who they are — the ID token is checked against the issuer, or the code is
exchanged using a secret the client never sees.

**Everything fails closed.** A provider with no client ID configured raises
rather than skipping the check. That ordering matters: verifying an audience
against an empty value would accept *anyone's* token, so "not configured" has to
mean "refused", never "unchecked".

**The account-takeover path is closed, and this is the subtle one.** Signing in
with a provider that reports an email matches an existing account by that
address — which hands the caller that account. `_user_from_oauth` only does it
when the provider *asserted the address is verified*. The five generic code-flow
providers hardcode `email_verified = False`, because their userinfo endpoints
don't say whether the address was confirmed. Without that, anyone could set an
arbitrary email on a Spotify account and use it to walk into the matching Music
ConnectZ account.

**Identities are unique.** `OAuthIdentity` has `unique_together = (provider,
provider_uid)`, so one provider account can't attach to two members.

**GitHub's uid is checked before use.** A malformed response would otherwise
produce uid `"None"`, which *every* failed sign-in would then share — collapsing
them all onto one account.

---

## Fixed in this pass

**Google accepted only one client ID.** Google issues a *separate* OAuth client
ID per platform — web, Android, iOS — and `aud` carries whichever one signed the
user in. The check compared against `GOOGLE_OAUTH_CLIENT_ID` alone, so a native
Google sign-in would have been rejected as an audience mismatch. Exactly the
Apple bug from earlier today, in a different provider. Now reads
`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_ANDROID_CLIENT_ID` and
`GOOGLE_OAUTH_IOS_CLIENT_ID`, each comma-splittable — and still rejects an
audience that isn't one of them.

**GitHub could 500 on GitHub's bad day.** `token_resp.json()` and the profile
fetch were unwrapped. A 502 from GitHub returns an HTML error page, so the parse
raised and the member got a 500 — our bug, reported for their outage. Now caught
and turned into a readable message.

**No rate limiting existed anywhere.** Login, register, password reset and OAuth
were all unauthenticated and uncapped. Two consequences: unlimited password
guessing, and — because every OAuth call makes an outbound request to
Google/GitHub/Apple — this server was a free amplifier for hammering them. Now
scoped throttles, tunable per environment:

| Scope | Default | Env var |
|---|---|---|
| `auth-login` | 30/min | `THROTTLE_AUTH_LOGIN` |
| `auth-oauth` | 30/min | `THROTTLE_AUTH_OAUTH` |
| `auth-register` | 20/hour | `THROTTLE_AUTH_REGISTER` |
| `auth-password` | 10/hour | `THROTTLE_AUTH_PASSWORD` |

Only those four scopes are throttled — there's no global anon rate, so public
catalogs stay uncapped. Rates are blanked under `manage.py test` (counters live
in the cache and would otherwise leak between test methods), and
`test_throttle.py` switches them back on so the feature isn't left untested.
That file patches `SimpleRateThrottle.THROTTLE_RATES` directly rather than using
`override_settings`, because DRF binds that dict at import — a settings override
alone changes nothing and the test would pass while measuring nothing.

---

## Open findings

### 🔴 The error message points at a feature that doesn't exist

When an unverified-email provider collides with an existing account, the member
is told:

> "…sign in with your original method and **link it from there**."

**There is no link endpoint.** `apps/accounts/urls.py` has register, login,
password forgot/reset, me, refresh, oauth-config, oauth, referrals, onboard.
Nothing links a second provider to a signed-in account.

So a member who signed up with a password and later tries Spotify hits a wall
with instructions that lead nowhere. It's the most likely OAuth support ticket
you'll get, and the fix is small: an authenticated `POST /api/auth/oauth/<provider>/link/`
that runs the same verifier and attaches an `OAuthIdentity` to `request.user`
instead of searching by email. Say the word and I'll build it.

### 🟡 No nonce — ID tokens are replayable inside their lifetime

Google and Apple ID tokens are accepted on presentation. Neither flow generates
or checks a `nonce`, so a token captured in that window could be replayed to
sign in as that member. The exposure is genuinely narrow (you'd need the token,
which means you're already in a strong position) but it's the standard defence
and both providers support it. Needs frontend cooperation: generate a nonce,
pass it to the provider, send it alongside the token.

### 🟡 Refresh tokens live 14 days and can't be revoked

`SIMPLE_JWT` sets a 14-day refresh lifetime with no `ROTATE_REFRESH_TOKENS`, no
`BLACKLIST_AFTER_ROTATION`, and no blacklist app installed. A stolen refresh
token is good for two weeks, and **changing your password doesn't invalidate
it** — there's no logout that revokes anything. For a platform holding wallet
balances, that's worth closing: add `rest_framework_simplejwt.token_blacklist`,
turn on rotation, and revoke on password change.

### 🟡 `state` is never validated

The CSRF defence for OAuth is the `state` parameter. The backend takes a `code`
by POST and never sees the redirect, so it *can't* check it — this is
necessarily the frontend's job. Worth confirming the frontend generates `state`,
stores it, and compares on return. If it doesn't, login-CSRF is live.

### 🟢 Apple never provides a name

Apple only sends the member's name on the *first* authorization, and it arrives
in the form post rather than the ID token — which `verify_apple` doesn't read.
So `name` is always `""` and the username is derived from the email local part.
Cosmetic, but it's why Apple sign-ups look anonymous.

### 🟢 Google costs a network round trip per login

`verify_google` calls Google's `tokeninfo` endpoint rather than verifying the
JWT locally against Google's public keys — the way `verify_apple` already does.
It works and it's correct, but it adds latency to every sign-in and Google rate
limits that endpoint. Switching to local verification would make Google cheaper
and match Apple's approach.

---

## Environment variables

| Variable | Needed for | Missing means |
|---|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` | Google web sign-in | Google refused |
| `GOOGLE_OAUTH_ANDROID_CLIENT_ID` | Native Android Google | Audience mismatch |
| `GOOGLE_OAUTH_IOS_CLIENT_ID` | Native iOS Google | Audience mismatch |
| `APPLE_OAUTH_CLIENT_ID` | Apple **web** (Services ID) | Web Apple refused |
| `APPLE_OAUTH_BUNDLE_ID` | Apple **native iOS** (Bundle ID) | Native Apple refused |
| `GITHUB_OAUTH_CLIENT_ID` / `_SECRET` | GitHub | GitHub refused |
| `<PROVIDER>_OAUTH_CLIENT_ID` / `_SECRET` | Spotify, Microsoft, Facebook, SoundCloud, Twitter | That provider refused |

`APPLE_KEY_ID`, `APPLE_TEAM_ID` and `APPLE_PRIVATE_KEY` are **not read by any
code**. They're only needed if server-to-server token exchange or Apple's
revocation notifications get built.

## Recommended order

1. **Build the link endpoint.** It's the one finding that already has a
   user-facing promise attached to it.
2. **Confirm the frontend validates `state`.** Costs nothing to check.
3. **Turn on refresh-token rotation and blacklisting**, and revoke on password
   change — before wallet balances get bigger.
4. Nonce, and local Google verification, when convenient.
