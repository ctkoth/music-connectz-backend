"""Every tier gate in the app, in one list — read from where each one already lives, never retyped.

Corey asked how to apply the tier numbers across the whole app. The first answer is to be able to
SEE them: gates were spread over a dozen tables (`TIER_LIMITS`, `features.FEATURES`, the StatZ
features, releases a month, the mastering ladder, the keyboard's voice allowances, Lilith's limits,
OCC's projects…) and no screen could say "here is everything each plan holds". This module is that
list, `GET /api/economy/ladders/` serves it, and MembershipZ draws it as one table.

Three rules hold it:

* **No number is written here.** Every row is a reader over the constant that actually gates the
  thing, so the table and the gate cannot disagree. A shared number (Corey's 3 / 6 / unlimited)
  appears once per place it gates, because a member looks up "tracks in a DAW", not a key name.
* **Nothing can be left off.** `test_ladders` fails when a `TIER_LIMITS` key, a `features.FEATURES`
  row or a StatZ feature has no row here, so a new gate cannot ship invisible.
* **The words say what a tier buys** — how much (`count`), or which plan opens it (`access`), with the
  StatZ sample named where it covers a feature. It is a tier saying how much, never whether, made
  readable; it decides nothing itself.
"""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import catalog as C
from .models import TIER_FREE, TIER_PREMIUM, TIER_STATZ

TIERS = (TIER_FREE, TIER_PREMIUM, TIER_STATZ)
BIG = 10 ** 6
COREYS = {TIER_FREE: "3", TIER_PREMIUM: "6", TIER_STATZ: "Unlimited"}        # anything this large is "unlimited" in practice (the owner's debug numbers sit above)


def _lim(key):
    return lambda t: C.limits_for(t).get(key)


def _from(table, field=None):
    return lambda t: (table[t][field] if field else table[t])


def _fmt(v, unit=""):
    if v is None or (isinstance(v, (int, float)) and v >= BIG):
        return "Unlimited"
    if isinstance(v, bool):
        return "✓" if v else "—"
    if isinstance(v, (int, float)):
        n = int(v) if float(v).is_integer() else v
        return f"{n:,}{(' ' + unit) if unit else ''}"
    return str(v)


def _rows():
    from .lilith_taskz import tier_limits as lilith
    from .releasez import PER_MONTH
    from .sonday import BOARDS as SONDAY
    from .catalog import AI_MODELS, ai_models_for
    from .models import AI_ENERGY_PER_PROMPT, ENERGY_FLOOR_PER_HOUR, PROMPT_ALLOWANCE
    wav = lambda t: {0: "MP3 only", 16: "16-bit WAV", 24: "24-bit WAV"}.get(C.MASTERING[t]["wav_bits"], "MP3 only")
    heaviest = lambda t: ", ".join(C.MASTERING_INTENSITY_LABELS[i] for i in C.MASTERING[t]["intensities"])
    rows = [
        # (group, key, label, tab, target, reader, unit, source)
        ("Everywhere", "daily_prompts", "Free AI prompts a day", "membershipz", "", _from(PROMPT_ALLOWANCE), "", "PROMPT_ALLOWANCE"),
        ("Everywhere", "ai_energy", "Energy one AI prompt takes (less is better)", "membershipz", "", _from(AI_ENERGY_PER_PROMPT), "⚡", "AI_ENERGY_PER_PROMPT"),
        # Gemini reads; Claude writes the answer. The best engine each plan may pick (the member may always pick a
        # lower one): Corey's ladder, read off AI_MODELS so the table and the gate cannot disagree.
        ("Everywhere", "ai_engine", "Best Claude engine that writes the AI's answers", "occ", "",
         lambda t: AI_MODELS[ai_models_for(t)[-1]]["name"], "", "AI_MODELS.tier"),
        ("Everywhere", "energy_floor", "Energy back every hour, at least", "membershipz", "", _from(ENERGY_FLOOR_PER_HOUR), "⚡", "ENERGY_FLOOR_PER_HOUR"),
        ("Everywhere", "char_limit", "Characters in a post", "postz", "post-compose", _lim("char_limit"), "", "tier_limits:char_limit"),
        ("Everywhere", "upload_mb", "Biggest single upload", "filez", "", _lim("upload_mb"), "MB", "tier_limits:upload_mb"),
        ("Everywhere", "storage_mb", "Storage", "filez", "", _lim("storage_mb"), "MB", "tier_limits:storage_mb"),
        ("Everywhere", "edit_window", "Minutes to edit a post after posting", "postz", "", lambda t: C.EDIT_WINDOW_SECONDS[t] // 60, "min", "EDIT_WINDOW_SECONDS"),
        ("PostZ & profile", "embeds_per_post", "Embeds in a post", "postz", "post-compose", _lim("embeds_per_post"), "", "tier_limits:embeds_per_post"),
        ("PostZ & profile", "profile_links", "Portfolio links", "profilez", "portfolio-links", _lim("profile_links"), "", "tier_limits:profile_links"),
        ("PostZ & profile", "widgets_open", "Widgets open at once", "profilez", "widgets", _lim("widgets_open"), "", "tier_limits:widgets_open"),
        ("PostZ & profile", "custom_groups", "Your own groups", "groupz", "", _lim("custom_groups"), "", "tier_limits:custom_groups"),
        ("PostZ & profile", "soundcloud_import", "SoundCloud tracks imported", "profilez", "", _lim("soundcloud_import"), "", "tier_limits:soundcloud_import"),
        ("PostZ & profile", "releases", "Tracks released a month (DistributeZ)", "distributez", "distributez-releases", _from(PER_MONTH), "", "releasez.PER_MONTH"),
        ("Make", "imagez_layers", "ImageZ layers in a picture", "imagez", "", _lim("imagez_layers"), "", "tier_limits:imagez_layers"),
        ("Make", "imagez_lists", "ImageZ filters, blend modes and adjustment presets", "imagez", "", _lim("imagez_layers"), "", "tier_limits:imagez_layers"),
        ("Make", "imagez_fonts", "ImageZ fonts", "imagez", "", _lim("imagez_fonts"), "", "tier_limits:imagez_fonts"),
        ("Make", "daw_tracks", "Tracks in a DAW session", "arsenal", "", _lim("imagez_layers"), "", "tier_limits:imagez_layers"),
        ("Make", "daw_vst", "VST effects on a track (Windows app)", "arsenal", "", _lim("imagez_layers"), "", "tier_limits:imagez_layers"),
        ("Make", "mix_tracks", "Tracks in a Mix ConnectZ mix", "mixconnectz", "mixz-tracks", _lim("imagez_layers"), "", "tier_limits:imagez_layers"),
        ("Make", "eq_bands", "EQ bands (TrackZ and every DAW's EQ)", "mixconnectz", "mixz-tracks", _lim("eq_bands"), "", "tier_limits:eq_bands"),
        ("Make", "split_opens", "PaneZ: times a day you can open a split page", "toolz", "", _lim("split_opens"), "", "tier_limits:split_opens"),
        ("Make", "glow_colors", "Glow colors you can choose from (the neon on buttons)", "profilez", "glow-color", _lim("glow_colors"), "", "tier_limits:glow_colors"),
        ("Make", "album_songs", "Songs mastered together as an album (Mix ConnectZ)", "mixconnectz", "mixz-album", _lim("album_songs"), "", "tier_limits:album_songs"),
        ("Make", "tone_presets", "Presets of each kind (track tone, track FX, mastering, channel strip)", "mixconnectz", "mixz-presets", _lim("tone_presets"), "", "tier_limits:tone_presets"),
        ("Make", "wav_bits", "Mastered export", "mixconnectz", "mixz-settings", wav, "", "MASTERING.wav_bits"),
        ("Make", "intensities", "Mastering intensities", "mixconnectz", "mixz-settings", heaviest, "", "MASTERING.intensities"),
        ("Make", "facez_faces", "Faces kept in FaceZ, and characters cast in MangaZ / Anime ConnectZ", "facez", "", _lim("facez_faces"), "", "tier_limits:facez_faces"),
        ("Make", "anime_shots", "Shots in an Anime ConnectZ piece", "animeconnectz", "animez-new", _lim("anime_shots"), "", "tier_limits:anime_shots"),
        ("Make", "writer_brief", "Characters in a Sentence ConnectZ brief", "sentenceconnectz", "sentencez-write", _from(C.WRITER_BRIEF_CHARS), "", "WRITER_BRIEF_CHARS"),
        ("Make", "custom_voices", "Custom writing voices", "sentenceconnectz", "", _from(C.CUSTOM_VOICE_LIMITS), "", "CUSTOM_VOICE_LIMITS"),
        ("Voice & keyboard", "key_clips", "Voice clips transcribed a day", "keyconnectz", "", _from(C.KEY_TRANSCRIBE_DAILY_CLIPS), "", "KEY_TRANSCRIBE_DAILY_CLIPS"),
        ("Voice & keyboard", "key_speak", "Characters read aloud a day (KeyConnectZ)", "keyconnectz", "", _from(C.KEY_SPEAK_DAILY_CHARS), "", "KEY_SPEAK_DAILY_CHARS"),
        ("Voice & keyboard", "coach_speak", "Characters the coach reads aloud a day", "singz", "", _from(C.COACH_SPEAK_DAILY_CHARS), "", "COACH_SPEAK_DAILY_CHARS"),
        ("Organise", "journal_per_day", "Journal entries a day", "journalz", "journalz-composer", _from(C.JOURNAL_LIMITS, "per_day"), "", "JOURNAL_LIMITS"),
        ("Organise", "journal_attachments", "Attachments on a journal entry", "journalz", "journalz-composer", _from(C.JOURNAL_LIMITS, "attachments"), "", "JOURNAL_LIMITS"),
        ("Organise", "bodiez_float", "BodieZ sessions kept on screen over other apps, a day", "bodiez", "today-float", _lim("bodiez_float"), "", "tier_limits:bodiez_float"),
        ("Organise", "lilith_routines", "Lilith routines", "lilith", "", lambda t: lilith(t)["routines"], "", "lilith.routines"),
        ("Organise", "lilith_tasks", "Lilith open tasks", "lilith", "", lambda t: lilith(t)["active_tasks"], "", "lilith.active_tasks"),
        ("Organise", "sonday_boards", "Sonday boards", "sonday", "", lambda t: SONDAY.get(t), "", "sonday.BOARDS"),
        ("Organise", "parcel", "Parcel Primate campaigns a week", "parcel", "", _from(C.PARCEL_PER_WEEK), "", "PARCEL_PER_WEEK"),
        ("Code", "occ_projects", "OCC projects", "occ", "", _from(C.OCC_PROJECTS), "", "OCC_PROJECTS"),
        ("Code", "occ_files", "Files in an OCC project", "occ", "", _from(C.OCC_PROJECT_FILES), "", "OCC_PROJECT_FILES"),
    ]
    out = []
    for group, key, label, tab, target, read, unit, source in rows:
        values = {t: _fmt(read(t), unit) for t in TIERS}
        out.append({"group": group, "key": key, "label": label, "kind": "count", "tab": tab, "target": target,
                    "source": source, "values": values,
                    # Corey's numbers: Free 3, Premium 6, StatZ unlimited. Said per row so the ones that differ are
                    # visible — whether they SHOULD move is his call, not this list's.
                    "coreys_numbers": values == COREYS})
    return out


def _access_rows():
    from .features import FEATURES, TIER_ORDER
    from . import statz_trial
    out = []
    for key, f in FEATURES.items():
        need = TIER_ORDER.index(f["tier"])
        out.append({"group": "Plans open", "key": f"feature:{key}", "label": f"{f.get('emoji', '')} {f['label']}".strip(),
                    "kind": "access", "tab": "", "target": "", "source": f"features.{key}", "note": f.get("blurb", ""),
                    "values": {t: ("✓" if TIER_ORDER.index(t) >= need else "—") for t in TIERS}})
    out.append({"group": "Plans open", "key": "specz", "label": "📐 SpecZ notes on any app", "kind": "access", "tab": "specz",
                "target": "", "source": "views.SpecZView", "note": "Priced in 🍥 on the button.",
                "values": {t: ("✓" if t == TIER_STATZ else "—") for t in TIERS}})
    sample = "Daily sample"
    for f in statz_trial.FEATURES:
        out.append({"group": "StatZ", "key": f"statz:{f['key']}", "label": f["label"], "kind": "access",
                    "tab": f.get("tab", ""), "target": f.get("target", ""), "source": f"statz_trial.{f['key']}",
                    "note": "Free and Premium can use it during the daily StatZ sample.",
                    "values": {TIER_FREE: sample, TIER_PREMIUM: sample, TIER_STATZ: "✓"}})
    return out


def ladders():
    return _rows() + _access_rows()


class LaddersView(APIView):
    """GET /api/economy/ladders/ — every gate and what each plan holds. Open logged-out (the same numbers
    the signup screen already reads); a signed-in caller is told which column is theirs."""
    permission_classes = [AllowAny]

    def get(self, request):
        mine = ""
        if request.user and request.user.is_authenticated:
            from .models import membership_for
            mine = membership_for(request.user).tier
        return Response({"tiers": list(TIERS), "labels": {TIER_FREE: "Free", TIER_PREMIUM: "Premium", TIER_STATZ: "StatZ"},
                         "mine": mine, "rows": ladders(),
                         "rule": "A plan says how much, never whether: every app opens on every plan."})
