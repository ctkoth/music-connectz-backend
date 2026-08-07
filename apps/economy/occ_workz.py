"""OCC WorkZ — what you gave OCC, what it gave back, and where that goes next.

OCC could take a prompt and print an answer, and that was the end of it. An
answer you can't rate, can't show anyone and can't carry into another app is a
dead end with a scrollbar — which is the one thing this app has decided nothing
is allowed to be.

So an OCC result is a record, and it is shaped like a post:

* **In** — `input_text` and `input_items`: the prompt and the attachments. Kept
  because "what did I actually ask for" is the first question anyone has when
  they open an output a week later.
* **Out** — the PostZ field names verbatim: title, description, media_type /
  media_url, image_url, lyrics, items. Sharing is then a copy, not a
  translation, and it goes through `postz.create_post` — the same daily cap,
  the same energy charge, the same sanitizing the composer uses. A second
  creation path is how one surface quietly stops charging for what the other
  charges for.

**Rating, likes and comments are not reimplemented here.** They ride the shared
item space. Before a share there is no `item_key` at all: until another member
can open the thing, an item key collects nothing, and publishing one anyway
would put a rating count on a screen the data can never fill.

**The price is stated before the button, not after it.** Every unshared output
carries `share_cost` — the energy the post will charge — so nobody discovers
what sharing costs by having paid it.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import over_char_limit
from .models import (
    OccOutput,
    OccTask,
    Post,
    item_rating_median,
    membership_for,
)
from .occ_spec import EXPORT_ROUTES
from .postz import clean_items, create_post, post_cost_cents

# What OCC hands back when it hands back a file. Anything else routes as a
# document, because text is a document and pretending otherwise sends a written
# answer to a media library that can't open it.
DEFAULT_ROUTE = "document"


def _route_for(o):
    """Where this work belongs, by what it actually is."""
    key = (o.media_type or "").strip().lower()
    if key not in EXPORT_ROUTES:
        key = "image" if o.image_url else DEFAULT_ROUTE
    return key, EXPORT_ROUTES[key]


def _send_targets(o):
    """Every app this work can move into, and honestly whether it can yet.

    A row that says "open in PlaylistZ" and then drops you into an empty
    playlist has told you nothing. So each target carries whether it needs the
    work shared first, and once it IS shared the post id is right there for the
    client to land on.
    """
    _, route = _route_for(o)
    shared = bool(o.shared_post_id)
    post_target = f"post-{o.shared_post_id}" if shared else ""
    audio = (o.media_type or "").lower() == "audio"
    return [
        {"key": "postz", "label": "Share to PostZ", "tab": "social",
         "target": post_target or "social-compose", "needs_share": False,
         "done": shared,
         "note": "Where it gets rated, liked, disliked and commented on."},
        {"key": route["app"], "label": f"Open in {route['app'].title()}",
         "tab": route["app"], "target": route["target"], "needs_share": False,
         "done": False,
         "note": "The library for this kind of file."},
        # PostZ is for show, CollabZ is for collaboration — and the PostZ →
        # CollabZ handoff already exists, so this rides it rather than growing a
        # second way to start a deal.
        {"key": "collabz", "label": "Take it into CollabZ", "tab": "collabz",
         "target": post_target, "needs_share": True, "done": False,
         "from_post": o.shared_post_id,
         "note": "Share it first — a deal is built on the post."},
        {"key": "playlistz", "label": "Add to a PlaylistZ", "tab": "playlistz",
         "target": post_target, "needs_share": True,
         "done": False, "available": audio or bool(o.media_url),
         "note": "Share it first — playlists hold posts."},
    ]


def output_dict(o, request=None):
    route_key, route = _route_for(o)
    shared = bool(o.shared_post_id)
    return {
        "id": o.id,
        "tab": o.tab,
        "task_id": o.task_id,
        # ---- what went in
        "input_text": o.input_text,
        "input_items": o.input_items or [],
        # ---- what came out, in the PostZ format
        "title": o.title,
        "description": o.description,
        "media_type": o.media_type,
        "media_url": o.media_url,
        "image_url": o.image_url,
        "lyrics": o.lyrics,
        "items": o.items or [],
        "genre": o.genre,
        "skills_used": o.skills_used or [],
        "skill_cost_cents": o.skill_cost_cents,
        # ---- shared or not, and what that means
        "shared": shared,
        "post_id": o.shared_post_id,
        # Null until shared, on purpose — see the module docstring.
        "item_key": o.item_key,
        "rating": item_rating_median(o.item_key) if shared else None,
        "post_url": (f"/p/{o.shared_post_id}"
                     if shared and o.shared_post and o.shared_post.visibility == "public" else ""),
        # ---- the price, before the button
        # Quoted by the SAME function that charges it. This used to read the
        # stored skill_cost_cents while create_post priced from the member's
        # PersonaZ rates, so WorkZ advertised one number and the post took
        # another — two sources of truth for one price.
        "share_cost": {"resource": "energy",
                       "amount": post_cost_cents(o.user, o.skills_used or [])[0]},
        "share_gain": {"resource": "spinaz", "note": "Restricted posts pay you per join; "
                                                     "ratings and comments arrive on the post."},
        # ---- where it goes next
        "export_route": route_key,
        "open_in": route["app"],
        "send_to": _send_targets(o),
        "created_at": o.created_at.isoformat(),
        "updated_at": o.updated_at.isoformat(),
    }


def _clean_fields(d, existing=None):
    """The PostZ-shaped half of the payload, sanitized to the same widths."""
    e = existing
    return {
        "title": (str(d.get("title", e.title if e else "")).strip()[:160]),
        "description": str(d.get("description", e.description if e else ""))[:20000],
        "media_type": str(d.get("media_type", e.media_type if e else "")).strip()[:24],
        "media_url": str(d.get("media_url", e.media_url if e else "")).strip()[:500],
        "image_url": str(d.get("image_url", e.image_url if e else "")).strip()[:500],
        "lyrics": str(d.get("lyrics", e.lyrics if e else ""))[:8000],
        "items": clean_items(d["items"]) if isinstance(d.get("items"), list)
                 else (e.items if e else []),
        "genre": str(d.get("genre", e.genre if e else ""))[:40],
        "skills_used": [str(x)[:60] for x in (d.get("skills_used") or
                        (e.skills_used if e else []) or [])
                        if isinstance(x, (str, int))][:40],
        "skill_cost_cents": max(0, int(d.get("skill_cost_cents",
                                             e.skill_cost_cents if e else 0) or 0)),
    }


class OccWorkzView(APIView):
    """GET my OCC work; POST records a new input/output pair."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (OccOutput.objects.filter(user=request.user)
              .select_related("shared_post"))
        tab = request.query_params.get("tab")
        if tab:
            qs = qs.filter(tab=tab[:32])
        task = request.query_params.get("task")
        if task and task.isdigit():
            qs = qs.filter(task_id=int(task))
        if request.query_params.get("shared") == "1":
            qs = qs.exclude(shared_post__isnull=True)
        works = [output_dict(o, request) for o in qs[:200]]
        return Response({
            "works": works,
            "shared": sum(1 for w in works if w["shared"]),
            # The export table itself, so the client offers exactly the routes
            # the server will honour rather than a menu of its own.
            "export_routes": EXPORT_ROUTES,
        })

    def post(self, request):
        d = request.data or {}
        fields = _clean_fields(d)
        input_text = str(d.get("input_text", "") or "")
        input_items = clean_items(d.get("input_items"))
        if not (fields["title"] or fields["description"] or fields["media_url"]
                or fields["image_url"] or fields["items"]):
            return Response(
                {"detail": "There's nothing here to keep — give it a title, some text, "
                           "or a file."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # The prompt is the member's own writing, so it answers to their tier's
        # character limit — never to a column width.
        cap = over_char_limit(input_text, membership_for(request.user).tier)
        if cap:
            return Response(
                {"detail": f"That input is over your {cap:,}-character limit — "
                           "upgrade in MembershipZ for more room.",
                 "char_limit": cap},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not fields["title"]:
            # Untitled work is unfindable work. Take the first line of whatever
            # there is rather than refusing over a field the member didn't know
            # mattered.
            source = fields["description"] or input_text
            fields["title"] = (source.strip().splitlines() or ["OCC work"])[0][:160]

        task = None
        if d.get("task_id"):
            task = OccTask.objects.filter(pk=d["task_id"], user=request.user).first()
            if not task:
                return Response({"detail": "task not found"}, status=status.HTTP_404_NOT_FOUND)

        o = OccOutput.objects.create(
            user=request.user, task=task, tab=str(d.get("tab", "") or "")[:32],
            input_text=input_text, input_items=input_items, **fields,
        )
        return Response(output_dict(o, request), status=status.HTTP_201_CREATED)


class OccWorkDetailView(APIView):
    """GET one; PATCH edits it; DELETE removes it."""

    permission_classes = [IsAuthenticated]

    def _get(self, request, pk):
        return (OccOutput.objects.filter(pk=pk, user=request.user)
                .select_related("shared_post").first())

    def get(self, request, pk):
        o = self._get(request, pk)
        if not o:
            return Response({"detail": "work not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(output_dict(o, request))

    def patch(self, request, pk):
        o = self._get(request, pk)
        if not o:
            return Response({"detail": "work not found"}, status=status.HTTP_404_NOT_FOUND)
        d = request.data or {}
        for k, v in _clean_fields(d, o).items():
            setattr(o, k, v)
        if "input_text" in d:
            text = str(d["input_text"] or "")
            cap = over_char_limit(text, membership_for(request.user).tier)
            if cap:
                return Response(
                    {"detail": f"That input is over your {cap:,}-character limit.",
                     "char_limit": cap},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            o.input_text = text
        if isinstance(d.get("input_items"), list):
            o.input_items = clean_items(d["input_items"])
        if "tab" in d:
            o.tab = str(d["tab"] or "")[:32]
        o.save()
        return Response(output_dict(o, request))

    def delete(self, request, pk):
        o = self._get(request, pk)
        if not o:
            return Response({"detail": "work not found"}, status=status.HTTP_404_NOT_FOUND)
        # The post outlives the working copy. Deleting your notes shouldn't
        # silently retract something other members have already rated.
        post_id = o.shared_post_id
        o.delete()
        return Response({"deleted": True, "post_id": post_id,
                         "note": ("The post stays up — delete it in PostZ if you want it gone."
                                  if post_id else "")})


class OccWorkShareView(APIView):
    """POST /api/economy/occ/workz/<pk>/share/ — publish it as a post.

    This is the whole point: the moment an OCC output becomes something other
    members can rate, like, dislike and comment on. It creates a REAL post
    through the composer's own code path, so the daily submission cap and the
    energy charge apply exactly as they would if the member had typed it in.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        o = (OccOutput.objects.filter(pk=pk, user=request.user)
             .select_related("shared_post").first())
        if not o:
            return Response({"detail": "work not found"}, status=status.HTTP_404_NOT_FOUND)
        if o.shared_post_id:
            # Sharing twice makes two posts competing for the same ratings.
            return Response(
                {"detail": "This one is already posted.", **output_dict(o, request)},
                status=status.HTTP_409_CONFLICT,
            )
        d = request.data or {}

        # Nothing is lost in the copy: an image and a script are album entries
        # when the post's single media slot is already taken by the audio/video.
        items = list(o.items or [])
        if o.image_url and not any(i.get("url") == o.image_url for i in items):
            items.append({"url": o.image_url, "type": "image",
                          "title": f"{o.title} (image)"[:160], "lyrics": ""})
        if o.lyrics and not any(i.get("lyrics") == o.lyrics for i in items):
            items.append({"url": "", "type": "text",
                          "title": f"{o.title} (script)"[:160], "lyrics": o.lyrics})

        payload = {
            "title": str(d.get("title") or o.title)[:160],
            "description": str(d.get("description") or o.description),
            "media_type": o.media_type,
            "media_url": o.media_url,
            "items": items,
            "genre": d.get("genre", o.genre),
            "skills_used": d.get("skills_used", o.skills_used),
            "visibility": d.get("visibility", "public"),
            "allow_in_playlists": d.get("allow_in_playlists", True),
            # Where it came from, on the post itself — so a member reading the
            # post can see the work was made in OCC and with what prompt.
            "score": {"occ": {"work_id": o.id, "tab": o.tab,
                              "input": o.input_text[:2000]}},
        }
        post, info, err = create_post(request.user, payload)
        if err:
            return Response(err[0], status=err[1])
        o.shared_post = post
        o.save(update_fields=["shared_post", "updated_at"])
        o.refresh_from_db()
        return Response({**output_dict(o, request), **info},
                        status=status.HTTP_201_CREATED)


class OccWorkUnshareView(APIView):
    """POST .../unshare/ — let go of the post without losing the work.

    It does NOT delete the post. Retracting something other members have rated
    is a separate decision, made in PostZ where the ratings are visible.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        o = (OccOutput.objects.filter(pk=pk, user=request.user)
             .select_related("shared_post").first())
        if not o:
            return Response({"detail": "work not found"}, status=status.HTTP_404_NOT_FOUND)
        if not o.shared_post_id:
            return Response({"detail": "That one isn't posted."},
                            status=status.HTTP_409_CONFLICT)
        post_id = o.shared_post_id
        o.shared_post = None
        o.save(update_fields=["shared_post", "updated_at"])
        return Response({**output_dict(o, request), "unlinked_post": post_id,
                         "note": "The post is still up — delete it in PostZ if you want it gone.",
                         "open_in": "social", "target": f"post-{post_id}"})


class PostOccWorkView(APIView):
    """GET /api/economy/postz/<pk>/occ/ — the OCC work behind a post.

    The return leg. A post made in OCC can be opened back in OCC with its
    original prompt, which is how someone iterates on it instead of starting
    over.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        post = Post.objects.filter(pk=pk).first()
        if not post:
            return Response({"detail": "post not found"}, status=status.HTTP_404_NOT_FOUND)
        o = OccOutput.objects.filter(shared_post_id=pk).select_related("shared_post").first()
        if not o:
            return Response({"work": None})
        mine = o.user_id == request.user.id
        return Response({
            # Only the author gets the prompt back. Other members get to know it
            # was made in OCC — the prompt is the author's working material.
            "work": output_dict(o, request) if mine else {
                "id": o.id, "tab": o.tab, "made_in": "occ",
                "created_at": o.created_at.isoformat(),
            },
            "mine": mine,
            "open_in": "occ" if mine else None,
            "target": f"occ:workz:{o.id}" if mine else "",
        })
