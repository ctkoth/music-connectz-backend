"""GameZ — the tab that pointed nowhere.

`occ_spec.py` has advertised a GameZ tab and `EXPORT_ROUTES["game"]` has routed
to `gamez:mine` since the taxonomy was written, with nothing behind either. Same
shape as BugZ's `/api/bugz/`, which 404'd under a 200 SpinaZ promise.

Two things these tests hold hardest: that `playable` is computed from a real
bundle rather than asserted by a status field, and that game assets count
against the storage a member's tier actually sells them.
"""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.catalog import limits_for
from apps.economy.gamez import clean_genre
from apps.economy.models import (
    MB,
    TIER_FREE,
    TIER_STATZ,
    Game,
    GameAsset,
    OccFile,
    Upload,
    membership_for,
    storage_used_bytes,
)
from apps.economy.occ_spec import GAME_GENRE_KEYS, GAME_SUBGENRES

User = get_user_model()
PW = "hunter2hunter2"
URL = "/api/economy/gamez/"


def asset(name="hero.png", size=1000, ct="image/png"):
    return SimpleUploadedFile(name, b"0" * size, content_type=ct)


class Base(TestCase):
    tier = TIER_STATZ

    def setUp(self):
        self.user = User.objects.create_user("dev", "d@e.com", PW)
        m = membership_for(self.user)
        m.tier = self.tier
        m.save()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def make(self, **kw):
        body = {"title": "Cave Runner", **kw}
        return self.client.post(URL, body, format="json")


class TheTaxonomyHasOneHome(TestCase):
    def test_a_subgenre_alone_finds_its_own_genre(self):
        # genre_of already exists. A client that sends "Metroidvania" shouldn't
        # be refused for not also repeating "action_adventure".
        genre, sub = clean_genre(None, "Metroidvania")
        self.assertEqual(genre, "action_adventure")
        self.assertEqual(sub, "Metroidvania")

    def test_a_genre_alone_is_kept(self):
        self.assertEqual(clean_genre("puzzle", None), ("puzzle", ""))

    def test_something_unrecognised_is_dropped_not_refused(self):
        # A game with no genre is fine. A 400 because somebody typed a genre we
        # don't list is not.
        self.assertEqual(clean_genre("interpretive-dance", "Yodelling"), ("", ""))

    def test_every_subgenre_in_the_spec_resolves(self):
        for sub in GAME_SUBGENRES:
            with self.subTest(subgenre=sub):
                genre, kept = clean_genre(None, sub)
                self.assertEqual(kept, sub)
                self.assertIn(genre, GAME_GENRE_KEYS)


class TheTabIsServed(Base):
    def test_the_endpoint_the_spec_advertises_exists(self):
        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_the_genre_list_is_served_not_hardcoded_on_the_client(self):
        genres = self.client.get(URL).json()["genres"]
        self.assertEqual(len(genres), 17)
        self.assertTrue(all(g["subgenres"] for g in genres))

    def test_the_screen_is_told_what_kind_of_games_these_are(self):
        # Said up front. A member who spends a week on a Unity project before
        # finding out is a member who was allowed to waste a week.
        note = self.client.get(URL).json()["note"]
        self.assertIn("Unity", note)

    def test_storage_headroom_is_stated(self):
        d = self.client.get(URL).json()
        self.assertEqual(d["storage_mb"], limits_for(TIER_STATZ)["storage_mb"])
        self.assertIn("storage_left_mb", d)

    def test_anonymous_callers_are_turned_away(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)


class MakingAGame(Base):
    def test_a_game_starts_as_a_draft_with_nothing_to_play(self):
        d = self.make(subgenre="Metroidvania").json()
        self.assertEqual(d["status"], Game.STATUS_DRAFT)
        self.assertFalse(d["playable"])
        self.assertEqual(d["bundle_url"], "")
        self.assertEqual(d["genre"], "action_adventure")

    def test_a_title_is_required(self):
        self.assertEqual(self.make(title="   ").status_code, 400)

    def test_a_game_can_be_renamed_and_refiled(self):
        pk = self.make().json()["id"]
        resp = self.client.patch(f"{URL}{pk}/",
                                 {"title": "Cave Runner II", "subgenre": "Soulslike"},
                                 format="json")
        self.assertEqual(resp.json()["title"], "Cave Runner II")
        self.assertEqual(resp.json()["genre"], "rpg")

    def test_a_game_cannot_be_renamed_to_nothing(self):
        pk = self.make().json()["id"]
        self.assertEqual(
            self.client.patch(f"{URL}{pk}/", {"title": ""}, format="json").status_code,
            400)

    def test_the_game_counts_the_project_files_behind_it(self):
        pk = self.make(project="game").json()["id"]
        OccFile.objects.create(user=self.user, project="game", path="index.html")
        OccFile.objects.create(user=self.user, project="game", path="main.js")
        self.assertEqual(self.client.get(f"{URL}{pk}/").json()["files"], 2)

    def test_one_members_games_are_not_anothers(self):
        pk = self.make().json()["id"]
        other = User.objects.create_user("other", "o@e.com", PW)
        membership_for(other)
        theirs = APIClient()
        theirs.force_authenticate(other)
        self.assertEqual(theirs.get(f"{URL}{pk}/").status_code, 404)
        self.assertEqual(theirs.get(URL).json()["games"], [])

    def test_deleting_a_game_leaves_the_members_uploads_alone(self):
        # A sprite reused across two games shouldn't vanish because one went.
        pk = self.make().json()["id"]
        self.client.post(f"{URL}{pk}/assets/", {"file": asset(), "path": "a.png"})
        self.client.delete(f"{URL}{pk}/")
        self.assertFalse(Game.objects.filter(pk=pk).exists())
        self.assertFalse(GameAsset.objects.filter(game_id=pk).exists())
        self.assertEqual(Upload.objects.filter(user=self.user).count(), 1)


class PlayableIsComputedNotAsserted(Base):
    def test_a_status_alone_never_makes_a_game_playable(self):
        # A Play button offered on a status with no file behind it is a button
        # that lies — the exact failure this whole tab exists to stop repeating.
        game = Game.objects.create(user=self.user, title="Ghost",
                                   status=Game.STATUS_PLAYABLE)
        self.assertFalse(game.playable)
        self.assertFalse(self.client.get(f"{URL}{game.id}/").json()["playable"])

    def test_a_bundle_alone_is_not_enough_either(self):
        game = Game.objects.create(user=self.user, title="Half-built",
                                   status=Game.STATUS_BUILDING)
        game.bundle.save("b.zip", SimpleUploadedFile("b.zip", b"zip"), save=True)
        self.assertFalse(game.playable)


class AssetsRideTheStorageThatAlreadyExists(Base):
    def test_an_asset_lands_and_is_listed(self):
        pk = self.make().json()["id"]
        resp = self.client.post(f"{URL}{pk}/assets/",
                                {"file": asset(), "path": "sprites/hero.png"})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["assets"][0]["path"], "sprites/hero.png")

    def test_an_asset_counts_against_the_members_storage(self):
        # A parallel file table would mean game assets quietly didn't.
        pk = self.make().json()["id"]
        before = storage_used_bytes(self.user)
        self.client.post(f"{URL}{pk}/assets/", {"file": asset(size=5000), "path": "a.png"})
        self.assertEqual(storage_used_bytes(self.user), before + 5000)

    def test_a_traversal_in_an_asset_path_is_refused(self):
        # This becomes a real path inside the bundle at build time.
        pk = self.make().json()["id"]
        resp = self.client.post(f"{URL}{pk}/assets/",
                                {"file": asset(), "path": "../../etc/passwd"})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(GameAsset.objects.exists())

    def test_the_same_path_twice_replaces_rather_than_duplicates(self):
        pk = self.make().json()["id"]
        self.client.post(f"{URL}{pk}/assets/", {"file": asset(), "path": "a.png"})
        resp = self.client.post(f"{URL}{pk}/assets/", {"file": asset(size=99), "path": "a.png"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["assets"]), 1)

    def test_an_asset_can_be_removed(self):
        pk = self.make().json()["id"]
        self.client.post(f"{URL}{pk}/assets/", {"file": asset(), "path": "a.png"})
        resp = self.client.delete(f"{URL}{pk}/assets/?path=a.png")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["assets"], [])

    def test_a_missing_file_is_refused(self):
        pk = self.make().json()["id"]
        self.assertEqual(self.client.post(f"{URL}{pk}/assets/", {}).status_code, 400)


class FreeTierLimitsBite(Base):
    tier = TIER_FREE

    def test_an_upload_over_the_tier_cap_is_refused_with_the_number(self):
        pk = self.make().json()["id"]
        cap = limits_for(TIER_FREE)["upload_mb"]
        big = SimpleUploadedFile("big.bin", b"0" * int((cap * MB) + 1))
        resp = self.client.post(f"{URL}{pk}/assets/", {"file": big, "path": "big.bin"})
        self.assertEqual(resp.status_code, 413)
        self.assertIn(str(cap), resp.json()["detail"])
        self.assertFalse(GameAsset.objects.exists())

    def test_a_free_member_still_gets_a_working_tab(self):
        self.assertEqual(self.client.get(URL).status_code, 200)
        self.assertEqual(self.make().status_code, 201)
