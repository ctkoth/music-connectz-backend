"""Creator-app manifest — the single source of truth the frontend reads to render
every creator tab consistently and wire it into the rest of Music ConnectZ.

Each entry declares:
  key            url/app key (matches /api/<key>/...)
  label, emoji   display
  icon           asset filename under /icons/ (the neon plate art)
  color          accent
  role           ProfileZ persona this app credits (ZodiacZ/persona system)
  skill_app_key  SkillZ engine key — gamified like SingZ/RapZ (train/* endpoints)
  gamified       bool — has SkillZ tracks/drills
  youth_safe     bool — open to youth accounts
  adult_only     bool — requires age-verified adult
  premium        bool — requires Premium+
  live           marketplace type: "" | "anr" | "management" (real-people, adult-gated)
  post_types     PostZ types this app can publish into the universal Post model
  workspace      primary CRUD collections (Z-pluralized)
"""

CREATOR_APPS = [
    {
        "key": "gamez", "label": "GameZ", "emoji": "\U0001F3AE", "icon": "gamez.png",
        "color": "#a855f7", "role": "Developer", "skill_app_key": "gamez",
        "gamified": True, "youth_safe": True, "adult_only": False, "premium": True,
        "live": "", "post_types": ["game"],
        "workspace": ["games"],
        "editor": "occ", "import_allowed": False,
        "tiers": {"premium": "code in OCC + AI suggestions", "statz": "auto mode + Unreal route"},
        "genres_endpoint": "gamez/genres/",
        "media_routing": "non-owner -> Intelligence; owner -> export",
        "desc": "Build games in OCC. Premium codes with AI suggestions; StatZ unlocks auto mode + the Unreal Engine route. Pick a genre or let AI detect it.",
    },
    {
        "key": "designz", "label": "DesignZ", "emoji": "🖌️", "icon": "designz.png",
        "color": "#f59e0b", "role": "Designer", "skill_app_key": "designz",
        "gamified": True, "youth_safe": True, "adult_only": False, "premium": False,
        "live": "", "post_types": ["image"],
        "workspace": ["projectz", "assetz", "templatez", "brand-kitz", "palettez"],
        "editor": "imagez",            # edit challenge work IN-APP via ImageZ
        "import_allowed": True,        # or import from anywhere to complete a challenge
        "challenge_submit": "designz/train/submit/",
        "desc": "Designer training + brand-kit workspace. Edit in ImageZ or import anything, then submit for a score.",
    },
    {
        "key": "shotz", "label": "ShotZ", "emoji": "🎥", "icon": "shotz.png",
        "color": "#22d3ee", "role": "Videographer", "skill_app_key": "shotz",
        "gamified": True, "youth_safe": True, "adult_only": False, "premium": False,
        "live": "", "post_types": ["video"],
        "workspace": ["projectz", "clipz", "footage", "storyboardz", "shotlistz", "locationz", "renderz"],
        "editor": "videoz", "import_allowed": True,
        "challenge_submit": "shotz/train/submit/",
        "desc": "Videographer bay — edit in VideoZ or import anything, then submit for a score.",
    },
    {
        "key": "writez", "label": "WriteZ", "emoji": "✍️", "icon": "writez.png",
        "color": "#a855f7", "role": "Ghostwriter", "skill_app_key": "writez",
        "gamified": True, "youth_safe": True, "adult_only": False, "premium": False,
        "live": "", "post_types": ["text"],
        "workspace": ["documentz", "draftz"],
        "editor": "sentencez", "import_allowed": True,
        "challenge_submit": "writez/train/submit/",
        "desc": "Creative-writer training. Write in SentenceZ or import anything, then submit for a score.",
    },
    {
        "key": "producez", "label": "ProduceZ", "emoji": "🎹", "icon": "producez.png",
        "color": "#eab308", "role": "Beat Producer", "skill_app_key": "producez",
        "gamified": True, "youth_safe": True, "adult_only": False, "premium": False,
        "live": "", "post_types": ["audio"],
        "workspace": [],
        "desc": "Producer training — drum programming, sound design, sampling, arrangement.",
    },
    {
        "key": "mixez", "label": "MixeZ", "emoji": "🎚️", "icon": "mixez.png",
        "color": "#10b981", "role": "Mix Engineer", "skill_app_key": "mixez",
        "gamified": True, "youth_safe": True, "adult_only": False, "premium": False,
        "live": "", "post_types": ["audio"],
        "workspace": [],
        "desc": "Mix-engineer training — gain staging, EQ, compression, the bus.",
    },
    {
        "key": "developz", "label": "DevelopZ", "emoji": "💻", "icon": "developz.png",
        "color": "#3b82f6", "role": "Engineer", "skill_app_key": "developz",
        "gamified": True, "youth_safe": True, "adult_only": False, "premium": False,
        "live": "", "post_types": ["text"],
        "workspace": ["projectz", "snippetz"],
        "desc": "Developer training — pairs with OCC for in-platform coding.",
    },
    {
        "key": "scoutz", "label": "ScoutZ", "emoji": "🔎", "icon": "scoutz.png",
        "color": "#06b6d4", "role": "A&R Scout", "skill_app_key": "scoutz",
        "gamified": True, "youth_safe": False, "adult_only": True, "premium": True,
        "live": "anr", "post_types": [],
        "workspace": ["prospectz", "reportz", "taskz"],
        "desc": "A&R training + private CRM + LIVE marketplace: real A&R ↔ adult artists.",
    },
    {
        "key": "managez", "label": "ManageZ", "emoji": "📋", "icon": "managez.png",
        "color": "#f97316", "role": "Manager", "skill_app_key": "managez",
        "gamified": True, "youth_safe": False, "adult_only": True, "premium": False,
        "live": "management", "post_types": [],
        "workspace": ["rosterz", "clientz", "contractz", "bookingz", "dealz", "invoicez", "payoutz", "taskz"],
        "desc": "Manager training + back office + LIVE marketplace: real managers ↔ adult artists.",
    },
]


def manifest_for(user=None):
    """Return the creator-app registry. (User-aware fields could be layered later;
    gating is enforced server-side per endpoint regardless of what we expose here.)"""
    return {"version": 1, "apps": CREATOR_APPS}
