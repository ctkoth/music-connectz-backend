"""The two Android apps must stay two coherent apps.

Nothing here runs Gradle — CI does that, and there is no Android SDK on a dev
box. What a unit test CAN hold is the set of facts that, when they drift, ship an
app that builds green and misbehaves on a member's phone:

- the packages are distinct (two listings cannot share one),
- each app's `asset_statements` names the site that app opens (otherwise the URL
  bar comes back, which a Play reviewer reads as a repackaged website),
- the BodieZ flavor's resources reference only things that exist (a missing
  drawable is an AAPT error in CI, found after the merge rather than before),
- the BodieZ art is the size Android and Play expect, since the generator is a
  script nobody re-runs until something looks wrong.
"""
import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "android" / "app"
GRADLE = (APP / "build.gradle.kts").read_text()


def _flavor(name):
    start = GRADLE.index(f'create("{name}")')
    return GRADLE[start:GRADLE.index("}", start)]


class AndroidFlavorTests(SimpleTestCase):
    def test_two_distinct_packages(self):
        ids = {n: re.search(r'applicationId = "([^"]+)"', _flavor(n)).group(1) for n in ("mcz", "bodiez")}
        self.assertEqual(ids, {"mcz": "net.musicconnectz.app", "bodiez": "net.musicconnectz.bodiez"})

    def test_only_music_connectz_opens_the_omviardz_tour(self):
        # BodieZ opens a site with no OmviardZ in it; a `?omviardz=1` there is a
        # dead parameter on a screen that has never heard of it.
        self.assertIn('"FIRST_LAUNCH_TOUR", "true"', _flavor("mcz"))
        self.assertIn('"FIRST_LAUNCH_TOUR", "false"', _flavor("bodiez"))

    def test_each_app_opens_its_own_site(self):
        # BodieZ opens the BodieZ-only build on its own host, never a path on the
        # main site: the main site is what carries the profile, orientation and
        # purchase screens the BodieZ listing exists to stay clear of.
        self.assertIn("bodiezUrl", _flavor("bodiez"))
        self.assertNotIn("siteUrl", _flavor("bodiez"))
        self.assertNotIn("/bodie\"", _flavor("bodiez"))

    def test_asset_statements_name_the_site_each_app_opens(self):
        main = (APP / "src/main/res/values/strings.xml").read_text()
        bodiez = (APP / "src/bodiez/res/values/strings.xml").read_text()
        site = re.search(r'"siteUrl"\)\s+as String\?\)\s*\?:\s*"([^"]+)"', GRADLE).group(1)
        bodiez_site = re.search(r'"bodiezUrl"\)\s+as String\?\)\s*\?:\s*"([^"]+)"', GRADLE).group(1)
        self.assertIn(f'"site": "{site}"', main)
        self.assertIn(f'"site": "{bodiez_site}"', bodiez)
        self.assertNotEqual(site, bodiez_site)

    def test_bodiez_flavor_resources_resolve(self):
        have = set()
        for res in (APP / "src/main/res", APP / "src/bodiez/res"):
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
        for f in (APP / "src/bodiez/res").rglob("*.xml"):
            for ref in re.findall(r"@(?:drawable|color|mipmap|string)/[A-Za-z0-9_]+", f.read_text()):
                if ref not in have:
                    missing.append((f.relative_to(APP).as_posix(), ref))
        self.assertEqual(missing, [])


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
