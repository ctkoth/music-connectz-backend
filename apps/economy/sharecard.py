"""Server-rendered link previews for the pages worth sharing.

`public/sitemap.xml` already names this gap in its own comment: `/u/<username>`,
`/p/<id>` and `/pl/<id>` are "the pages worth indexing most, and they need a
per-URL title and description the SPA cannot give them."

It is worse than an SEO problem. Every social crawler — Facebook, X, LinkedIn,
iMessage, WhatsApp, Discord, Slack — reads the STATIC HTML and does not run
JavaScript. `index.html` carries one fixed `og:title` and one `og:image`, so
every link anybody has ever shared out of this platform previewed as
"Music ConnectZ — Connect Through Music" with the house card. Share a member's
profile: the house card. Share a scored take: the house card.

For a platform whose cheapest growth channel is a member posting their own
score, that is the growth loop broken at the last inch — the thing being shared
is the one thing the preview does not mention.

`document.title` in the client fixes the browser tab and eventually Google,
which does render JS. It cannot fix a share card, because the crawler has left
before React starts. So this renders real HTML, server-side, with the tags
filled in from the same functions that serve the JSON.

It is not a second copy of the app. It is a preview document: the tags, the
content in visible text so a crawler that reads body copy sees the same thing
the tags claim, and an immediate redirect into the SPA for anybody with a
browser. Same content to both, which is what keeps this the opposite of
cloaking.
"""
import html

from django.http import HttpResponse
from django.utils.html import escape

from .models import Post, Profile, can_view_post
from .publicz import public_profile_dict

SITE = "https://musicconnectz.net"


def _doc(*, path, title, description, image, body):
    """One preview document. Tags for the crawler, text for the reader, and a
    redirect for the browser — in that order, because the tags have to be in
    the head before anything else can go wrong."""
    url = f"{SITE}{path}"
    t, d = escape(title)[:120], escape(description)[:300]
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{t}</title>
<meta name="description" content="{d}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="profile">
<meta property="og:site_name" content="Music ConnectZ">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{t}">
<meta property="og:description" content="{d}">
<meta property="og:image" content="{escape(image)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{t}">
<meta name="twitter:description" content="{d}">
<meta name="twitter:image" content="{escape(image)}">
<!-- A reader gets the app. The crawler has already read the head and stopped,
     so this costs it nothing; a human sees this document for one frame. -->
<script>location.replace({html.escape(repr(path), quote=False).replace("'", '"')});</script>
</head><body>
<h1>{t}</h1>
<p>{d}</p>
{body}
<p><a href="{url}">Open on Music ConnectZ</a></p>
</body></html>"""


def profile_card(request, username):
    p = Profile.objects.filter(user__username__iexact=username).select_related("user").first()
    if not p:
        return HttpResponse(status=404)
    d = public_profile_dict(p)
    name = d["display_name"]
    # Their skills are the reason a stranger would care, so they are the
    # description — not the site's tagline repeated under somebody's name.
    skills = [s["name"] for per in d.get("personas", []) for s in per.get("skills", [])][:6]
    desc = (d.get("bio") or "").strip()
    if skills:
        desc = (desc + "  " if desc else "") + "Skills: " + ", ".join(skills) + "."
    if not desc:
        desc = f"{name} makes music on Music ConnectZ."
    body = "".join(f"<li>{escape(s)}</li>" for s in skills)
    return HttpResponse(_doc(
        path=f"/u/{p.user.username}",
        title=f"{name} — Music ConnectZ",
        description=desc,
        # The house card, NOT the member's avatar. `Profile.avatar` exists and
        # would make this card far more clickable — a face beats a logo every
        # time — but nothing public serves it today: `public_profile_dict`
        # omits it and the public profile page does not render it. Putting it
        # here would publish somebody's face to everyone who sees a link
        # they did not post, as a side effect of an SEO change. That is a
        # disclosure decision, so it is Corey's, not this file's.
        image=f"{SITE}/og-card.png",
        body=f"<ul>{body}</ul>" if body else "",
    ), content_type="text/html; charset=utf-8")


def post_card(request, pk):
    post = Post.objects.filter(pk=pk).select_related("author").first()
    # The same visibility rule the JSON endpoint uses. A private post must not
    # leak its title through a link preview, which would be a real disclosure
    # dressed as a nicety.
    if not post or not can_view_post(post, None):
        return HttpResponse(status=404)
    author = post.author.username
    title = (post.title or "Untitled").strip()
    desc = (post.description or "").strip() or f"A track by {author} on Music ConnectZ."
    score = ""
    if isinstance(post.score, dict) and post.score.get("score") is not None:
        # The score is the shareable part — it is what somebody posts to show.
        score = f" Scored {post.score['score']}/10 by the coach."
    return HttpResponse(_doc(
        path=f"/p/{post.pk}",
        title=f"{title} — {author} on Music ConnectZ",
        description=(desc + score)[:300],
        image=f"{SITE}/og-card.png",
        body=f"<p>By {escape(author)}.</p>",
    ), content_type="text/html; charset=utf-8")
