"""The three Android apps must stay three coherent apps.

Nothing here runs Gradle — CI does that, and there is no Android SDK on a dev
box. What a unit test CAN hold is the set of facts that, when they drift, ship an
app that builds green and misbehaves on a member's phone:

- the packages are distinct (three listings cannot share one),
- each app's `asset_statements` names the site that app opens (otherwise the URL
  bar comes back, which a Play reviewer reads as a repackaged website),
- the BodieZ and IntelligenceZ flavors' resources reference only things that exist
  (a missing drawable is an AAPT error in CI, found after the merge rather than
  before),
- their art is the size Android and Play expect, since the generators are scripts
  nobody re-runs until something looks wrong.
"""
import importlib.util
import re
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "android" / "app"
GRADLE = (APP / "build.gradle.kts").read_text()
FLAVORS = ("mcz", "bodiez", "intelligencez")
# Flavors with a source set of their own (main's is the Music ConnectZ app).
OWN_RES = ("bodiez", "intelligencez")


def _flavor(name):
    start = GRADLE.index(f'create("{name}")')
    return GRADLE[start:GRADLE.index("}", start)]


class AndroidFlavorTests(SimpleTestCase):
    def test_three_distinct_packages(self):
        ids = {n: re.search(r'applicationId = "([^"]+)"', _flavor(n)).group(1) for n in FLAVORS}
        self.assertEqual(ids, {"mcz": "net.musicconnectz.app", "bodiez": "net.musicconnectz.bodiez",
                               "intelligencez": "net.musicconnectz.intelligencez"})
        self.assertEqual(len(set(ids.values())), 3)

    def test_only_music_connectz_opens_the_omviardz_tour(self):
        # BodieZ opens a site with no OmviardZ in it; a `?omviardz=1` there is a
        # dead parameter on a screen that has never heard of it.
        self.assertIn('"FIRST_LAUNCH_TOUR", "true"', _flavor("mcz"))
        self.assertIn('"FIRST_LAUNCH_TOUR", "false"', _flavor("bodiez"))
        self.assertIn('"FIRST_LAUNCH_TOUR", "false"', _flavor("intelligencez"))

    def test_each_app_opens_its_own_site(self):
        # BodieZ opens the BodieZ-only build on its own host, never a path on the
        # main site: the main site is what carries the profile, orientation and
        # purchase screens the BodieZ listing exists to stay clear of.
        self.assertIn("bodiezUrl", _flavor("bodiez"))
        self.assertNotIn("siteUrl", _flavor("bodiez"))
        self.assertNotIn("/bodie\"", _flavor("bodiez"))
        # IntelligenceZ is the same decision for the same reason: its shell is
        # sign-in and four IntelligenceZ screens, and a path on the main site would
        # bring the whole platform (and its purchase flow) with it.
        self.assertIn("intelligencezUrl", _flavor("intelligencez"))
        self.assertNotIn("siteUrl", _flavor("intelligencez"))
        self.assertNotIn("bodiezUrl", _flavor("intelligencez"))

    def test_asset_statements_name_the_site_each_app_opens(self):
        main = (APP / "src/main/res/values/strings.xml").read_text()
        bodiez = (APP / "src/bodiez/res/values/strings.xml").read_text()
        iz = (APP / "src/intelligencez/res/values/strings.xml").read_text()
        site = re.search(r'"siteUrl"\)\s+as String\?\)\s*\?:\s*"([^"]+)"', GRADLE).group(1)
        bodiez_site = re.search(r'"bodiezUrl"\)\s+as String\?\)\s*\?:\s*"([^"]+)"', GRADLE).group(1)
        iz_site = re.search(r'"intelligencezUrl"\)\s+as String\?\)\s*\?:\s*"([^"]+)"', GRADLE).group(1)
        self.assertIn(f'"site": "{site}"', main)
        self.assertIn(f'"site": "{bodiez_site}"', bodiez)
        self.assertIn(f'"site": "{iz_site}"', iz)
        # Three apps, three hosts: Chrome verifies a TWA against the host it
        # opens, so two apps on one host would contest one assetlinks.json.
        self.assertEqual(len({site, bodiez_site, iz_site}), 3)

    def test_the_build_checks_every_flavors_asset_statements(self):
        # checkAssetStatements is what fails the build when a string drifts from
        # its -P property. A flavor missing from it ships a URL bar on the day
        # somebody overrides the host and forgets the string.
        for res in ("src/main", "src/bodiez", "src/intelligencez"):
            self.assertIn(f'"{res}/res/values/strings.xml"', GRADLE)
        self.assertIn('inputs.property("intelligencezUrl", intelligencezUrl)', GRADLE)

    def test_workflow_builds_and_uploads_every_flavor(self):
        wf = (ROOT / ".github" / "workflows" / "android.yml").read_text()
        for name in ("Mcz", "Bodiez", "Intelligencez"):
            self.assertIn(f"assemble{name}Debug", wf)
            self.assertIn(f"bundle{name}Release", wf)
        for artifact in ("music-connectz-apk", "bodiez-apk", "intelligencez-apk",
                         "music-connectz-playstore-bundle", "bodiez-playstore-bundle",
                         "intelligencez-playstore-bundle"):
            self.assertIn(f"name: {artifact}", wf)
        self.assertIn("intelligencez_url:", wf)
        self.assertIn("-PintelligencezUrl=", wf)

    def test_flavor_resources_resolve(self):
        for flavor in OWN_RES:
            have = set()
            for res in (APP / "src/main/res", APP / f"src/{flavor}/res"):
                for f in res.rglob("*"):
                    if not f.is_file():
                        continue
                    kind = f.parent.name.split("-")[0]
                    if kind in ("drawable", "mipmap"):
                        have.add(f"@{kind}/{f.stem}")
                    elif kind == "values":
                        for m in re.finditer(r'<(color|string|style)\s+name="([^"]+)"', f.read_text()):
                            have.add(f"@{m.group(1)}/{m.group(2)}")
            missing = []
            for f in (APP / f"src/{flavor}/res").rglob("*.xml"):
                for ref in re.findall(r"@(?:drawable|color|mipmap|string)/[A-Za-z0-9_]+", f.read_text()):
                    if ref not in have:
                        missing.append((f.relative_to(APP).as_posix(), ref))
            self.assertEqual(missing, [], flavor)

    def test_each_flavor_overrides_what_makes_it_that_app(self):
        # A flavor that forgets its launcher icon or its name ships as the Music
        # ConnectZ app under another package id, which is the one failure here a
        # member can see on their home screen.
        for flavor in OWN_RES:
            res = APP / f"src/{flavor}/res"
            for f in ("mipmap-anydpi-v26/ic_launcher.xml", "mipmap-anydpi-v26/ic_launcher_round.xml",
                      "values/strings.xml", "values/colors.xml", "values-v31/themes.xml", "drawable/splash.xml"):
                self.assertTrue((res / f).is_file(), f"{flavor}: {f}")
        self.assertIn('name="app_name">IntelligenceZ<', (APP / "src/intelligencez/res/values/strings.xml").read_text())


class BodiezArtTests(SimpleTestCase):
    def _size(self, path):
        from PIL import Image
        with Image.open(path) as im:
            return im.size, im.mode

    def test_play_graphics_have_the_sizes_play_requires(self):
        play = ROOT / "brand" / "play" / "bodiez"
        self.assertEqual(self._size(play / "icon-512.png"), ((512, 512), "RGBA"))
        self.assertEqual(self._size(play / "feature-graphic-1024x500.png")[0], (1024, 500))

    def test_adaptive_layers_are_108dp_at_xxxhdpi(self):
        res = APP / "src/bodiez/res/drawable-nodpi"
        for name in ("ic_bodiez_foreground", "ic_bodiez_monochrome"):
            self.assertEqual(self._size(res / f"{name}.png")[0], (432, 432), name)


class IntelligencezArtTests(SimpleTestCase):
    """The IntelligenceZ generator is `android/tools/make_intelligencez_assets.py`.
    These load it, so a size that drifts is a failing test and not a launcher
    icon that is quietly blurry or clipped."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        path = ROOT / "android" / "tools" / "make_intelligencez_assets.py"
        spec = importlib.util.spec_from_file_location("make_intelligencez_assets", path)
        cls.gen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.gen)

    def _size(self, path):
        from PIL import Image
        with Image.open(path) as im:
            return im.size, im.mode

    def test_adaptive_layers_are_108dp_at_xxxhdpi(self):
        res = APP / "src/intelligencez/res/drawable-nodpi"
        for name in ("ic_intelligencez_foreground", "ic_intelligencez_monochrome"):
            self.assertEqual(self._size(res / f"{name}.png")[0], (432, 432), name)
        self.assertEqual(self._size(res / "ic_intelligencez_splash.png")[0], (352, 352))

    def test_the_name_in_the_art_clears_a_circular_mask(self):
        # The sign's name sits near its top edge; a launcher that masks to a circle
        # would take the ends of "IntelligenceZ" if the art were any larger.
        self.assertTrue(self.gen.title_clears(self.gen.ART_SIDE))
        self.assertFalse(self.gen.title_clears(432), "the check must be able to fail")

    def test_play_graphics_have_the_sizes_play_requires(self):
        with tempfile.TemporaryDirectory() as tmp:
            icon, feature = Path(tmp) / "icon-512.png", Path(tmp) / "feature.png"
            self.gen.play_icon(str(icon))
            self.gen.feature_graphic(str(feature))
            self.assertEqual(self._size(icon), ((512, 512), "RGBA"))
            self.assertEqual(self._size(feature)[0], (1024, 500))

    def test_the_source_is_not_upscaled(self):
        # Every output is at most 512px, so the 1024px source is always downscaled.
        self.assertGreaterEqual(self._size(self.gen.SOURCE)[0][0], 1024)
