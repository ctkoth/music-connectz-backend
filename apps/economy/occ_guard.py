"""Two things OCC refuses to do itself, both checked BEFORE a model runs or a credit moves.

1. **Music ConnectZ's own code is not OCC's to hand out** (Corey's rule). OCC's tools
   only ever touch the member's own project files — it has no network and no git —
   so nobody can actually reach the repositories through it. What somebody CAN do
   is ask: "show me the Music ConnectZ backend", a TaskZ pointed at
   github.com/ctkoth/music-connectz-backend. Every such ask from anyone but the owner
   is refused with a sentence, written down, and the owner is told who and where.
   The owner is exempt: it is their code.

2. **Media goes to the app that makes it.** OCC is the coding agent. A request to
   make a picture, a video, a beat, lyrics or a master is answered with the
   Intelligence app that does that job properly — its own price, its own shape,
   its own royalty — instead of OCC improvising one and charging for it. Nothing
   is charged for being pointed elsewhere. A coding request that merely MENTIONS
   media ("add an image to my game") is not media, and `force` sends any request
   through anyway, because a guess that cannot be overridden is a wall.
"""
import logging
import re

from .models import Notification, is_platform_owner

logger = logging.getLogger(__name__)

_REPO = re.compile(
    r"(github\.com/)?ctkoth/\S*music-?connectz"
    r"|-?music-?connectz-(backend|frontend)-?"
    r"|\b(music ?connectz|mcz|this (app|platform|site))'?s? "
    r"(own )?(source( code)?|repo(sitory|s)?|code ?base|backend( code)?|server code|frontend code|git)\b",
    re.I)

REPO_REFUSAL = ("Music ConnectZ's own code isn't available through OCC — it's the owner's, and asking for it "
                "is flagged to them. OCC builds YOUR projects: tell it what to make.")


def repo_attempt(user, text, where):
    """The refusal sentence if `text` reaches for Music ConnectZ's repositories, else None.

    Logs and alerts the owner on every refusal. The owner themselves is never refused."""
    if not text or not _REPO.search(str(text)):
        return None
    if is_platform_owner(user):
        return None
    snippet = " ".join(str(text).split())[:120]
    logger.warning("OCC repo guard: %s (id %s) in %s — %r", user.username, user.id, where, snippet)
    try:
        from django.contrib.auth import get_user_model
        for owner in get_user_model().objects.filter(is_superuser=True)[:5]:
            Notification.objects.create(
                user=owner, actor=user, kind="system", item_id=f"occ-guard:{where}",
                text=f"⚠️ @{user.username} asked OCC ({where}) for Music ConnectZ's code — refused: “{snippet}”"[:280])
    except Exception:                                     # an alert must never decide the refusal
        logger.exception("OCC repo guard: couldn't notify the owner")
    return REPO_REFUSAL


# What each Intelligence app makes, as the nouns a member uses for it. Order matters:
# the first app whose nouns match wins, so "music video" is video before "music".
ROUTES = [
    ("videoconnectz", "Video ConnectZ",
     r"music video|bio video|promo(tional)? video|video|clip|reel|lip ?sync",
     "makes music, bio and promo videos, with your FaceZ photo if you like."),
    ("imageconnectz", "Image ConnectZ",
     r"album cover|song cover|cover art|profile pic(ture)?|avatar|wallpaper|background|banner|header image"
     r"|thumbnail|flyer|poster|logo|picture|image|photo|artwork|drawing|illustration",
     "makes pictures for a use: covers, profile pictures, banners, wallpapers, thumbnails and flyers."),
    ("instrumentalconnectz", "Instrumental ConnectZ",
     r"beat|instrumental|midi|melody|chord progression|drum loop|loop",
     "composes MIDI by genre, instruments, BPM and key."),
    ("mixconnectz", "Mix ConnectZ",
     r"master(ing)?|mixdown|mix (of )?(my|a|the|this) (song|track)",
     "masters a finished song on your device — loudness, tone, width, punch and peaks — and hands it back as WAV or MP3."),
    ("sentenceconnectz", "Sentence ConnectZ",
     r"lyrics|verse|chorus|hook|song|poem|essay|caption|social media post|bio|resume|cover letter"
     r"|artist contract|contract|royalt(y|ies) agreement",
     "writes lyrics, captions, posts, essays and agreements — in K-Oth's voice where it fits."),
]
_MAKE = r"\b(make|create|generate|draw|design|paint|render|produce|compose|write|record|shoot|master|mix)\b"
_CODE = re.compile(r"\b(game|app|website|site|web ?page|page|component|function|class|script|code|program"
                   r"|api|bot|css|html|javascript|python|button|sprite sheet|shader|database|level)\b", re.I)


def media_route(text):
    """{tab, label, why} when `text` asks OCC to MAKE media an Intelligence app makes, else None."""
    t = str(text or "")
    if not re.search(_MAKE, t, re.I) or _CODE.search(t):
        return None
    # "Master my song" / "mix my track": here the VERB is the job, so it is checked first —
    # otherwise "song" sends a mastering request to the lyric writer.
    if re.search(r"\b(master|mix)(ing)?\b(\W+\w+){0,3}?\W+(song|track|single|ep|album|beat)\b", t, re.I):
        tab, label, _, does = next(r for r in ROUTES if r[0] == "mixconnectz")
        return {"tab": tab, "label": label,
                "why": f"That's a job for {label}, which {does} It has its own price before you press, "
                       "and nothing was charged here. Ask OCC again with “build it anyway” to have OCC try."}
    for tab, label, nouns, does in ROUTES:
        # The noun has to come after the verb, within a few words — "write me lyrics",
        # "make a song cover" — so a sentence that only names a medium is left alone.
        if re.search(_MAKE + r"(\W+\w+){0,5}?\W+(" + nouns + r")\b", t, re.I):
            return {"tab": tab, "label": label,
                    "why": f"That's a job for {label}, which {does} It has its own price before you press, "
                           "and nothing was charged here. Ask OCC again with “build it anyway” to have OCC try."}
    return None
