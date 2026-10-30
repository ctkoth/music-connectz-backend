"""LookmaxZ — what you can change about how you present, by sector, and what to buy for it.

This is AttractivenessZ's grown-up sibling and it inherits every line that
module drew (read its docstring first): **18+ verified, self only, presentation
never identity, nothing stored, no video.** What is new is that the one overall
number is split into sectors, each sector into the factors that make it up, and
every factor that is low points at something a member can actually do — and
buy, if buying is the right answer.

The sectors, and why each one is allowed to exist:

* **Face 🧔** — brows, facial hair, hair. NOT the face. Bone structure and
  proportion are exactly what AttractivenessZ refuses to score, and "face" here
  means the part of it a barber can change.
* **Skin 🧴** — texture, hydration, blemishes, sun damage, evenness.
* **Teeth 🦷** — staining, visible cleanliness, how the gums look. Never
  alignment or shape: that is a dentist's call, not a photo's.
* **Styling 👔** — fit, colour, condition of what you are wearing.
* **Proportions 📐 — opt-in, and the one sector that is not about change.** Added at
  Corey's request: the classical thirds, fifths and width-to-height ratios, and left-right
  balance. It is held apart on purpose (see `PROPORTIONS_DISCLAIMER`): behind an explicit
  "I understand", never in the default selection, never in the overall, never with a shop,
  and **its numbers are the server's arithmetic on rough measurements the model reports**,
  not a model's opinion of a face. A ratio is checkable; "a 6 for your jaw" is not. The
  prompt never mentions race or ethnicity and never calls a ratio "ideal" — it is closeness
  to a reference from art and design, which no study has shown predicts how people are seen.
* **Body photo 🏋️ — opt-in, and it reads TRAINING, never the body.** Added at Corey's request
  ("body pics refer to BodieZ to improve"). It is posture and the visible training balance
  of upper body, core and lower body — what a lifting plan can change — and every low result
  is a door into BodieZ's muscle builder for exactly those muscles. It is behind its own
  acknowledgement, never in the default selection, never in the overall, takes only clothed
  photos, and the prompt forbids weight, body fat, leanness, "ideal", comparison and any health
  claim. The honest cost: a model judging a physique from one photo is rough (clothes, pump,
  light and angle all move it) — which is why the BodieZ progress card below it stays the
  measured number and this stays labelled as a look.
* **Body 💪** — the measured one: **not read from a photo at all.** A body shape
  is the clearest "trait nobody can change by Tuesday", and scoring one is how
  a looks app becomes an eating-disorder app. Body is BodieZ's own measured
  progress: did your lifts go up against YOUR earlier best. A member who trains
  and gets stronger moves it; one who photographs well does not.

Four rules that hold it, each one a decision rather than a default:

1. **The model scores factors; the SERVER does the arithmetic.** A sector's
   number is the mean of its scored factors, and the overall is the mean of the
   sectors that were asked for. A second opinion from the model on the total is
   exactly the number nobody can check (the calibration section in CLAUDE.md).
   A factor the photo does not show is `None`, never a guess.
2. **Nothing a model wrote reaches a link.** Product searches are the server's
   (`PRODUCTS`), chosen by which factor scored low. The model's advice is text;
   the shop is ours. Otherwise "buy this" would be whatever a photo-reading
   model felt like saying, pointing at whatever it felt like pointing at.
3. **The tier buys WHERE you shop, never whether.** Everybody gets Amazon, eBay
   and Walmart, in that order, first. StatZ may replace the list with their own
   marketplaces. Links carry no affiliate tag — we earn nothing from them and
   the screen says so, because a recommendation with a hidden commission is the
   decoration the substance rule is about.
4. **A low number points at a product only when a product is the answer.**
   Persistent acne, a changing mole, bleeding gums are not shopping problems;
   each sector carries a "see a professional" line that is shown regardless of
   score.
"""
import base64
import json
import logging
import re
from urllib.parse import quote_plus, urlparse

import requests

from .attractivenessz import _clamp, _parse, gemini_image_mime
from .gemini import generate_content
from .vocalcoach import _key

logger = logging.getLogger(__name__)

# A factor under this gets a product. 7 is "fine, with something to do"; a 7
# is not a problem and does not need selling a cure.
WORK_BELOW = 7
SHOP_PER_SECTOR = 3
CUSTOM_MAX = 8

CAVEAT = ("This reads ONE photo — light, angle and a bad hair day all move it. "
          "It scores what you can change, never what you can't, and the numbers "
          "are plain averages of the factors under them. Not a permanent judgment.")

CARE_NOTE = ("If thinking about how you look is taking over your day, that is worth "
             "talking to a doctor or a counsellor about — no number here is a "
             "reason to feel worse.")

# `photo` sectors are read from one picture; `bodiez` is read from logged training.
SECTORS = {
    "face": {
        "label": "Face", "emoji": "🧔", "source": "photo",
        "means": "What a barber can change: hair, facial hair, brows. Not the shape of your face.",
        "factors": {"hair": "Hair", "facial_hair": "Facial hair", "brows": "Brows"},
        "see_pro": "A barber or stylist can do more in one visit than any product.",
    },
    "skin": {
        "label": "Skin", "emoji": "🧴", "source": "photo",
        "means": "Visible texture, hydration, blemishes, sun damage and evenness.",
        "factors": {"texture": "Texture", "hydration": "Hydration", "blemishes": "Blemishes",
                    "sun_care": "Sun damage", "evenness": "Evenness"},
        "see_pro": ("Acne that is painful or scarring, or any mole that changes, itches or "
                    "bleeds, is a dermatologist's job — not a product's."),
    },
    "teeth": {
        "label": "Teeth", "emoji": "🦷", "source": "photo",
        "means": "How clean and even in colour they look, and how the gums look. Not alignment or shape.",
        "factors": {"staining": "Staining", "cleanliness": "Visible cleanliness", "gums": "Gum look"},
        "see_pro": ("Bleeding or swollen gums, pain and sensitivity need a dentist. A photo can "
                    "show colour; it cannot show health."),
    },
    "styling": {
        "label": "Styling", "emoji": "👔", "source": "photo",
        "means": "How what you are wearing fits, how its colours sit on you, and what shape it is in.",
        "factors": {"fit": "Fit", "colour": "Colour", "condition": "Condition"},
        "see_pro": "A tailor fixes fit for a few dollars; a product cannot.",
    },
    "proportions": {
        "label": "Proportions", "emoji": "📐", "source": "photo", "opt_in": True,
        "means": ("How close the ratios in THIS photo sit to the classical references from art and "
                  "design: thirds, fifths, width to height, and left-right balance. A measurement "
                  "of the picture, not of your worth or your looks."),
        "factors": {"thirds": "Vertical thirds", "fifths": "Eye spacing", "width_height": "Width to height",
                    "symmetry": "Left-right balance"},
        "see_pro": ("None of this needs fixing and no product changes it. If how your face looks is "
                    "weighing on you, a doctor or counsellor is who to talk to — not a ratio."),
    },
    "physique": {
        "label": "Body photo", "emoji": "🏋️", "source": "photo", "opt_in": True,
        "means": ("Posture, and how balanced your visible training looks across upper body, core and "
                  "lower body in this one photo. Never weight, body fat or how you compare to anyone."),
        "factors": {"posture": "Posture", "upper_body": "Upper body", "core": "Core",
                    "lower_body": "Lower body"},
        "see_pro": ("A doctor before a big change in training, food or weight; and if how your body "
                    "looks is taking over your days, a doctor or counsellor — no number here is a reason "
                    "to feel worse."),
    },
    "body": {
        "label": "Body", "emoji": "💪", "source": "bodiez",
        "means": ("Read from your BodieZ training, never from a photo: whether your lifts went "
                  "up against your own earlier best."),
        "factors": {"strength_progress": "Strength progress"},
        "see_pro": "A doctor or qualified coach before a big change in training, food or weight.",
    },
}
PHOTO_SECTORS = [k for k, v in SECTORS.items() if v["source"] == "photo"]
# What a reading asks for unless the member asks for more. Opt-in sectors are never in it,
# and never in the overall.
DEFAULT_SECTORS = [k for k in PHOTO_SECTORS if not SECTORS[k].get("opt_in")]
OPT_IN_SECTORS = [k for k in PHOTO_SECTORS if SECTORS[k].get("opt_in")]

PHYSIQUE_DISCLAIMER = (
    "This reads posture and how balanced your training looks across upper body, core and lower body "
    "from ONE clothed photo. It is not a measure of weight, body fat, health or worth, and nothing "
    "here is an ideal to match. Clothes, a pump, light, lens and angle all change what a photo shows, "
    "and a model judging a body by eye is rough — the BodieZ progress card, which compares your lifts "
    "with your own earlier best, is the number to trust. A low result is a muscle group to train, and "
    "each one opens BodieZ's builder for it. It never enters your overall, and nothing about the photo "
    "or the result is kept.")

# Where a low physique factor goes: the BodieZ muscle groups that train it.
BODIEZ_MUSCLES = {
    "posture": ["back", "shoulders", "abs"],
    "upper_body": ["chest", "back", "shoulders", "biceps", "triceps"],
    "core": ["abs"],
    "lower_body": ["upper_legs", "glutes", "lower_legs"],
}

PROPORTIONS_DISCLAIMER = (
    "These ratios are classical reference points from art and design — thirds, fifths, width to "
    "height — not a validated measure of attractiveness, and not a measure of you. People are seen "
    "and loved for reasons no ratio captures, and what is admired differs between cultures and "
    "eras. One phone photo shifts every number: lens distortion, camera distance, head tilt and "
    "expression all move them, and the model only estimates by eye. You cannot change your "
    "proportions and nothing needs changing, so there is no shop here and this never enters your "
    "overall. Nothing about the photo or the result is kept.")
PROPORTIONS_RULE = (
    "Each measure is estimated from the photo, then the server scores how near it sits to its reference: "
    "thirds — about 1/3 each for hairline-to-brow, brow-to-nose-base and nose-base-to-chin (each 3 "
    "percentage points of drift costs a point); eye spacing — the gap between the eyes about one eye "
    "width apart; width to height — about two-thirds; left-right balance — a 0-1 estimate, the least "
    "reliable of the four because pose and light change it. A face not square on to the camera is not "
    "measured at all.")


# What each factor looks at, why it matters, how to move it. ONE place: the model's prompt
# is built from `what`, the screen shows all three BEFORE a photo is sent, and a test fails
# if a factor has no entry — a number with no description is a broken feature.
FACTORS = {
    ("face", "hair"): {
        "what": "How the hair you have is kept and shaped: clean, even, a cut that suits how you wear it.",
        "why": "Hair frames everything in a photo, and it is the quickest thing to change — a cut is an afternoon.",
        "how": "A fresh cut every 4-6 weeks, wash to suit your scalp, a little product for shape."},
    ("face", "facial_hair"): {
        "what": "Whether facial hair, or its absence, looks deliberate: edges, neckline, even length, no stray patches.",
        "why": "Unkempt reads as careless; kept reads as chosen, whichever style you picked.",
        "how": "Trim the neckline and cheek line weekly, keep one length, or shave clean and moisturise."},
    ("face", "brows"): {
        "what": "Tidiness of the brows: strays, gaps in grooming, length. Never their shape or position.",
        "why": "Brows are the first thing a camera reads on a face, and stray hair is an easy fix.",
        "how": "Remove strays below and between, trim long hairs; leave your natural line."},
    ("skin", "texture"): {
        "what": "How smooth or rough the skin surface looks: flaking, bumps, visible pores in the light.",
        "why": "Texture is what light catches, so it shows even in a flattering photo.",
        "how": "Gentle cleanser, a mild exfoliant a couple of times a week, and patience — weeks, not days."},
    ("skin", "hydration"): {
        "what": "Whether skin looks plump and even or dry, tight or dull.",
        "why": "Dry skin shows lines and flaking more and photographs flat.",
        "how": "Moisturise morning and night, drink water, and wash with something gentler."},
    ("skin", "blemishes"): {
        "what": "Visible spots, redness from breakouts and marks. Not scars you cannot change.",
        "why": "Active breakouts are the most noticed thing in a close photo, and are treatable.",
        "how": "Gentle cleansing, an over-the-counter spot treatment, hands off. Severe or painful acne: a dermatologist."},
    ("skin", "sun_care"): {
        "what": "Visible sun damage: uneven darkening, sunburn, leathery or spotted areas.",
        "why": "Sun is the biggest controllable cause of skin ageing, and the damage is cumulative.",
        "how": "Broad-spectrum SPF 30+ every day, hat and shade. Any mole that changes: a doctor."},
    ("skin", "evenness"): {
        "what": "How even the colour is across the face: patches, redness, dark marks.",
        "why": "Even tone reads as healthy skin more than any single feature does.",
        "how": "Sunscreen first (it stops marks deepening), then patience with a vitamin C serum."},
    ("teeth", "staining"): {
        "what": "How much the teeth you can see are stained or yellowed. Natural shade is not a fault.",
        "why": "Surface stain from coffee, tea, wine and smoking is common and lifts.",
        "how": "Rinse after dark drinks, a dentist clean, enamel-safe whitening. Stop if teeth get sensitive."},
    ("teeth", "cleanliness"): {
        "what": "Whether the visible teeth look clean: plaque, residue, film.",
        "why": "It is the same habit that protects them, and it shows.",
        "how": "Brush two minutes twice a day, clean between the teeth daily, dentist twice a year."},
    ("teeth", "gums"): {
        "what": "How the visible gums look: even pink, or red and swollen. Looks only — it cannot diagnose.",
        "why": "Red, puffy gums can mean something a dentist should see.",
        "how": "Brush gently along the gumline and floss daily; if they stay red or bleed, see a dentist."},
    ("styling", "fit"): {
        "what": "Whether what you are wearing sits well on you: shoulders, length, neither tight nor swamping.",
        "why": "Fit changes how any outfit looks, at any price.",
        "how": "Buy for your shoulders, then tailor sleeves and hems — it is cheap."},
    ("styling", "colour"): {
        "what": "How the colours you are wearing sit together and against your skin and hair.",
        "why": "The right colour makes skin look healthier; the wrong one drains it.",
        "how": "Build on two or three neutrals and one colour you get complimented in."},
    ("styling", "condition"): {
        "what": "The state of what you are wearing: creases, pilling, stains, fraying.",
        "why": "Close up, wear shows first and reads as effort not spent.",
        "how": "Steam or iron, remove pilling, retire what is worn out."},
    ("proportions", "thirds"): {
        "what": "Whether the three vertical sections of the face — hairline to brow, brow to the base of the nose, nose base to chin — are close to equal in this photo.",
        "why": "A classical drawing guideline; many faces are not equal thirds and are not lesser for it.",
        "how": "Nothing to change. Hair and brow styling change how the sections read in a photo; that is styling, not a fix."},
    ("proportions", "fifths"): {
        "what": "Whether the space between the eyes is about one eye-width, as the classical 'fifths' guideline has it.",
        "why": "Another art-school reference. Wide-set and close-set eyes are both ordinary.",
        "how": "Nothing to change. Brow grooming and glasses frames change how eye spacing reads."},
    ("proportions", "width_height"): {
        "what": "The width of the face compared with its height, against a reference of about two-thirds.",
        "why": "Face shape varies widely and healthily; this is a reference, not a target.",
        "how": "Nothing to change. A haircut or facial hair frames the face differently."},
    ("proportions", "symmetry"): {
        "what": "A rough estimate of how mirror-like the left and right halves look in this photo.",
        "why": "Every face is slightly asymmetric; head turn, light and expression move this one most of all, so it is the least reliable.",
        "how": "Nothing to change. Face the camera square on, in even light, if you want a steadier reading."},
    ("physique", "posture"): {
        "what": "How upright you stand in the photo: head over shoulders, shoulders level and not rolled forward.",
        "why": "Posture changes how everything you wear sits, and it is trainable — back, shoulder and core strength hold it.",
        "how": "Rows and rear-shoulder work, core bracing, and moving through the day. Pain is a doctor's question."},
    ("physique", "upper_body"): {
        "what": "How evenly the chest, back, shoulders and arms look trained against the rest of you. Not size, and not leanness.",
        "why": "An area that lags the rest is the one place a plan pays back fastest.",
        "how": "Add sets for the lagging group in BodieZ, progress the weight against your own best, rest between sessions."},
    ("physique", "core"): {
        "what": "How trained the trunk looks relative to the rest of the body in this photo. Never body fat.",
        "why": "A strong core carries every other lift and holds posture.",
        "how": "Carries, planks and rotation work in BodieZ's abs builder; consistency beats volume."},
    ("physique", "lower_body"): {
        "what": "How evenly the legs and glutes look trained against the upper body.",
        "why": "Legs are the biggest muscles you have and the ones most often skipped.",
        "how": "Squat, hinge and single-leg work in BodieZ, built up gradually."},
    ("body", "strength_progress"): {
        "what": "Whether your logged lifts went up against YOUR OWN earlier best in BodieZ. Not what you look like.",
        "why": "Getting stronger is the one body change that is measured rather than judged — and it is yours.",
        "how": "Log your sessions, add a little weight or a rep when it feels easy, rest between sessions."},
}

SCALE = [
    {"band": "1-3", "means": "A real problem to fix first."},
    {"band": "4-6", "means": "Ordinary, with clear room to improve."},
    {"band": "7-8", "means": "Well kept."},
    {"band": "9-10", "means": "Excellent — little to change."},
]
RATING_RULE = ("Each factor is scored 1-10 from what the photo shows; a factor it does not show is left "
               "blank, never guessed. A sector is the average of its factors, the overall is the average "
               "of the sectors you asked for. Photo quality is shown on its own and is not in the average.")

# Server-owned, by (sector, factor). `query` is what is searched on a marketplace;
# `caution` is shown beside the product. Categories, never brands — a brand is an
# endorsement we have no way to test.
PRODUCTS = {
    ("face", "hair"): [
        {"key": "hair_clay", "label": "Matte hair clay", "query": "matte hair clay men women",
         "why": "Holds a shape without the wet look."},
        {"key": "hair_brush", "label": "Boar-bristle brush", "query": "boar bristle hair brush",
         "why": "Spreads oil along the hair so it reads healthier."},
    ],
    ("face", "facial_hair"): [
        {"key": "trimmer", "label": "Beard trimmer", "query": "beard trimmer adjustable guard",
         "why": "A clean neckline and even length is most of the difference."},
        {"key": "beard_oil", "label": "Beard balm or oil", "query": "beard oil balm",
         "why": "Softens and tames stray hair.", "caution": "Patch-test; stop if skin itches."},
    ],
    ("face", "brows"): [
        {"key": "brow_kit", "label": "Brow grooming kit", "query": "eyebrow grooming kit tweezers scissors",
         "why": "Removing strays and trimming length, nothing more."},
    ],
    ("skin", "hydration"): [
        {"key": "moisturiser", "label": "Ceramide moisturiser", "query": "ceramide moisturizer fragrance free",
         "why": "The single most useful daily step for dry-looking skin."},
    ],
    ("skin", "sun_care"): [
        {"key": "sunscreen", "label": "Broad-spectrum SPF 30+ sunscreen",
         "query": "broad spectrum spf 30 face sunscreen",
         "why": "Daily sun is the largest controllable cause of visible skin ageing."},
    ],
    ("skin", "texture"): [
        {"key": "exfoliant", "label": "Gentle exfoliant (salicylic acid)",
         "query": "2% salicylic acid gentle exfoliant",
         "why": "Smooths surface roughness over weeks, not days.",
         "caution": "Start twice a week; stop if it stings or peels."},
        {"key": "cleanser", "label": "Gentle cleanser", "query": "gentle face cleanser fragrance free",
         "why": "Harsh washing makes texture worse."},
    ],
    ("skin", "blemishes"): [
        {"key": "spot_treatment", "label": "Benzoyl peroxide spot treatment",
         "query": "benzoyl peroxide 2.5% spot treatment",
         "why": "An over-the-counter first step for ordinary breakouts.",
         "caution": "Bleaches fabric. Painful, scarring or persistent acne needs a dermatologist."},
    ],
    ("skin", "evenness"): [
        {"key": "vitamin_c", "label": "Vitamin C serum", "query": "vitamin c serum face",
         "why": "Used with sunscreen it can help even out tone over months.",
         "caution": "Patch-test first."},
    ],
    ("teeth", "staining"): [
        {"key": "whitening_strips", "label": "Enamel-safe whitening strips",
         "query": "teeth whitening strips enamel safe sensitive",
         "why": "Lifts surface stain from coffee, tea and wine.",
         "caution": "Sensitivity is common; do not overuse."},
    ],
    ("teeth", "cleanliness"): [
        {"key": "electric_brush", "label": "Electric toothbrush", "query": "electric toothbrush timer",
         "why": "Cleans more consistently than most hands do."},
        {"key": "floss", "label": "Floss picks or water flosser", "query": "water flosser",
         "why": "What a brush misses between teeth is what shows."},
    ],
    ("teeth", "gums"): [
        {"key": "soft_brush", "label": "Soft-bristle toothbrush", "query": "soft bristle toothbrush",
         "why": "Gentle on gums that look irritated.",
         "caution": "Gums that bleed or swell are a dentist's call."},
    ],
    ("styling", "fit"): [
        {"key": "basics", "label": "Well-fitting plain basics", "query": "fitted plain t-shirt crew neck",
         "why": "A clean fit beats any pattern."},
    ],
    ("styling", "colour"): [
        {"key": "neutrals", "label": "Neutral layering pieces", "query": "neutral overshirt navy grey",
         "why": "Neutrals flatter most skin tones and mix freely."},
    ],
    ("styling", "condition"): [
        {"key": "steamer", "label": "Handheld garment steamer", "query": "handheld garment steamer",
         "why": "Creased clothes read as careless in a photo."},
        {"key": "lint", "label": "Lint remover", "query": "fabric lint remover shaver",
         "why": "Pilling is the first thing a close photo shows."},
    ],
    ("body", "strength_progress"): [
        {"key": "dumbbells", "label": "Adjustable dumbbells", "query": "adjustable dumbbells set",
         "why": "A progressive load at home, if the gym is the thing in the way."},
        {"key": "bands", "label": "Resistance bands", "query": "resistance bands set with handles",
         "why": "Cheap, travels, trains the same patterns."},
        {"key": "roller", "label": "Foam roller", "query": "foam roller",
         "why": "For soreness between sessions."},
    ],
}

# ----------------------------------------------------------------- marketplaces

DEFAULT_MARKETS = [
    {"key": "amazon", "name": "Amazon", "url": "https://www.amazon.com/s?k={q}"},
    {"key": "ebay", "name": "eBay", "url": "https://www.ebay.com/sch/i.html?_nkw={q}"},
    {"key": "walmart", "name": "Walmart", "url": "https://www.walmart.com/search?q={q}"},
]
_DEFAULT_BY_KEY = {m["key"]: m for m in DEFAULT_MARKETS}
_SLUG = re.compile(r"[^a-z0-9]+")


def _bad_host(host):
    host = (host or "").lower()
    if not host or "." not in host or host.endswith(".local") or host.endswith(".internal"):
        return True
    # An address literal is never a marketplace, and 127.x / 10.x / 192.168.x
    # are exactly the ones a template could be pointed at.
    return bool(re.fullmatch(r"[\d.]+", host)) or ":" in host or host == "localhost"


def clean_market(raw):
    """One entry from a member's list → a clean dict, or None. Repairs, never raises.

    An entry may name a default by `key` alone (to reorder or keep it), or carry
    its own `name` + `url` template with exactly one `{q}`.
    """
    if not isinstance(raw, dict):
        return None
    key = _SLUG.sub("-", str(raw.get("key") or raw.get("name") or "").lower()).strip("-")[:30]
    url = str(raw.get("url") or "").strip()
    if not url and key in _DEFAULT_BY_KEY:
        return dict(_DEFAULT_BY_KEY[key])
    name = str(raw.get("name") or "").strip()[:30]
    if not name or not key or len(url) > 300 or url.count("{q}") != 1:
        return None
    parsed = urlparse(url.replace("{q}", "x"))
    if parsed.scheme != "https" or parsed.username or parsed.password or _bad_host(parsed.hostname):
        return None
    return {"key": key, "name": name, "url": url}


def clean_markets(raw):
    """A list → clean, de-duplicated, capped. Returns (list, dropped_count)."""
    out, seen, dropped = [], set(), 0
    for item in (raw if isinstance(raw, list) else []):
        m = clean_market(item)
        if not m or m["key"] in seen:
            dropped += 1
            continue
        seen.add(m["key"])
        out.append(m)
    if len(out) > CUSTOM_MAX:
        dropped += len(out) - CUSTOM_MAX
        out = out[:CUSTOM_MAX]
    return out, dropped


def _is_statz(user):
    """A saved marketplace list is a standing preference, so it needs the real tier:
    a free sample must not leave a permanent grant behind (`coach_voices` is the precedent)."""
    from .models import TIER_DEBUG, TIER_STATZ, membership_for
    return membership_for(user).tier in (TIER_STATZ, TIER_DEBUG)


def markets_for(user):
    """What the member shops on. Everyone has the three; StatZ may have their own."""
    from .models import LookmaxPrefs
    row = LookmaxPrefs.objects.filter(user=user).first()
    saved, _ = clean_markets(row.markets if row else [])
    statz = _is_statz(user)
    if statz and saved:
        return {"markets": saved, "source": "yours", "can_customise": True, "saved": len(saved)}
    return {"markets": [dict(m) for m in DEFAULT_MARKETS], "source": "default",
            "can_customise": statz,
            # Kept, not discarded, on a lapse — it comes back with StatZ.
            "saved": len(saved)}


def link_for(market, query):
    return market["url"].replace("{q}", quote_plus(query))


def products_for(sector, factor, score, markets):
    """The shop for one low factor — server catalogue, links built here."""
    out = []
    for p in PRODUCTS.get((sector, factor), []):
        out.append({
            "key": p["key"], "label": p["label"], "why": p["why"], "caution": p.get("caution", ""),
            "factor": factor, "factor_label": SECTORS[sector]["factors"][factor], "score": score,
            "links": [{"key": m["key"], "name": m["name"], "url": link_for(m, p["query"])}
                      for m in markets],
        })
    return out


def shop_for_sector(sector, markets, scores=None):
    """Products for a sector. With scores: only the factors under WORK_BELOW, lowest first.
    Without (the free browse): every factor, in the catalogue's order."""
    out = []
    factors = SECTORS[sector]["factors"]
    if scores is None:
        for f in factors:
            out += products_for(sector, f, None, markets)
        return out
    low = sorted(((s, f) for f, s in scores.items() if s is not None and s < WORK_BELOW))
    for s, f in low:
        out += products_for(sector, f, s, markets)
    return out[:SHOP_PER_SECTOR]


# ----------------------------------------------------------------------- rating

def build_prompt(sectors):
    styled = [k for k in sectors if k not in ("proportions", "physique")]
    prop = "proportions" in sectors
    phys = "physique" in sectors
    lines = []
    for k in styled:
        s = SECTORS[k]
        facs = "; ".join(f'"{f}" ({lab}: {FACTORS[(k, f)]["what"]})' for f, lab in s["factors"].items())
        lines.append(f'- "{k}" — {s["means"]} Factors: {facs}.')
    shape = ", ".join(
        f'"{k}": {{"factors": {{{", ".join(chr(34) + f + chr(34) + ": <1-10 or null>" for f in SECTORS[k]["factors"])}}}, '
        f'"advice": ["<specific, actionable steps>"]}}'
        for k in styled)
    if prop:
        shape += (", " if shape else "") + (
            '"proportions": {"measures": {"upper": <fraction of face height, hairline to brow, or null>, '
            '"middle": <brow to base of nose, or null>, "lower": <base of nose to chin, or null>, '
            '"eye_gap_over_eye_width": <number or null>, "width_over_height": <number or null>, '
            '"symmetry": <0 to 1 or null>}, "advice": []}')
    if phys:
        shape += (", " if shape else "") + (
            '"physique": {"factors": {"posture": <1-10 or null>, "upper_body": <1-10 or null>, '
            '"core": <1-10 or null>, "lower_body": <1-10 or null>}, "advice": ["<training-focused steps>"]}')
    base = f"""You are a grooming and presentation consultant, not a beauty \
judge. Look at this ONE photo and give honest, specific, ACTIONABLE feedback."""
    if styled:
        base += f"""
For these sectors, on presentation only:
{chr(10).join(lines)}

Score each factor 1-10 (1-3 a real problem, 4-6 ordinary with room to improve, 7-8 well kept, 9-10 excellent), and judge it exactly as its description says, and use null for \
any factor the photo does not actually show (a mouth that is closed has no \
"staining" to read). Never guess a factor you cannot see.

For these sectors score and advise ONLY on things a person can change. Do NOT \
score, mention, or imply anything about bone structure, body shape or size, \
race, ethnicity, age, disability, or any other trait nobody can change. \
Be constructive: name what is working before what to change. Talk TO the \
person, the way an honest friend who knows skincare and grooming would. Do \
not recommend specific brands or products — only what to do."""
    if prop:
        base += """

For the "proportions" sector only, report ROUGH MEASUREMENTS of this photo as \
numbers, never a judgement or a score: upper, middle and lower are the three \
vertical sections of the face as fractions of the face's height (they should \
sum to about 1); eye_gap_over_eye_width is the distance between the inner \
eye corners divided by the width of one eye; width_over_height is the width \
of the face at the cheekbones divided by its height; symmetry is a 0-1 \
estimate of how mirror-like the two halves look. These are estimates by eye \
and may be rough. If the face is not looking square at the camera (turned, \
tilted or cropped), set every measure to null — do not guess. Do not say \
anything is ideal, attractive, better or worse, and never mention race, \
ethnicity, age or any comparison to other people. Leave "advice" empty for \
this sector."""
    if phys:
        base += """

For the "physique" sector only, you are a strength coach reading ONE photo: \
score posture, and how evenly trained the upper body, core and lower body \
look relative to each other, 1-10 (a higher number means that area looks as \
developed as the rest of the person; a lower number means it lags the rest). \
Use null for any area clothing, framing or angle hides — never guess. Do NOT \
mention or estimate weight, body fat, leanness, BMI, health, age, \
race, or ethnicity; never call a body ideal, attractive, good or bad; never \
compare the person to anyone. Advice must be training only (which muscle \
groups to train, how), never diet or weight. If the photo shows nudity, set \
"unreadable" to ask for a clothed photo, and stop."""
    base += f"""

If the photo does not clearly show one person — their face for the grooming \
sectors, their body for the body photo — (too dark, too blurry, not a person, \
or multiple people), set "unreadable" to a short sentence saying \
what you saw, and stop.

Reply with ONLY a JSON object, no prose around it:
{{
  "unreadable": <null, or a short sentence>,
  "photo_quality": <1-10: how well this photo shows the person; not a score of them>,
  "verdict": "<one or two sentences, direct and kind, about presentation only>",
  "working": ["<what is already working, specific to this photo>"],
  "sectors": {{{shape}}}
}}"""
    return base


def _frac(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if 0 < v < 3 else None


def score_proportions(measures):
    """Rough measurements in → (scores, cleaned measures). All arithmetic is here, none is the model's.

    A measure that is missing or implausible is None and scores None: a face not square on to the
    camera is not measured, so nothing is guessed to fill the slot.
    """
    m = measures if isinstance(measures, dict) else {}
    clean = {k: _frac(m.get(k)) for k in ("upper", "middle", "lower", "eye_gap_over_eye_width",
                                           "width_over_height")}
    sym = _frac(m.get("symmetry"))
    clean["symmetry"] = sym if sym is not None and sym <= 1 else None
    thirds = [clean["upper"], clean["middle"], clean["lower"]]
    scores = {"thirds": None, "fifths": None, "width_height": None, "symmetry": None}
    if all(t is not None for t in thirds):
        total = sum(thirds)
        if 0.85 <= total <= 1.15:                       # sections that do not add up are not a face
            dev = max(abs(t / total - 1 / 3) for t in thirds)
            scores["thirds"] = max(1, min(10, round(10 - 100 * dev)))
    if clean["eye_gap_over_eye_width"] is not None:
        scores["fifths"] = max(1, min(10, round(10 - 10 * abs(clean["eye_gap_over_eye_width"] - 1.0))))
    if clean["width_over_height"] is not None:
        scores["width_height"] = max(1, min(10, round(10 - 25 * abs(clean["width_over_height"] - 2 / 3))))
    if clean["symmetry"] is not None:
        scores["symmetry"] = max(1, min(10, round(1 + 9 * clean["symmetry"])))
    return scores, clean


def _mean(values):
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def clean_reply(parsed, sectors):
    """Whatever the model said → only declared sectors and factors, server arithmetic."""
    listy = lambda v: [str(x)[:300] for x in v][:5] if isinstance(v, list) else []
    got = parsed.get("sectors") if isinstance(parsed.get("sectors"), dict) else {}
    out = {}
    for k in sectors:
        raw = got.get(k) if isinstance(got.get(k), dict) else {}
        if k == "proportions":
            scores, measures = score_proportions(raw.get("measures"))
            out[k] = {"scores": scores, "score": _mean(scores.values()), "advice": [],
                      "measures": measures, "disclaimer": PROPORTIONS_DISCLAIMER}
            continue
        rf = raw.get("factors") if isinstance(raw.get("factors"), dict) else {}
        scores = {f: _clamp(rf.get(f)) for f in SECTORS[k]["factors"]}
        out[k] = {"scores": scores, "score": _mean(scores.values()), "advice": listy(raw.get("advice"))}
        if k == "physique":
            out[k]["disclaimer"] = PHYSIQUE_DISCLAIMER
            out[k]["doors"] = bodiez_doors(scores)
    return out


def bodiez_doors(scores):
    """The way into BodieZ for every physique factor under WORK_BELOW, lowest first.

    Server-owned: which muscle groups train which factor is `BODIEZ_MUSCLES`, never the model's
    say-so, and the client lands on BodieZ's muscle builder with the first one pre-selected."""
    low = sorted((s, f) for f, s in scores.items() if s is not None and s < WORK_BELOW)
    return [{"factor": f, "label": SECTORS["physique"]["factors"][f], "score": s,
             "muscles": BODIEZ_MUSCLES[f],
             "open_in": {"tab": "bodiez", "muscle": BODIEZ_MUSCLES[f][0],
                         "label": f"Build a {SECTORS['physique']['factors'][f].lower()} day in BodieZ"}}
            for s, f in low]


def overall_of(cleaned):
    """The overall is the mean of the sectors asked for — never an opt-in one."""
    return _mean(s["score"] for k, s in cleaned.items() if not SECTORS[k].get("opt_in"))


def rate_looks(fileobj, content_type, sectors):
    """One photo in, per-sector feedback out. Returns (payload, reason); exactly one is None.

    The caller has already checked verified_18plus and confirm_self.
    """
    key = _key()
    if not key:
        return None, "the coach isn't configured (GEMINI_API_KEY)"
    mime = gemini_image_mime(content_type)
    if not mime:
        return None, f"can't read {content_type or 'that format'}"
    body = {"contents": [{"parts": [
        {"text": build_prompt(sectors)},
        {"inline_data": {"mime_type": mime, "data": base64.b64encode(fileobj.read()).decode()}},
    ]}], "generationConfig": {"temperature": 0.3}}
    try:
        resp, tried = generate_content(
            "text", body, key=key, timeout=90,
            env_vars=("GEMINI_VIDEO_MODEL", "GEMINI_AUDIO_MODEL"), label="LookmaxZ")
    except requests.RequestException:
        logger.exception("LookmaxZ: could not reach Gemini")
        return None, "couldn't reach the coach"
    if resp.status_code != 200:
        logger.error("LookmaxZ: Gemini %s mime=%s model=%s — %s",
                     resp.status_code, mime, ", ".join(tried), resp.text[:300])
        return None, {
            400: "that photo wasn't accepted", 403: "the coach's API key was refused",
            404: "the coach can't reach a model right now", 429: "the coach has hit its limit for now",
        }.get(resp.status_code, "the coach is having a moment" if resp.status_code >= 500
              else "the coach refused that one")
    try:
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, ValueError):
        return None, "the reply didn't come back readable"
    parsed = _parse(text)
    if not parsed:
        logger.error("LookmaxZ: unparseable reply — %s", text[:300])
        return None, "the reply didn't come back readable"

    empty = {"unreadable": "", "photo_quality": None, "verdict": "", "working": [],
             "sectors": {}, "overall": None, "caveat": CAVEAT}
    if parsed.get("unreadable"):
        return {**empty, "unreadable": str(parsed["unreadable"])[:300]}, None

    cleaned = clean_reply(parsed, sectors)
    overall = overall_of(cleaned)
    if overall is None and not any(s["score"] is not None for s in cleaned.values()):
        # Nothing scorable came back: not a result, and not charged.
        return {**empty, "unreadable": "The photo didn't show enough of those sectors to read any of them."}, None
    return {
        **empty,
        "photo_quality": _clamp(parsed.get("photo_quality")),
        "verdict": str(parsed.get("verdict", ""))[:400],
        "working": [str(x)[:300] for x in (parsed.get("working") or [])][:5]
        if isinstance(parsed.get("working"), list) else [],
        "sectors": cleaned,
        "overall": overall,
    }, None


# ------------------------------------------------------------------------ body

BODY_WINDOW_DAYS = 120
BODY_SESSIONS_DAYS = 28
BODY_SET_CAP = 4000


def body_sector(user):
    """Body, read from BodieZ. Free, no model, and never from a picture."""
    from datetime import timedelta

    from django.utils import timezone

    from .bodiez import muscle_coach_ratings
    from .models import BodieZSession, BodieZSet
    now = timezone.now()
    sets = list(BodieZSet.objects
                .filter(session__user=user, session__ended_at__isnull=False,
                        session__started_at__gte=now - timedelta(days=BODY_WINDOW_DAYS))
                .select_related("exercise", "session")[:BODY_SET_CAP])
    ratings = muscle_coach_ratings(sets)
    rated = [r["rating"] for r in ratings.values() if r["rating"] is not None]
    score = _mean(rated)
    sessions = BodieZSession.objects.filter(
        user=user, ended_at__isnull=False,
        started_at__gte=now - timedelta(days=BODY_SESSIONS_DAYS)).count()
    return {
        "scores": {"strength_progress": score}, "score": score, "advice": [],
        "why": (f"{len(rated)} muscle group{'s' if len(rated) != 1 else ''} compared against "
                "your own earlier best." if rated else
                "Needs two logged sessions of the same exercise before anything can be compared."),
        "sessions_28d": sessions,
        "open_in": {"tab": "bodiez", "label": "Log a session in BodieZ"},
    }


# ---- Look Inspiration: somebody's LOOK, never somebody ---------------------------------------
# The reading above is for photos of the member and scores them 1-10. A photo of anybody else is
# described, never scored: the changeable choices in it (cut, facial hair, brows, styling) and how
# to get each. The prompt forbids a number, any word about the person's face, skin, teeth or body,
# guessing who they are, and attractiveness itself — so a stranger's picture cannot come back as a
# verdict on the stranger. What it does come back as is the useful part: "I want that cut".
INSPIRE_PARTS = {"hair": "Haircut", "facial_hair": "Facial hair", "brows": "Brows", "styling": "Styling"}


def inspire_prompt():
    parts = ", ".join(f'"{k}" ({v})' for k, v in INSPIRE_PARTS.items())
    return (
        "Describe the LOOK in this photo so somebody else can recreate it. Cover only these parts, and only "
        f"the ones the photo shows: {parts}. For each give \"what\" (what the look is, in the words a barber, "
        "stylist or shop would use) and \"how\" (how to get it: what to ask for, how to wear it, what to buy, "
        "as categories never brands).\n"
        "Rules you must not break: give NO score, rating or number of any kind. Say NOTHING about the person's "
        "face shape, features, skin, teeth, body, weight, age, ethnicity or attractiveness. Do not guess or "
        "say who they are. Describe the choices, never the person.\n"
        "If the photo shows none of those parts, return {\"none\": \"<one sentence why>\"}.\n"
        "Reply with JSON only: {\"summary\": \"<one sentence: the look>\", \"parts\": {\"<part>\": "
        "{\"what\": \"<…>\", \"how\": [\"<step>\"]}}}"
    )


def clean_inspiration(parsed):
    """Only the declared parts, text only, bounded; nothing numeric survives."""
    parts = []
    raw = parsed.get("parts") if isinstance(parsed, dict) else None
    for key, label in INSPIRE_PARTS.items():
        row = raw.get(key) if isinstance(raw, dict) else None
        if not isinstance(row, dict):
            continue
        what = " ".join(str(row.get("what") or "").split())[:300]
        how = [" ".join(str(x).split())[:240] for x in (row.get("how") or []) if str(x).strip()][:5] \
            if isinstance(row.get("how"), list) else []
        if what:
            parts.append({"key": key, "label": label, "what": what, "how": how})
    return {"summary": " ".join(str((parsed or {}).get("summary") or "").split())[:300], "parts": parts}


def inspire_look(fileobj, content_type):
    """(look, None) or (None, reason). `look["parts"]` empty means nothing to describe (not charged)."""
    key = _key()
    if not key:
        return None, "the coach isn't configured (GEMINI_API_KEY)"
    mime = gemini_image_mime(content_type)
    if not mime:
        return None, f"can't read {content_type or 'that format'}"
    body = {"contents": [{"parts": [
        {"text": inspire_prompt()},
        {"inline_data": {"mime_type": mime, "data": base64.b64encode(fileobj.read()).decode()}},
    ]}], "generationConfig": {"temperature": 0.4}}
    try:
        resp, _tried = generate_content("text", body, key=key, timeout=90,
                                        env_vars=("GEMINI_VIDEO_MODEL", "GEMINI_AUDIO_MODEL"),
                                        label="LookZMaxZ inspiration")
    except requests.RequestException:
        logger.exception("LookZMaxZ inspiration: could not reach Gemini")
        return None, "couldn't reach the coach"
    if resp.status_code != 200:
        logger.error("LookZMaxZ inspiration: Gemini %s — %s", resp.status_code, resp.text[:300])
        return None, "the coach couldn't read that photo right now"
    try:
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, ValueError):
        return None, "the reply didn't come back readable"
    parsed = _parse(text)
    if not parsed:
        return None, "the reply didn't come back readable"
    if parsed.get("none"):
        return {"summary": "", "parts": [], "why": str(parsed["none"])[:300]}, None
    return clean_inspiration(parsed), None
