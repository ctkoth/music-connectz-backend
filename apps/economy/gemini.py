"""Gemini generation for Image ConnectZ (image) + Video ConnectZ (Veo video).

Uses Google's Generative Language REST API. Charges the AI-cost minimum (PromptZ
first, then cash) like the rest of the AI suite. Every endpoint 503s cleanly
when GEMINI_API_KEY isn't configured, so the client falls back gracefully.
Model names are env-overridable since Google revises them often.
"""
import os

import requests
from django.conf import settings

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import ai_cost
from .models import can_afford_ai, charge_ai_usage, wallet_for
from .views import platform_owner

BASE = "https://generativelanguage.googleapis.com/v1beta"


def _key():
    return getattr(settings, "GEMINI_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")


def _bill(user, note):
    """Charge the AI minimum (PromptZ→cash) and route it to the owner."""
    cost = ai_cost("standard")
    if not cost:
        return 0
    remaining = charge_ai_usage(user, cost, note=note)
    owner = platform_owner()
    if owner and owner.id != user.id:
        ow = wallet_for(owner)
        ow.money_cents = (ow.money_cents or 0) + cost
        ow.save(update_fields=["money_cents", "updated_at"])
    return cost


class GeminiImageView(APIView):
    """POST { prompt } → a generated image as a data URI. Synchronous."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        prompt = str((request.data or {}).get("prompt", "")).strip()
        if not prompt:
            return Response({"detail": "prompt required"}, status=status.HTTP_400_BAD_REQUEST)
        key = _key()
        if not key:
            return Response({"detail": "Image generation isn't configured — set GEMINI_API_KEY on the backend.", "image": None},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        cost = ai_cost("standard")
        if cost and not can_afford_ai(request.user, cost):
            return Response({"detail": "Not enough PromptZ / balance.", "cost_cents": cost}, status=status.HTTP_402_PAYMENT_REQUIRED)

        model = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image-preview")
        try:
            r = requests.post(
                f"{BASE}/models/{model}:generateContent?key={key}",
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}},
                timeout=90,
            )
            data = r.json()
            img, mime = None, "image/png"
            for part in (data.get("candidates") or [{}])[0].get("content", {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    img = inline["data"]; mime = inline.get("mimeType") or inline.get("mime_type") or mime
                    break
            if not img:
                detail = (data.get("error") or {}).get("message") or "No image returned."
                return Response({"detail": f"Gemini: {detail}"[:200], "image": None}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            return Response({"detail": f"Gemini error: {exc}"[:200], "image": None}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        cost = _bill(request.user, f"Image ConnectZ (Gemini)")
        return Response({"image": f"data:{mime};base64,{img}", "cost_cents": cost, "money": round(wallet_for(request.user).money_cents / 100, 2)})


class GeminiVideoView(APIView):
    """POST { prompt } → start a Veo video generation; returns an operation name
    to poll. Video gen is long-running (~1–2 min)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        prompt = str((request.data or {}).get("prompt", "")).strip()
        if not prompt:
            return Response({"detail": "prompt required"}, status=status.HTTP_400_BAD_REQUEST)
        key = _key()
        if not key:
            return Response({"detail": "Video generation isn't configured — set GEMINI_API_KEY on the backend.", "operation": None},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        cost = ai_cost("standard")
        if cost and not can_afford_ai(request.user, cost):
            return Response({"detail": "Not enough PromptZ / balance.", "cost_cents": cost}, status=status.HTTP_402_PAYMENT_REQUIRED)

        model = os.environ.get("GEMINI_VIDEO_MODEL", "veo-3.0-generate-preview")
        try:
            r = requests.post(
                f"{BASE}/models/{model}:predictLongRunning?key={key}",
                json={"instances": [{"prompt": prompt}]},
                timeout=60,
            )
            data = r.json()
            op = data.get("name")
            if not op:
                detail = (data.get("error") or {}).get("message") or "Could not start video generation."
                return Response({"detail": f"Veo: {detail}"[:200], "operation": None}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            return Response({"detail": f"Veo error: {exc}"[:200], "operation": None}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        cost = _bill(request.user, "Video ConnectZ (Veo)")
        return Response({"operation": op, "status": "pending", "cost_cents": cost})


class GeminiVideoStatusView(APIView):
    """POST { operation } → poll a Veo generation; returns { done, video_url }."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        op = str((request.data or {}).get("operation", "")).strip()
        key = _key()
        if not op or not key:
            return Response({"detail": "operation and GEMINI_API_KEY required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            r = requests.get(f"{BASE}/{op}?key={key}", timeout=30)
            data = r.json()
            if not data.get("done"):
                return Response({"done": False})
            resp = data.get("response") or {}
            uri = None
            samples = (resp.get("generateVideoResponse") or {}).get("generatedSamples") or resp.get("generatedSamples") or []
            if samples:
                uri = (samples[0].get("video") or {}).get("uri") or samples[0].get("uri")
            return Response({"done": True, "video_url": uri and f"{uri}&key={key}" if uri else None})
        except Exception as exc:
            return Response({"detail": f"Veo poll error: {exc}"[:200], "done": False}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
