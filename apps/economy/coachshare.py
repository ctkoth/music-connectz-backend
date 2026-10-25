"""The coach's read, shared WITH a post — and with its own visibility.

A member wants to post a song with the coach's feedback beside it, link it on
Reddit or TikTok, and have a stranger hear the song and see the score on the
same page. They also want the opposite on other days: a public song whose read
only signed-in members can see, or a read nobody but them ever sees. So the
read has its OWN setting, `Post.score_visibility`, separate from who may open
the post.

    ""         same as the post — whoever can see the post can see the read.
               This is what every post made before the setting existed has, so
               adding it moved nothing.
    "members"  signed-in members only. A stranger still hears the song and is
               shown a locked card in the read's place.
    "private"  the author alone. Nobody else is even told a read exists.

The read can never be WIDER than the post. There is no setting above "same as
the post", and a private post's read is private whatever the column says.

THE ONE RULE THIS FILE EXISTS FOR

Every place a post is handed to somebody other than its author goes through
`coach_read_for`. A second copy of "who may see the read" is how a members-only
score ends up in a link preview: the number is the only thing worth protecting,
and it is also the thing most likely to be copied into a serializer by someone
who only wanted the title. `test_coachshare` walks every serializer against a
viewer matrix and fails if any of them carries read content for a viewer the
function refused.

THE READ IS THE SERVER'S, NEVER THE CLIENT'S

A score posted beside a song is a claim — "the coach gave this 9/10" — so it is
only ever copied from a `ScoreShare` row the coach itself minted for that same
member (models.mint_score_share), by token. A request body that carries a
number, a verdict or a whole payload is ignored; the only thing the client
chooses is WHICH of its own reads. The same reason `PostsView` drops a
client-sent `score` on the way in.

What this cannot prove is that the song on the post is the file the coach
listened to: the coach reads the take it was sent, the post stores the file
that was uploaded, and nothing ties the two rows together. The read says WHEN
it was given and by whom (`coached_at`), and the screen prints that beside it.
"""
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from .instruments import INSTRUMENTS, SONG_SCORE, profile_for_app, scores_for
from .models import Post, ScoreShare, can_view_post

# The three things a member may choose. "" first: it is the default and the
# only value that does not need explaining to somebody who never opens the menu.
VISIBILITIES = ("", "members", "private")

# What a stranger is told when a read exists and is not theirs to see. Exact
# wording is Corey's ("It's free to join") and the screens render it as sent.
LOCKED_FOR_MEMBERS = "The coach's read on this song is for members. It's free to join."

REFUSE_VISIBILITY = ("Choose who sees the coach's read: the same people as the post, "
                     "members only, or only you.")
NEEDS_TOKEN = "Choose which coach read to post with this song."
NOT_YOURS = ("That coach read isn't one of yours. Only a read the coach gave one of "
             "your own takes can be posted with a song.")
NO_PAYLOAD = ("That read was saved before reads could be posted with a song, so only its "
              "score card exists. Run the take through the coach once more and post that read.")
ONLY_AUTHOR = "Only the member who published this can change its coach read."

# What of a stored read is ever handed out. A whitelist, not a strip-down: this
# is copied onto a post that strangers can open, and a deny-list quietly serves
# whatever the coach adds to its answer later.
_NUMBERS = ("score", "song_score")
_TEXT = ("verdict", "now", "goal", "range_profile", "style_fit", "song_why",
         "lyrics_read", "lyrics_note", "wit_note", "mix_note", "next_drill")
_LISTS = ("strengths", "fixes", "rated_extras", "counted_extras")
_FLAGS = ("rated_lyrics", "rated_mix")
_TEXT = _TEXT + ("hook_why", "feelz_why", "feelz_emotion")
_NUMBERS = _NUMBERS + ("hook_score", "feelz_score", "score_exact")
# Lists of server-cleaned dicts (HookZ / FeelZ rows with their tips, and mix suggestions). Copied from the
# share row, which the server built; re-cleaned on the way OUT as well, because a stored read is read for years.
_ROWS = ("extras", "mix_tips")
_KEEP = _NUMBERS + _TEXT + _LISTS + _FLAGS + ("scores",) + _ROWS


def clean_visibility(value):
    """(setting, None) for a valid value, (None, sentence) for junk.

    `None` in means "not sent", which is not an error — the caller keeps what
    the post already has. Junk is refused rather than coerced to the default,
    because the default is the WIDEST setting: a typo must never be the thing
    that publishes a score somebody meant to keep.
    """
    if value is None:
        return None, None
    v = str(value).strip().lower()
    if v in VISIBILITIES:
        return v, None
    return None, REFUSE_VISIBILITY


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def stored_read(post):
    """The coach read kept on a post, or None when it does not hold one.

    "Holds one" is stricter than "has a `score` column that is not empty". The
    column also carries OCC's provenance (`{"occ": …}`) and, before this file,
    whatever a client chose to POST. A read has an integer overall score, an
    instrument this server can label, and a provenance mark the coach itself
    writes: `coached_by` (vocalcoach._save_to_post) or `source == "share"`
    (attach below). A dict without them is not served as the coach's word.
    """
    s = getattr(post, "score", None)
    if not isinstance(s, dict) or not _is_int(s.get("score")):
        return None
    if str(s.get("app_key") or "").lower() not in INSTRUMENTS:
        return None
    if not (s.get("coached_by") or s.get("source") == "share"):
        return None
    return s


def legacy_score(post, coach):
    """The `score` key every post dict has always carried.

    Present in full only when the read is shown — the old key is the same
    content as `coach.read`, so leaving it populated for a viewer the read was
    refused would be the leak with a different name. Anything else the column
    holds that is not a read (OCC's provenance) is served exactly as before.
    """
    s = post.score if isinstance(post.score, dict) else {}
    if coach.get("state") == "shown":
        return s
    return {"occ": s["occ"]} if "occ" in s else {}


def _labels(stored):
    app_key = str(stored.get("app_key")).lower()
    return scores_for(app_key, lyrics=bool(stored.get("rated_lyrics")),
                      mix=bool(stored.get("rated_mix")),
                      extras=tuple(stored.get("rated_extras") or ()))


def read_view(stored):
    """The read as a viewer gets it: only what is labelled, plus the labels.

    A dimension the server cannot name is dropped rather than served as a bare
    number — a number with no meaning beside it teaches the wrong thing, and a
    missing label means the coach and this file disagree about what exists,
    which is a bug to see in a test and not a number to show a stranger.
    """
    app_key = str(stored.get("app_key")).lower()
    names = _labels(stored)
    scores = {k: v for k, v in (stored.get("scores") or {}).items()
              if k in names and _is_int(v)}
    out = {
        "app_key": app_key,
        "label": profile_for_app(app_key)["label"],
        "score": stored["score"],
        "scores": scores,
        "labels": {k: names[k] for k in scores},
        # What one take can and cannot show, on the same card as the number. A
        # score with no scope beside it is read as a verdict on the singer.
        "caveat": profile_for_app(app_key)["caveat"],
        "coached_by": str(stored.get("coached_by") or ""),
        "coached_at": str(stored.get("coached_at") or ""),
        # Where the read came from, so the card is not a dead end: members open
        # the progress screen of the app that gave it.
        "open_in": app_key,
        "target": f"{app_key}-progress",
    }
    for k in _TEXT:
        if stored.get(k):
            out[k] = str(stored[k])
    for k in _LISTS:
        v = stored.get(k)
        out[k] = [str(x) for x in v][:6] if isinstance(v, list) else []
    if _is_int(stored.get("song_score")):
        out["song_score"] = stored["song_score"]
        out["labels"]["song_score"] = SONG_SCORE["song_score"]
    if isinstance(stored.get("score_exact"), (int, float)):
        out["score_exact"] = stored["score_exact"]
    from .scoreshare import clean_extras, clean_mix
    ex, mix = clean_extras(stored.get("extras")), clean_mix(stored.get("mix_tips"))
    if ex:
        out["extras"] = ex
    if mix:
        out["mix_tips"] = mix
    return out


def _authed(viewer):
    return bool(getattr(viewer, "is_authenticated", False))


def _get_yours(post, stored):
    """The way a stranger takes their own free take, with the author's handle as
    the referral code — exactly what the shared score card already does."""
    app_key = str(stored.get("app_key")).lower()
    return {"app_key": app_key, "label": profile_for_app(app_key)["label"],
            "path": f"/try/{app_key}?ref={post.author.username}"}


def coach_read_for(post, viewer):
    """What `viewer` may see of the coach's read on `post`.

        {"state": "none"}                          no read, or not theirs to know about
        {"state": "locked", "reason": …}           a read exists; they may not see it
        {"state": "shown", "read": {…}, "public": bool}

    `visibility` (the author's own setting) rides along for the AUTHOR only —
    a stranger has no business learning how somebody configured their post.

    No query, ever. It reads the row it is handed, which is what lets the feed
    call it per card and stay at the same query count; `owns_post` and
    `can_view_post` read the post's own JSON columns, not the database.

    The rules, in the order they bite:
      * no read → none
      * the author → shown, always
      * the post is not visible to the viewer → none (the post is refused first)
      * the member who ran the coach on it → shown (it was their own answer)
      * "private", or a private post → none. NOT locked: "only me" means nobody
        is told there is anything to ask for.
      * an authenticated viewer → shown, for "" and "members"
      * a stranger → shown for "", locked for "members"
    """
    setting = post.score_visibility or ""
    is_author = _authed(viewer) and post.author_id == viewer.id
    base = {"visibility": setting} if is_author else {}
    stored = stored_read(post)
    if stored is None:
        return {"state": "none", **base}

    def shown():
        return {"state": "shown", **base, "read": read_view(stored),
                "public": post.visibility == "public" and setting == "",
                "get_yours": _get_yours(post, stored)}

    if is_author:
        return shown()
    if not can_view_post(post, viewer):
        return {"state": "none"}
    # Whoever ran the coach on this post keeps seeing their own answer, even
    # when the author has made it "only me" — a credited contributor who paid
    # for the read has already seen it, and hiding it from them would only
    # hide it from the person it was for.
    if _authed(viewer) and stored.get("coached_by") == viewer.username:
        return shown()
    if setting == "private" or post.visibility == "private":
        return {"state": "none"}
    if _authed(viewer):
        return shown()
    # A stranger, and the post is public (it is the only kind they can open).
    if setting == "members":
        return {"state": "locked", "reason": LOCKED_FOR_MEMBERS,
                "app_key": str(stored["app_key"]).lower(),
                "label": profile_for_app(str(stored["app_key"]).lower())["label"],
                "get_yours": _get_yours(post, stored)}
    return shown()


def public_read(post):
    """The read as a stranger would get it, or None — the question every link
    preview and card image asks. Stated as its own function so those callers
    cannot forget which viewer they are."""
    c = coach_read_for(post, None)
    return c["read"] if c["state"] == "shown" else None


def card_dict(post, read):
    """What `scoreshare.render_card` draws for a read that lives on a post."""
    from .scoreshare import short_verdict
    return {"label": read["label"], "genre": post.genre or "", "score": read["score"],
            "verdict": short_verdict(read.get("verdict", "")),
            "extras": read.get("extras") or [],
            "username": post.author.username}


# ---- attaching ----------------------------------------------------------

def share_for(user, token):
    """(ScoreShare, None) when `token` is one of THIS member's own reads and
    carries the whole read; (None, sentence) otherwise.

    One sentence for "no such token" and "somebody else's": telling them apart
    would let a member probe which tokens exist.
    """
    t = str(token or "").strip().rsplit("/", 1)[-1][:64]
    if not t:
        return None, NEEDS_TOKEN
    row = ScoreShare.objects.filter(token=t, user_id=user.id).first()
    if row is None:
        return None, NOT_YOURS
    payload = row.payload if isinstance(row.payload, dict) else {}
    if not _is_int(payload.get("score")) or row.app_key.lower() not in INSTRUMENTS:
        return None, NO_PAYLOAD
    return row, None


def read_from_share(row):
    """The dict stored on a post: the coach's own fields from the share row and
    the provenance marks, nothing from the request."""
    p = row.payload
    out = {k: p[k] for k in _KEEP if k in p}
    out.update({
        "app_key": row.app_key.lower(),
        "coached_by": row.user.username if row.user_id else "",
        "coached_at": row.created_at.isoformat(),
        "source": "share",
        "share_token": row.token,
    })
    return out


def _keep_occ(post):
    s = post.score if isinstance(post.score, dict) else {}
    return {"occ": s["occ"]} if "occ" in s else {}


def for_new_post(user, d):
    """(score_dict, visibility, error) for a post being created.

    `error` is a payload for a 400, or None. Called BEFORE anything is charged,
    so a refused token costs nothing. `score_dict` is {} when no token was sent;
    the visibility is validated either way, because "only me" set ahead of a
    later read protects that read when it lands.
    """
    vis, err = clean_visibility(d.get("score_visibility"))
    if err:
        return {}, "", {"detail": err}
    token = d.get("coach_token")
    if token in (None, ""):
        return {}, vis or "", None
    row, err = share_for(user, token)
    if err:
        return {}, "", {"detail": err}
    return read_from_share(row), vis or "", None


class PostCoachView(APIView):
    """/api/economy/postz/<pk>/coach/

    GET     what the caller may see of this post's read (same object as `coach`,
            plus `post_visibility`)
    POST    {share_token, score_visibility?} attach one of your own reads
    DELETE  take the read off the post

    Attaching and removing are the AUTHOR's. They are settings about a score,
    not edits to the post's content, so neither is held to the tier's edit
    window — the same reasoning that exempts `visibility` and `allow_in_playlists`.
    Neither costs anything: the read was already paid for when the coach gave it.
    """

    def get_permissions(self):
        return [AllowAny()] if self.request.method == "GET" else [IsAuthenticated()]

    def _post(self, request, pk):
        post = Post.objects.filter(pk=pk).select_related("author", "author__membership").first()
        # 404, never 403: confirming a post you cannot see exists is the leak.
        if not post or not can_view_post(post, request.user):
            return None, Response({"detail": "post not found"}, status=status.HTTP_404_NOT_FOUND)
        return post, None

    def get(self, request, pk):
        post, miss = self._post(request, pk)
        if miss:
            return miss
        # `post_visibility` is who can open the post — something this viewer can
        # already tell (they got past can_view_post), and what the screen needs to
        # say what each read setting would mean for THIS post.
        return Response({**coach_read_for(post, request.user),
                         "post_visibility": post.visibility})

    def _reply(self, request, post):
        from .postz import _post_dict
        return Response(_post_dict(post, request))

    def post(self, request, pk):
        post, miss = self._post(request, pk)
        if miss:
            return miss
        if post.author_id != request.user.id:
            return Response({"detail": ONLY_AUTHOR}, status=status.HTTP_403_FORBIDDEN)
        d = request.data
        vis, err = clean_visibility(d.get("score_visibility"))
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
        row, err = share_for(request.user, d.get("share_token"))
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
        post.score = {**_keep_occ(post), **read_from_share(row)}
        fields = ["score"]
        if vis is not None:
            post.score_visibility = vis
            fields.append("score_visibility")
        post.save(update_fields=fields)
        return self._reply(request, post)

    def delete(self, request, pk):
        post, miss = self._post(request, pk)
        if miss:
            return miss
        if post.author_id != request.user.id:
            return Response({"detail": ONLY_AUTHOR}, status=status.HTTP_403_FORBIDDEN)
        # The setting stays. Removing a read is not a decision about the next
        # one, and a member who chose "only me" and then re-coached the post
        # should not find the new read quietly wider than the last.
        post.score = _keep_occ(post)
        post.save(update_fields=["score"])
        return self._reply(request, post)


def post_coach_card(request, pk):
    """GET /api/economy/postz/<pk>/coach-card.png[?format=story]

    The score card for a read that lives on a post, drawn from the stored read
    and ONLY when a stranger is allowed to see that read. That is the point of
    having it: this URL is what a link preview embeds, and a crawler is a
    stranger. 404 otherwise, so narrowing the setting takes the image down at
    once and no token has to be remembered and revoked.
    """
    from .scoreshare import render_card, wants_story
    post = get_object_or_404(Post.objects.select_related("author"), pk=pk)
    read = public_read(post) if can_view_post(post, None) else None
    if read is None:
        return HttpResponse(status=404)
    resp = HttpResponse(render_card(card_dict(post, read), story=wants_story(request)),
                        content_type="image/png")
    # Short, because unlike a share row this can be taken back.
    resp["Cache-Control"] = "public, max-age=300"
    return resp
