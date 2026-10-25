"""Every credit spent buys something — and this is the list that says what.

Corey's rule: **a credit is only spent on something tangible, shareable,
understandable, lucrative, braggable or learnable.** A resource that leaves and
buys nothing a member can keep, show, understand, earn from or learn from is a
fee, and this platform does not charge fees. That is the substance rule applied
to the wallet.

So every module that spends a resource is declared here, once, with:

* `resource`  — what leaves (promptz, spinaz, energy);
* `buys`      — one plain sentence on what the member gets for it;
* `outcomes`  — which of the six it delivers (at least one, always a subset of
                OUTCOMES);
* `lands_in`  — the tabs where the thing can be USED, which is the
                cross-pollination rule for a purchase: nothing bought is a dead end;
* `free_way`  — where the same value is available without spending, OR
  `no_free_way` — the honest reason there isn't one. One of the two, never
                neither: a member who can learn it for free should be told.

Corey's second rule, narrower: **every PromptZ spend specifically — the resource
that costs real Gemini/Anthropic money, not SpinaZ or Energy — must leave the
member something tangible: saved, reopenable, and exportable or shareable.**
A reply shown once and gone is a spend with nothing to show for it, however
"understandable" or "learnable" it was. So a `resource: "promptz"` entry must
include `"tangible"` in its `outcomes`, OR declare `ephemeral_reason` — the
stated reason it deliberately keeps nothing (a preview before a choice, a
privacy-sensitive reading never stored), same shape as `free_way`/
`no_free_way`: one of the two, never silently neither.

`test_credit_outcomes` is the enforcement. It walks the source, finds every
module that calls a spend primitive, and fails if one is not declared here — so
a NEW way to spend credits cannot ship without saying what it buys, and a
declared one that stops spending cannot linger as a claim about code that is
gone. `GET /api/economy/creditz/` publishes the list: the price of a credit is
what it buys, and a member can read it before spending one.
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

OUTCOMES = {
    "tangible": "A thing you keep — saved to your library, yours to open again.",
    "shareable": "Something you can send, post or link to.",
    "understandable": "It tells you WHY, in words, not just a number.",
    "lucrative": "It can earn: a royalty, a payout, winnings, a listing.",
    "braggable": "A score, rank or result worth showing off.",
    "learnable": "You come away knowing how to do it better.",
}

# The primitives that move a credit OUT. A module calling any of these is a spend.
SPEND_PRIMITIVES = ("charge_ai_usage", "_bill", "spend_spinaz", "charge_skill_energy",
                    "_spend_energy_up_to", "spend_energy")

COACH_FREE = {"label": "A daily free allowance covers a coached take before any credit is touched, "
                       "and the drills and breath training are free.", "tab": "breathz"}

CREDIT_OUTCOMES = {
    "vocalcoach": {
        "resource": "promptz", "label": "Coached take",
        "buys": "A scored take: the number, why you got it, what worked, what to fix, HookZ and FeelZ, "
                "and what to practise — kept in your history.",
        "outcomes": ["understandable", "learnable", "shareable", "braggable", "tangible"],
        "lands_in": ["singz", "rapz", "postz", "messagez", "journalz", "sentenceconnectz"],
        "free_way": COACH_FREE},
    "matchref": {
        "resource": "promptz", "label": "Match a reference",
        "buys": "Your take heard against a song you want to sound like: what separates them, in "
                "dimensions, EQ by ear, how-to and lyric direction (never their words). Nothing is kept.",
        "outcomes": ["learnable", "understandable"],
        "lands_in": ["singz", "rapz", "sentenceconnectz"],
        "ephemeral_reason": "The reference is somebody else's record, so it is never stored, and a gap to "
                            "it is not a measurement of you; the read is shown once to act on.",
        "free_way": COACH_FREE},
    "coach_upgrades": {
        "resource": "promptz", "label": "Gear and settings advice",
        "buys": "Named gear and settings advice tied to the reasons in one take.",
        "outcomes": ["learnable", "understandable", "tangible"],
        "lands_in": ["singz", "rapz"],
        "no_free_way": "It names specific gear and settings for one take; the free read already says what to fix."},
    "mangaz": {
        "resource": "promptz", "label": "MangaZ",
        "buys": "A manga page script from your characters and idea, kept and editable, then drawn panel by panel.",
        "outcomes": ["tangible", "shareable", "braggable"],
        "lands_in": ["postz", "filez", "merchz"],
        "free_way": {"label": "A daily free prompt covers a script; making characters is free.", "tab": "characterz"}},
    "writecoach": {
        "resource": "promptz", "label": "Writing coach",
        "buys": "Your written lyrics scored on five dimensions, each with the reason and the fix, kept so you see them move.",
        "outcomes": ["tangible", "learnable", "understandable", "braggable"],
        "lands_in": ["sentenceconnectz", "postz"],
        "free_way": {"label": "A daily free prompt covers a read; writing in SentenceZ is always free.", "tab": "sentencez"}},
    "sentencez": {
        "resource": "promptz", "label": "Sentence ConnectZ",
        "buys": "A written piece, or five ranked suggestions for a weak area, kept in your library.",
        "outcomes": ["tangible", "lucrative", "shareable", "understandable"],
        "lands_in": ["postz", "distributez", "collabz", "battlez"],
        "free_way": {"label": "A daily free prompt covers a run; writing it yourself is always free.",
                     "tab": "sentenceconnectz"}},
    "instrumentalz": {
        "resource": "promptz", "label": "Instrumental ConnectZ",
        "buys": "A backing track as a MIDI you keep and can release.",
        "outcomes": ["tangible", "lucrative", "shareable"],
        "lands_in": ["distributez", "collabz", "battlez"],
        "free_way": {"label": "A daily free prompt covers a run.", "tab": "instrumentalconnectz"}},
    "gemini": {
        "resource": "promptz", "label": "Image ConnectZ",
        "buys": "A generated image you keep and can post.",
        "outcomes": ["tangible", "shareable"],
        "lands_in": ["postz", "messagez"],
        "free_way": {"label": "A daily free prompt covers a run.", "tab": "imageconnectz"}},
    "voicez": {
        "resource": "promptz", "label": "Voice preview",
        "buys": "A spoken sample of a voice, so you hear it before you choose it.",
        "outcomes": ["understandable"],
        "lands_in": ["voicez"],
        "ephemeral_reason": "It's a preview before a choice, not the thing itself — the voice you then "
                            "pick and use is free and yours at every tier; saving the sample would mean "
                            "keeping a clip whose only purpose was to be heard once and decided on.",
        "free_way": {"label": "Choosing and using your own voice is free; only the sample is metered.",
                     "tab": "voicez"}},
    "occ": {
        "resource": "promptz", "label": "OCC chat",
        "buys": "A reply from the OCC agent you can keep, edit and share as a work.",
        "outcomes": ["tangible", "shareable", "understandable"],
        "lands_in": ["occ", "postz"],
        "free_way": {"label": "A daily free prompt covers a run.", "tab": "occ"}},
    "occ_agent": {
        "resource": "promptz", "label": "OCC agent run",
        "buys": "A finished agent run, saved as a work you can open and share.",
        "outcomes": ["tangible", "shareable"],
        "lands_in": ["occ", "postz"],
        "free_way": {"label": "A daily free prompt covers a run.", "tab": "occ"}},
    "directz_app": {
        "resource": "promptz", "label": "DirectZ craft rating",
        "buys": "A watched-and-scored read of your video: framing, editing, lighting, sound, story.",
        # The score writes onto the DirectZWork row itself (directz_app.py
        # `_apply_craft_rating`), which is a public, listed work — tangible and
        # shareable were missing from this list even though the code already
        # delivers both; this was a declaration bug, not a product one.
        "outcomes": ["understandable", "learnable", "braggable", "tangible", "shareable"],
        "lands_in": ["directz", "postz"],
        "free_way": {"label": "A daily free prompt covers a run.", "tab": "directz"}},
    "translate": {
        "resource": "promptz", "label": "Translation",
        "buys": "Your text, translated, to keep and send.",
        "outcomes": ["tangible", "understandable", "shareable"],
        "lands_in": ["messagez", "postz"],
        "free_way": {"label": "KeyConnectZ translate is free at every tier.", "tab": "keyconnectz"}},
    "attractivenessz_view": {
        "resource": "promptz", "label": "Presentation rating",
        "buys": "A read of how a photo presents, with what to change.",
        "outcomes": ["understandable", "learnable"],
        "lands_in": ["profilez", "facez"],
        "ephemeral_reason": "Nothing is stored by design (attractivenessz.py): no photo, no score, no "
                            "history. A repeated biometric-adjacent rating held over time is its own "
                            "privacy risk that a stateless call does not create.",
        "no_free_way": "It reads one photo with a model; the daily free allowance is the free way in."},
    "bodiez_ai_view": {
        "resource": "promptz", "label": "BodieZ AI coach",
        "buys": "An AI read of a workout, routine or muscle from your logs (what's working, what to change, your next session), or a form check that watches one video of a set and scores it with cues.",
        "outcomes": ["tangible", "understandable", "learnable"],
        "lands_in": ["bodiez"],
        "free_way": {"label": "Every lift, muscle and routine already has a free Thorough rating, and a daily free prompt covers a read.", "tab": "bodiez"}},
    "lookmaxz_view": {
        "resource": "promptz", "label": "LookZMaxZ reading",
        "buys": "A sector-by-sector read of how a photo presents (face, skin, teeth, styling) with what to change and where to shop for it.",
        # Extends AttractivenessZ and inherits its privacy line: the reading
        # itself is never stored (only the member's own shop-market
        # preferences are, in LookmaxPrefs — a different thing). "tangible"
        # was here before this, which overclaimed what the code does; this is
        # the declaration catching up to the deliberate design, not a new one.
        "outcomes": ["understandable", "learnable"],
        "lands_in": ["lookmaxz", "bodiez"],
        "ephemeral_reason": "Inherits AttractivenessZ's privacy line: the reading is never stored, for "
                            "the same reason (a held biometric-adjacent history is its own risk). Only "
                            "the member's own shop-market preferences persist, in LookmaxPrefs.",
        "free_way": {"label": "Body, the shop and your marketplaces are free; a daily free prompt covers a reading.", "tab": "lookmaxz"}},
    "views": {
        "resource": "promptz", "label": "AI usage charge",
        "buys": "The model run another screen asked for, billed once and logged with its reason.",
        # This is the generic pass-through other screens bill an ad hoc AI
        # call through — it has no content model of its own, so "tangible"
        # here used to mean only "it shows up in your ledger," not "the
        # output is saved." The LogZ line is real but it is a bill, not a
        # kept result; the caller is the one that owes its own declaration
        # for whatever it actually produces.
        "outcomes": ["understandable"],
        "lands_in": ["logz"],
        "ephemeral_reason": "A generic billing pass-through for another screen's own ad hoc AI call — "
                            "it has no output of its own to keep. Whatever calls this should carry its "
                            "own declaration for what IT produces and keeps.",
        "free_way": {"label": "A daily free prompt covers a run, and every charge is in LogZ.", "tab": "logz"}},
    "battlez": {
        "resource": "spinaz", "label": "Battle stake",
        "buys": "A place in a battle with winnings on the line.",
        "outcomes": ["lucrative", "braggable", "shareable"],
        "lands_in": ["battlez", "postz"],
        "free_way": {"label": "Judging battles earns 🍥 and costs nothing.", "tab": "battlez"}},
    "venuez": {
        "resource": "spinaz", "label": "Room entry",
        "buys": "A booked place at a room or event, refunded if it is called off.",
        "outcomes": ["tangible", "shareable"],
        "lands_in": ["venuez"],
        "no_free_way": "A seat in a room is the thing itself; rooms with no entry price are free to book."},
    "collab": {
        "resource": "energy", "label": "Starting a deal",
        "buys": "A CollabZ deal with its escrow, split and release dates, ready to fund and finish.",
        "outcomes": ["tangible", "lucrative", "shareable"],
        "lands_in": ["collabz", "postz"],
        "free_way": {"label": "Energy regenerates hourly.", "tab": "collabz"}},
    "postz": {
        "resource": "energy", "label": "Posting",
        "buys": "A post that is live, linkable, and earns from ratings and joins; or a day near the top of the feed for a post you boost.",
        "outcomes": ["shareable", "lucrative", "braggable", "tangible"],
        "lands_in": ["postz", "battlez", "distributez"],
        "free_way": {"label": "Energy regenerates hourly, so posting is paid for in time, not money.",
                     "tab": "postz"}},
    "gamez_build": {
        "resource": "energy", "label": "Game build",
        "buys": "A playable game you can share.",
        "outcomes": ["tangible", "shareable", "braggable"],
        "lands_in": ["gamez", "postz"],
        "free_way": {"label": "Energy regenerates hourly.", "tab": "gamez"}},
    "messages_view": {
        "resource": "energy", "label": "Starting a conversation",
        "buys": "A first message to someone you have no history with, delivered to their inbox and by email.",
        "outcomes": ["shareable", "lucrative"],
        "lands_in": ["messagez", "collabz"],
        "free_way": {"label": "Replies, follow-ups, people who follow you and collab partners are always free; "
                              "Energy regenerates hourly.", "tab": "messagez"}},
    "social": {
        "resource": "energy", "label": "Commenting",
        "buys": "A comment or a follow that reaches someone, past your free daily allowance of each.",
        "outcomes": ["shareable", "braggable"],
        "lands_in": ["postz", "messagez"],
        "free_way": {"label": "Your first comments and follows each day, comments on your own post, and following back are free; "
                              "Energy regenerates hourly.", "tab": "postz"}},
    "occ_run": {
        "resource": "energy", "label": "OCC run",
        "buys": "A finished run saved as a work.",
        "outcomes": ["tangible", "shareable"],
        "lands_in": ["occ", "postz"],
        "free_way": {"label": "Energy regenerates hourly.", "tab": "occ"}},
}


def validate(entry):
    """Problems with one declaration; empty when it is sound."""
    out = []
    if entry.get("resource") not in ("promptz", "spinaz", "energy", "money"):
        out.append("resource")
    if not str(entry.get("buys", "")).strip():
        out.append("buys")
    got = entry.get("outcomes") or []
    if not got or not set(got) <= set(OUTCOMES):
        out.append("outcomes")
    if not entry.get("lands_in"):
        out.append("lands_in")
    free, none = entry.get("free_way"), entry.get("no_free_way")
    if not ((free and free.get("label") and free.get("tab")) or (none and str(none).strip())):
        out.append("free_way or no_free_way")
    # Corey's rule, narrower: a PromptZ spend — the resource that costs real
    # model money — must leave the member something tangible, or say plainly
    # why it deliberately doesn't. Silence on this is what let gemini.py bill
    # a member and hand back nothing kept.
    if entry.get("resource") == "promptz":
        ephemeral = entry.get("ephemeral_reason")
        if "tangible" not in got and not (ephemeral and str(ephemeral).strip()):
            out.append("tangible outcome or ephemeral_reason")
    return out


class CreditOutcomesView(APIView):
    """GET /api/economy/creditz/ — what every credit buys, before anyone spends one."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "outcomes": OUTCOMES,
            "spends": [{"key": k, **{f: v for f, v in e.items()}} for k, e in CREDIT_OUTCOMES.items()],
        })
