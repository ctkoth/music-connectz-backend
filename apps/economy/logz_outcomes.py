"""What a ledger row BOUGHT — the rating, the report and the file.

A spend is only a fee until the ledger can point at what it paid for. Rows
carry `ref` ("take:12", "sentence:4"), set by the code that made the purchase;
this resolves a page of them to the thing itself in two queries, so LogZ can open
a row onto the score the member was given, the coach's report, and the recording.

Honest about the file: a take scored in the coach was SCORED and not kept — the
coach listens, and the recording is only stored when it came from a post or a
journal entry, or the member posted it. So a row says where the file is when
there is one, and says plainly that it was not kept when there isn't, rather than
showing a dead link. (Keeping every take would change what the privacy policy
promises and what storage costs; that is a decision for the owner, not a default.)
"""
from .media import stable_media_url
from .instruments import WIT_KEYS, scores_for
from .models import SentenceWork, TakeScore

NOT_KEPT = ("This take was scored, not kept — the coach listens and the recording isn't stored unless you "
            "tick \"Keep this take\" when you send it. A take that came from a post or a journal entry keeps "
            "its file there.")


def file_of(t, request=None):
    """Where a take's recording is: kept (with its address), lost, or never kept."""
    up = t.upload
    if up and not up.missing_since:
        return {"kept": True, "name": up.name, "content_type": up.content_type,
                "url": stable_media_url(up, request) or None}
    if up and up.missing_since:
        return {"kept": False, "why": "The recording was lost from storage; the score and report are kept."}
    return {"kept": False, "why": NOT_KEPT}


def _take(t, request):
    r = t.read or {}
    file = file_of(t, request)
    # Each number paired with what the coach heard behind it: the strongest
    # observation it filed under that dimension. A number with nothing beside it
    # is the "score with no description" this app does not ship.
    try:
        labels = dict(scores_for(t.app_key, lyrics=True, extras=WIT_KEYS))
    except Exception:                                       # pragma: no cover
        labels = {}
    heard = ((t.upgrades or {}).get("context") or {}).get("heard") or []
    best = {}
    for h in heard:
        if isinstance(h, dict) and h.get("dim") and h.get("what"):
            if h["dim"] not in best or int(h.get("confidence") or 1) > int(best[h["dim"]].get("confidence") or 1):
                best[h["dim"]] = h
    dims = [{"key": k, "label": labels.get(k, k), "value": v,
             "detail": (best.get(k) or {}).get("what", ""), "at": (best.get(k) or {}).get("t", "")}
            for k, v in (t.scores or {}).items() if k in labels and isinstance(v, int)]
    return {"kind": "take", "id": t.pk, "app_key": t.app_key,
            "rating": {"score": t.overall, "exact": r.get("exact"), "scores": t.scores or {},
                       "hook": r.get("hook"), "feelz": r.get("feelz"), "dimensions": dims},
            "report": {"verdict": r.get("verdict", ""), "strengths": r.get("strengths", []),
                       "fixes": r.get("fixes", []), "practice": r.get("practice", [])},
            "file": file, "genre": t.genre, "share_url": f"/s/{t.share_token}" if t.share_token else "",
            "open_in": {"tab": t.app_key, "target": f"{t.app_key}:progress"}}


def _promo_results(w, user):
    """How the link inside a promo post is doing — read NOW, so the same ledger row
    shows today's opens. None when this piece is not a promo, or its take has no
    link. `opens` is the public page's counter; nobody is named here."""
    tid = (w.inputs or {}).get("promo_take")
    if not tid:
        return None
    t = TakeScore.objects.filter(pk=tid, user=user).only("share_token", "app_key").first()
    if not t or not t.share_token:
        return None
    from .models import ScoreShare
    row = ScoreShare.objects.filter(token=t.share_token).only("views").first()
    return {"url": f"/s/{t.share_token}", "opens": row.views if row else 0,
            "open_in": {"tab": "viewz", "target": "viewz-links"}}


def _sentence(w, user=None):
    items = (w.inputs or {}).get("items") or []
    return {"kind": "sentence", "results": _promo_results(w, user) if user else None, "id": w.pk, "label": w.kind, "text": w.text[:1500],
            "rating": None, "report": {"items": [{"line": i.get("line", ""), "why": i.get("why", "")} for i in items]},
            "file": {"kept": True, "name": f"{w.kind}.txt", "url": None,
                     "why": "Kept in your Sentence ConnectZ library."},
            "open_in": {"tab": "sentenceconnectz", "target": "sentencez-write"}}


def outcomes_for(user, rows, request=None):
    """{ref: outcome} for the rows that have one. Only the member's OWN things:
    the lookup is filtered by user, so a forged ref reads as nothing."""
    refs = {r.get("ref") for r in rows if r.get("ref")}
    take_ids = [int(x.split(":", 1)[1]) for x in refs if x.startswith("take:") and x.split(":", 1)[1].isdigit()]
    sent_ids = [int(x.split(":", 1)[1]) for x in refs if x.startswith("sentence:") and x.split(":", 1)[1].isdigit()]
    out = {}
    if take_ids:
        for t in TakeScore.objects.filter(user=user, pk__in=take_ids).select_related("upload"):
            out[f"take:{t.pk}"] = _take(t, request)
    if sent_ids:
        for w in SentenceWork.objects.filter(user=user, pk__in=sent_ids):
            out[f"sentence:{w.pk}"] = _sentence(w, user)
    return out
