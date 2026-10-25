"""Every door OCC offers lands on a tab that exists, on an anchor that exists.

The audit that wrote this found three families of dead door, all with the same
symptom — the click plays the open-in sound and the member stays where they are:

* `EXPORT_ROUTES` named `imagez` and `writez`, which are not tabs anywhere, and
  routed code to `occ` itself;
* WorkZ's "Share to PostZ" went to `social`/`social-compose` (PostZ is `postz`,
  and its anchors are `composer` and `feed`);
* the tab grid's "Open →" went to `occ:<key>`, an anchor that exists nowhere.

None of them errors. A tab key the client does not mount is just a string, and
`goToSpot` to it is a sound effect. So the list of real tab keys is held HERE,
explicitly, and every route the backend serves is checked against it.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.features import FEATURES, required_tier
from apps.economy.models import OccOutput
from apps.economy.occ_spec import EXPORT_ROUTES, OCC_LANGUAGES, OCC_TABS, OCC_TOGGLES
from apps.economy.occ_workz import _send_targets

User = get_user_model()

# The tab keys the frontend MOUNTS: the `key:` of every entry in App.jsx's TABS
# (frontend repo, src/App.jsx). Typed here on purpose — the backend cannot read
# the other repo, and a door to a key that is not in this list is a dead button.
# The frontend's own `occRoutes.test.mjs` parses App.jsx and fails if this copy
# of the list (kept there as OCC_DOORS) names anything that is not in TABS.
# When a tab is added to or removed from App.jsx, change this list with it.
MOUNTED_TABS = frozenset({
    "toolz", "onboardz", "postz", "playlistz", "social", "vybez",
    "soundcloudengagementz", "coachz", "profilez", "personaz", "preferencez",
    "substancez", "zodiacz", "facez", "distributez", "ratez", "sonday", "parcel",
    "merchz", "beatz", "statsz", "opportunitiez", "specz", "membershipz", "adz",
    "offerz", "mimez", "directz", "lessonz", "singz", "rapz", "guitarz", "bassz",
    "keyz", "violinz", "messagez", "keyconnectz", "sentenceconnectz",
    "instrumentalconnectz", "viewz", "videoconnectz", "occ", "logz", "royaltiez",
    "callz", "gamez", "soundz", "metz", "tunerz", "chordz", "drumz", "journalz",
    "habitz", "lilith", "bodiez", "collabz", "venuez", "battlez", "labelz",
    "groupz", "bugz", "dawz", "funnelz", "dupez", "iconz",
    "filez", "characterz", "mangaz",
})

# The data-tour anchors on OCC's own screen (OCC.jsx and components/occ/).
# The frontend test checks each of these really is in the source.
OCC_ANCHORS = frozenset({
    "occ-chat", "occ-taskz", "occ-run", "occ-workz", "occ-suggest", "occ-settings",
})

MEDIA_TYPES = ["", "audio", "video", "image", "document", "code", "game"]


class EveryRouteIsATabTheClientMounts(TestCase):
    def test_export_routes_name_mounted_tabs_or_nothing(self):
        for kind, route in EXPORT_ROUTES.items():
            if route["app"]:
                self.assertIn(route["app"], MOUNTED_TABS, kind)
                self.assertTrue(route["label"], f"{kind} needs a human label")
            else:
                # No destination: no target and no label either, so nothing can
                # half-render a door.
                self.assertEqual((route["target"], route["label"]), ("", ""), kind)

    def test_code_is_never_routed_back_to_occ(self):
        self.assertEqual(EXPORT_ROUTES["code"]["app"], "")

    def test_every_workz_door_for_every_media_type_is_a_mounted_tab(self):
        u = User.objects.create_user("w", "w@e.com", "hunter2hunter2")
        for media in MEDIA_TYPES:
            o = OccOutput.objects.create(user=u, title="t", media_type=media,
                                         media_url="/u/x.mp3" if media == "audio" else "")
            for row in _send_targets(o):
                self.assertIn(row["tab"], MOUNTED_TABS, (media, row["key"]))

    def test_the_tab_grid_only_opens_mounted_tabs_and_real_anchors(self):
        for tab in OCC_TABS:
            if not tab["built"]:
                self.assertNotIn("open_in", tab, f"{tab['key']} is not built: no door")
                continue
            self.assertIn(tab["open_in"], MOUNTED_TABS, tab["key"])
            if tab["open_in"] == "occ":
                self.assertIn(tab["target"], OCC_ANCHORS, tab["key"])

    def test_a_built_tab_always_says_where_it_lands(self):
        for tab in OCC_TABS:
            self.assertIn("built", tab, tab["key"])
            if tab["built"]:
                self.assertIn("open_in", tab, tab["key"])
                self.assertIn("target", tab, tab["key"])

    def test_the_tabs_that_have_a_screen_are_the_ones_marked_built(self):
        built = {t["key"] for t in OCC_TABS if t["built"]}
        # The audit found seven advertising a screen OCC did not have. FileZ and
        # CharacterZ have mounted tabs of their own since, so they open those —
        # the same shape as LogZ and CallZ below; the other five still have none.
        for key in ("editor", "console", "gitz", "tellz", "search"):
            self.assertNotIn(key, built, key)
        # CallZ and GameZ are mounted tabs and were missing a door.
        for key in ("callz", "gamez", "taskz", "workz", "settings", "logz", "filez", "characterz"):
            self.assertIn(key, built, key)


class GatesAreReadNotRetyped(TestCase):
    """A second copy of a gate is how the tab grid told Free members to upgrade
    for LogZ, which features.py (and test_logz) say is free."""

    def test_logz_is_free_in_the_grid(self):
        tabs = {t["key"]: t for t in OCC_TABS}
        self.assertEqual(tabs["logz"]["needs"], required_tier("logz"))
        self.assertEqual(required_tier("logz"), "free")

    def test_every_tab_that_has_a_feature_uses_its_tier(self):
        tabs = {t["key"]: t for t in OCC_TABS}
        for tab_key, feature in (("logz", "logz"), ("tellz", "tellz"),
                                 ("gitz", "gitz"), ("gamez", "occ_games")):
            self.assertIn(feature, FEATURES)
            self.assertEqual(tabs[tab_key]["needs"], required_tier(feature), tab_key)

    def test_the_toggles_and_languages_read_features_too(self):
        toggles = {t["key"]: t for t in OCC_TOGGLES}
        self.assertEqual(toggles["automation"]["needs"], required_tier("automationz"))
        self.assertEqual(toggles["suggestionz"]["needs"], required_tier("suggestionz"))
        for lang in OCC_LANGUAGES:
            want = required_tier("occ_cpp") if lang["key"] in ("cpp", "c") else required_tier("occ_games")
            self.assertEqual(lang["needs"], want, lang["key"])


class TheSpecServesTheDoors(TestCase):
    def test_built_and_target_travel_with_each_tab(self):
        c = APIClient()
        c.force_authenticate(User.objects.create_user("s", "s@e.com", "hunter2hunter2"))
        tabs = {t["key"]: t for t in c.get("/api/economy/occ/spec/").data["tabs"]}
        self.assertTrue(tabs["taskz"]["built"])
        self.assertEqual((tabs["taskz"]["open_in"], tabs["taskz"]["target"]), ("occ", "occ-taskz"))
        self.assertFalse(tabs["editor"]["built"])
        self.assertNotIn("open_in", tabs["editor"])
