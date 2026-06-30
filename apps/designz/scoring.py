"""Auto-scoring for DesignZ challenge submissions.

If ANTHROPIC_API_KEY is set, we ask Claude to rate the submitted artwork (by URL)
against the challenge prompt and return 0-100. If no key (or anything fails), we
fall back to a "credit for completing the work" baseline so the gamification loop
still closes — designers always get XP for showing up, and real critique when the
key is configured. A client-supplied score (e.g. self-rating) always wins if given.
"""
import json
import re

import requests
from django.conf import settings

BASELINE = 72  # "you did the work" — passes (>=60) and awards solid XP


def score_submission(drill_prompt, artifact_url, client_score=None):
    if client_score is not None:
        try:
            return max(0, min(100, int(client_score))), "self"
        except (TypeError, ValueError):
            pass

    key = settings.ANTHROPIC_API_KEY
    if key and artifact_url and artifact_url.startswith("http"):
        try:
            body = {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 200,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "url", "url": artifact_url}},
                        {"type": "text", "text": (
                            f"You are a design instructor scoring a student's submission for this "
                            f"challenge: \"{drill_prompt}\". Reply with ONLY a JSON object: "
                            f"{{\"score\": <0-100 integer>, \"note\": \"<one sentence of feedback>\"}}.")},
                    ],
                }],
            }
            r = requests.post("https://api.anthropic.com/v1/messages", timeout=30,
                              headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                       "content-type": "application/json"},
                              data=json.dumps(body))
            txt = "".join(b.get("text", "") for b in r.json().get("content", []))
            m = re.search(r"\{.*\}", txt, re.S)
            if m:
                data = json.loads(m.group(0))
                return max(0, min(100, int(data.get("score", BASELINE)))), data.get("note", "ai")
        except Exception:
            pass

    return BASELINE, "baseline"
