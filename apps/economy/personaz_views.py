"""PersonaZ catalog endpoints.

    GET /api/economy/personaz/         the whole catalog (every persona + skills)
    GET /api/economy/personaz/<key>/   one persona, for the skill picker

Public, because it is static reference data with nothing member-specific in it —
and because the picker runs during onboarding, before there's much of an account
to authenticate. Serving it means the frontend stops shipping its own copy, which
is how the two fell out of sync in the first place.
"""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .personaz import (PERSONAZ, catalog_payload, is_any_skill, label_for,
                       normalize_persona_key)


class PersonaZView(APIView):
    permission_classes = [AllowAny]

    def get(self, _request):
        return Response(catalog_payload())


class PersonaZDetailView(APIView):
    """One persona. Accepts any spelling that ever shipped — `Beat-producer`,
    `Designer`, `Independent artist` all resolve — and reports the canonical key
    back so a client can correct itself."""

    permission_classes = [AllowAny]

    def get(self, _request, key):
        canonical = normalize_persona_key(key)
        if not canonical:
            return Response(
                {"detail": f"Unknown persona '{key}'.", "known": list(PERSONAZ)},
                status=404,
            )
        persona = PERSONAZ[canonical]
        return Response(
            {
                "key": canonical,
                "requested": key,
                "name": persona["name"],
                "emoji": persona["emoji"],
                "label": label_for(canonical),
                "blurb": persona["blurb"],
                "since": persona["since"],
                "categories": [
                    {
                        "name": cat,
                        "skills": [
                            {"key": sk, "label": label, "any": is_any_skill(sk)}
                            for sk, label in skills.items()
                        ],
                    }
                    for cat, skills in persona["categories"].items()
                ],
            }
        )


class GenreZView(APIView):
    """GET the genre list — 2.2's fifteen first, flagged, then the additions.

    Public for the same reason as the persona catalog: static reference data the
    picker needs before anyone has signed in.
    """

    permission_classes = [AllowAny]

    def get(self, _request):
        from .genrez import catalog_payload as genre_catalog

        return Response(genre_catalog())
