"""ReligionZ — a declared religion, grouped into families, one filter,
every search.

Same shape as PersonalitieZ and for the same reason: this is a DECLARATION,
never a measurement, so the substance rule's test ("could a member get a good
one without getting good?") has no good one to ask about — there is no
ranking across fifty traditions and none is implied by list order or by
which family a tradition sits under.

- **It never touches a measurement.** No rating, median, skill level or
  leaderboard position moves because somebody picked a tradition. It filters
  WHO you see, same as gender, sign and personality already do in
  `MembersView`.
- **Nothing is inferred.** Never guessed from posts, takes, a name or
  anything else — a declared field stays declared, or it is
  `directz_ai_rating` wearing a different form.
- **Undeclared is a THIRD state**, exactly like personality's "-": `""` is
  "hasn't said", never a default and never folded into any one tradition's
  count.

The list is closed, grouped into families (Christianity → Catholic,
Lutheran, ...; Islam → Sunni, Shia, ...; and so on for every family with more
than one common branch), and served from here — never typed into a screen a
second time, the same reason a tier number lives in `catalog.py` and nowhere
else: a value stated in two places reads two ways within a year.

What is STORED and MATCHED on is always the leaf — `Profile.religion` holds
"catholic", never "christianity" — the same granularity gender and sign
already store at. The grouping is a picker convenience and a way to read the
list; it is not a second, coarser field.
"""

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

# Sixteen families covering the top 50 traditions by adherents worldwide —
# every family with more than one commonly-declared branch gets its
# branches listed under it (Christianity, Islam, Buddhism, East Asian
# traditions, Pagan & folk, Diasporic & indigenous, Nonreligious); a family
# with one common branch still gets its own group, so the shape is the same
# everywhere rather than special-cased for Christianity alone. Order groups
# related traditions for a picker that scrolls — it is NOT a ranking, and
# `key` is the only thing anything else may read.
RELIGION_GROUPS = (
    ("christianity", "Christianity", (
        ("catholic", "Catholic"),
        ("protestant", "Protestant"),
        ("orthodox_christian", "Orthodox Christian"),
        ("evangelical", "Evangelical"),
        ("baptist", "Baptist"),
        ("methodist", "Methodist"),
        ("lutheran", "Lutheran"),
        ("anglican", "Anglican / Episcopalian"),
        ("pentecostal", "Pentecostal"),
        ("adventist", "Seventh-day Adventist"),
        ("lds", "Latter-day Saint (Mormon)"),
        ("jehovahs_witness", "Jehovah's Witness"),
        ("quaker", "Quaker"),
        ("christian_other", "Christian — other"),
    )),
    ("islam", "Islam", (
        ("sunni", "Sunni"),
        ("shia", "Shia"),
        ("sufi", "Sufi"),
        ("muslim_other", "Muslim — other"),
    )),
    ("judaism", "Judaism", (
        ("judaism", "Jewish"),
    )),
    ("hinduism", "Hinduism", (
        ("hinduism", "Hindu"),
    )),
    ("buddhism", "Buddhism", (
        ("buddhism_theravada", "Theravada"),
        ("buddhism_mahayana", "Mahayana"),
        ("buddhism_vajrayana", "Vajrayana"),
    )),
    ("sikhism", "Sikhism", (
        ("sikhism", "Sikh"),
    )),
    ("jainism", "Jainism", (
        ("jainism", "Jain"),
    )),
    ("bahai", "Baháʼí", (
        ("bahai", "Baháʼí"),
    )),
    ("east_asian", "East Asian traditions", (
        ("shinto", "Shinto"),
        ("taoism", "Taoist"),
        ("confucianism", "Confucian"),
        ("falun_gong", "Falun Gong"),
        ("tenrikyo", "Tenrikyo"),
        ("caodaism", "Cao Đài"),
    )),
    ("zoroastrianism", "Zoroastrianism", (
        ("zoroastrianism", "Zoroastrian"),
    )),
    ("levantine", "Other Middle Eastern traditions", (
        ("druze", "Druze"),
        ("yazidi", "Yazidi"),
    )),
    ("rastafari", "Rastafari", (
        ("rastafari", "Rastafari"),
    )),
    ("pagan_folk", "Pagan & folk traditions", (
        ("paganism", "Pagan"),
        ("wicca", "Wiccan"),
        ("druidry", "Druid"),
        ("animism", "Animist"),
        ("shamanism", "Shamanist"),
    )),
    ("diasporic_indigenous", "Diasporic & indigenous traditions", (
        ("santeria", "Santería"),
        ("voodoo", "Voodoo"),
        ("candomble", "Candomblé"),
        ("indigenous", "Indigenous / Native spirituality"),
        ("african_traditional", "African Traditional Religion"),
    )),
    ("nonreligious", "Nonreligious", (
        ("agnostic", "Agnostic"),
        ("atheist", "Atheist"),
        ("spiritual_not_religious", "Spiritual, not religious"),
    )),
    ("other", "Other", (
        ("other", "Other"),
    )),
)

# The flat top-50, derived rather than typed a second time — the exact trap
# the module docstring warns about, one level down.
RELIGIONS = tuple(leaf for _, _, leaves in RELIGION_GROUPS for leaf in leaves)

# Asserted on import rather than trusted, same as personalityz's letter
# check — a duplicated key would make two rows answer to the same filter,
# silently. `clean_religion` only ever checks a value against the LEAF set
# below, never the group set, so the two namespaces never need to agree with
# each other — a single-branch family's group key and its one leaf sharing a
# spelling (e.g. "judaism"/"judaism") is fine for exactly that reason.
assert len(RELIGIONS) == 50, "the picker promises the top 50 — keep the count honest"
_KEYS = {k for k, _ in RELIGIONS}
assert len(_KEYS) == len(RELIGIONS), "a duplicated leaf key would make two rows the same filter"
_GROUP_KEYS = {g for g, _, _ in RELIGION_GROUPS}
assert len(_GROUP_KEYS) == len(RELIGION_GROUPS), "a duplicated group key"


def clean_religion(value):
    """Normalize whatever arrived to a valid LEAF key, or "" for nothing said.

    Always the leaf, never the group — "christianity" is not a valid stored
    value any more than "protestant" alone would be a valid group. An
    unrecognised value clears rather than refuses, the same rule
    `personalityz.clean_code` follows: a profile write must not 400 over one
    bad value, and a wrong value silently kept is worse than a blank one.
    """
    key = str(value or "").strip().lower()
    return key if key in _KEYS else ""


class ReligionsView(APIView):
    """GET /api/economy/religionz/ — the closed list, grouped into families,
    never typed into a screen a second time.

    Open logged-out, same reason `personalityz` and `rulez` are: the screen
    that renders this picker is ProfileZ, and a stranger reads the join page
    before deciding whether to make an account at all.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({
            "groups": [
                {"key": g, "label": label,
                 "options": [{"key": k, "label": l} for k, l in leaves]}
                for g, label, leaves in RELIGION_GROUPS
            ],
            "note": ("A declaration, never a score — no tradition or family on this "
                     "list is ranked above another, and picking one never moves a "
                     "rating, a skill level or a leaderboard position. Leave it "
                     "blank and it stays \"hasn't said\", not a default."),
        })
