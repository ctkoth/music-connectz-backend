"""OCC — the registry, the tiers, TaskZ, and the two toggles.

The spec's own priority is «git integration synchronous with taskz because git
integration becomes a task», so a git action is a TaskZ row rather than a side
channel. And SuggestionZ must explain what, why and how — all three, or it
isn't a suggestion.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import (
    TIER_FREE,
    TIER_PREMIUM,
    TIER_STATZ,
    OccTask,
    membership_for,
    occ_settings_for,
    occ_undo_window,
)
from apps.economy.occ_spec import GAME_GENRES, GAME_SUBGENRES, genre_of, languages_for

User = get_user_model()
PW = "hunter2hunter2"


def as_tier(user, tier):
    m = membership_for(user)
    m.tier = tier
    m.save(update_fields=["tier", "updated_at"])
    return user


class TaxonomyTests(TestCase):
    """Unabridged means unabridged."""

    def test_every_genre_and_subgenre_from_the_spec_is_present(self):
        self.assertEqual(len(GAME_GENRES), 17)
        self.assertEqual(sum(len(subs) for *_, subs in GAME_GENRES), 99)

    def test_no_subgenre_is_listed_twice(self):
        flat = [s for *_, subs in GAME_GENRES for s in subs]
        self.assertEqual(len(flat), len(set(flat)))

    def test_the_two_unmarked_entries_are_filed_under_their_genre(self):
        # "Tactical RPG" and "Artillery" were written without a subgenre marker
        # in the source; both plainly belong to the genre above them.
        self.assertEqual(genre_of("Tactical RPG"), "rpg")
        self.assertEqual(genre_of("Artillery"), "strategy")

    def test_a_subgenre_knows_its_genre(self):
        self.assertEqual(genre_of("Soulslike"), "rpg")
        self.assertEqual(genre_of("Metroidvania"), "action_adventure")
        self.assertEqual(genre_of("nonsense"), "")

    def test_every_genre_carries_an_emoji(self):
        self.assertTrue(all(emoji for _, _, emoji, _ in GAME_GENRES))


class LanguageGateTests(TestCase):
    """Unreal is the StatZ reservation, which is what makes C++ the StatZ
    language."""

    def test_premium_gets_everything_but_cpp(self):
        allowed, locked = languages_for(TIER_PREMIUM)
        self.assertEqual({l["key"] for l in locked}, {"cpp", "c"})
        self.assertIn("csharp", {l["key"] for l in allowed})

    def test_statz_gets_cpp(self):
        allowed, locked = languages_for(TIER_STATZ)
        self.assertEqual(locked, [])
        self.assertIn("cpp", {l["key"] for l in allowed})

    def test_free_gets_none_of_them(self):
        allowed, _ = languages_for(TIER_FREE)
        self.assertEqual(allowed, [])


class SpecTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", PW)
        self.client.force_authenticate(self.user)

    def spec(self):
        resp = self.client.get("/api/economy/occ/spec/")
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.data

    def test_every_tab_carries_its_name_emoji_and_gate(self):
        for tab in self.spec()["tabs"]:
            self.assertTrue(tab["name"] and tab["emoji"] and tab["desc"], tab)
            self.assertIn("allowed", tab)

    def test_locked_tabs_are_returned_marked_not_hidden(self):
        # A menu that silently shrinks teaches a member nothing about the tier
        # above them.
        tabs = {t["key"]: t for t in self.spec()["tabs"]}
        self.assertFalse(tabs["gitz"]["allowed"])
        self.assertFalse(tabs["logz"]["allowed"])
        self.assertTrue(tabs["taskz"]["allowed"])
        # 21 from the spec + WorkZ, which the spec's own rule (nothing is a
        # dead end) demanded once OCC started producing things.
        self.assertEqual(len(tabs), 22)
        self.assertTrue(tabs["workz"]["allowed"])

    def test_every_tab_keeps_an_emoji_even_when_it_has_artwork(self):
        # The emoji is the fallback, so it is never optional. The frontend
        # deploys itself and the backend doesn't: a tab whose art hasn't
        # shipped yet must still render something that means the right thing.
        for tab in self.spec()["tabs"]:
            self.assertTrue(tab["emoji"], tab)
            if "icon" in tab:
                self.assertTrue(tab["icon"].endswith((".png", ".jpg", ".webp")), tab)

    def test_every_tab_names_its_own_artwork(self):
        tabs = {t["key"]: t for t in self.spec()["tabs"]}
        self.assertEqual(tabs["workz"]["icon"], "workz.png")
        self.assertEqual(tabs["gitz"]["icon"], "gitz.png")
        # Pick ConnectZ's art is filed under the shorter name it was drawn as.
        self.assertEqual(tabs["pickconnectz"]["icon"], "pickconz.png")
        # Reserved names — the art doesn't exist yet. Naming it anyway is what
        # makes dropping the file the entire job later.
        self.assertEqual(tabs["mistakez"]["icon"], "mistakez.png")
        self.assertEqual(tabs["characterz"]["icon"], "characterz.png")
        self.assertTrue(all("icon" in t for t in tabs.values()))

    def test_no_tab_borrows_another_tabs_artwork(self):
        # A picture of the wrong thing is worse than the emoji it replaced, so
        # two tabs sharing one icon has to be impossible rather than unlikely.
        icons = [t["icon"] for t in self.spec()["tabs"]]
        self.assertEqual(len(icons), len(set(icons)))

    def test_the_gates_move_with_the_tier(self):
        as_tier(self.user, TIER_STATZ)
        tabs = {t["key"]: t for t in self.spec()["tabs"]}
        self.assertTrue(tabs["gitz"]["allowed"])
        self.assertTrue(tabs["logz"]["allowed"])

    def test_it_says_plainly_that_it_cannot_run_code(self):
        # Better said once than discovered by pressing a button that does
        # nothing.
        spec = self.spec()
        self.assertFalse(spec["can_execute"])
        self.assertIn("sandbox", spec["execute_note"])

    def test_every_tab_that_opens_somewhere_names_the_control_it_opens_on(self):
        # `open_in` alone is a tab switch. The client used to build the second
        # half itself as `occ:<key>`, and no such anchor has ever existed in the
        # frontend, so every Open -> landed at the top of the destination app.
        # A tab that says where it opens has to say where in it.
        for tab in self.spec()["tabs"]:
            if tab.get("open_in"):
                self.assertTrue(tab.get("target"), tab)
                # The anchor is a data-tour="..." name, never an `app:control`
                # pair the client has to split — that split is what drifted.
                self.assertNotIn(":", tab["target"], tab)

    def test_a_tab_with_nothing_behind_it_yet_says_so_rather_than_opening_nowhere(self):
        # The other half of the same rule: no `open_in` means the client renders
        # "Not built yet", which is honest. What isn't honest is saying that
        # about something that ships — Pick ConnectZ is the dock at the foot of
        # every screen, so it opens like anything else that exists.
        tabs = {t["key"]: t for t in self.spec()["tabs"]}
        self.assertEqual(tabs["pickconnectz"]["open_in"], "occ")
        self.assertTrue(tabs["pickconnectz"]["target"])
        self.assertNotIn("open_in", tabs["gitz"])

    def test_ico_is_among_the_image_exports(self):
        self.assertIn("ico", self.spec()["image_exports"])

    def test_exports_route_to_an_intelligence_app_by_media_type(self):
        routes = self.spec()["export_routes"]
        self.assertEqual(routes["image"]["app"], "imagez")
        self.assertEqual(routes["video"]["app"], "directz")
        self.assertTrue(all(r.get("target") for r in routes.values()))

    def test_the_taxonomy_is_served_whole(self):
        genres = self.spec()["game_genres"]
        self.assertEqual(len(genres), 17)
        self.assertEqual(sum(len(g["subgenres"]) for g in genres), 99)


class SettingsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", PW)
        self.client.force_authenticate(self.user)

    def patch(self, **body):
        return self.client.patch("/api/economy/occ/settings/", body, format="json")

    def test_automation_is_off_by_default(self):
        # A setting that acts on your code unasked is not one to inherit.
        self.assertFalse(self.client.get("/api/economy/occ/settings/").data["automation"])

    def test_free_cannot_switch_automation_on(self):
        resp = self.patch(automation=True)
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.data["required_tier"], "statz")
        self.assertFalse(occ_settings_for(self.user).automation)

    def test_statz_can(self):
        as_tier(self.user, TIER_STATZ)
        self.assertTrue(self.patch(automation=True).data["automation"])

    def test_suggestionz_is_premium(self):
        self.assertEqual(self.patch(suggestionz=True).status_code, 403)
        as_tier(self.user, TIER_PREMIUM)
        self.assertTrue(self.patch(suggestionz=True).data["suggestionz"])

    def test_switching_something_off_is_never_gated(self):
        # Being unable to turn a thing OFF because of your tier would be absurd.
        self.assertEqual(self.patch(automation=False).status_code, 200)

    def test_free_pins_two_and_is_told_so(self):
        resp = self.patch(pinned_tabs=["taskz", "filez", "search"])
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.data["pin_limit"], 2)
        self.assertEqual(self.patch(pinned_tabs=["taskz", "filez"]).status_code, 200)

    def test_premium_pins_as_many_as_it_likes(self):
        as_tier(self.user, TIER_PREMIUM)
        resp = self.patch(pinned_tabs=["taskz", "filez", "search", "logz", "gitz"])
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIsNone(resp.data["pin_limit"])


class TaskZTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", PW)
        self.client.force_authenticate(self.user)

    def add(self, **over):
        return self.client.post("/api/economy/occ/taskz/",
                                {"title": "Rename the module", **over}, format="json")

    def test_a_task_needs_a_title(self):
        self.assertEqual(self.add(title="  ").status_code, 400)

    def test_a_plain_task_starts_queued(self):
        resp = self.add()
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["status"], "queued")
        self.assertFalse(resp.data["automated"])

    def test_a_suggestion_must_say_what_why_and_how(self):
        # All three or it isn't a suggestion, it's an assertion.
        resp = self.add(suggested=True, what="Rename it", why="")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("why", resp.data["missing"])
        self.assertIn("how", resp.data["missing"])

    def test_a_complete_suggestion_waits_rather_than_running(self):
        resp = self.add(suggested=True, what="Rename it", why="It shadows a builtin",
                        how="git mv, then update the imports")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["status"], "suggested")
        self.assertEqual(resp.data["why"], "It shadows a builtin")

    def test_git_is_a_task_not_a_side_channel(self):
        as_tier(self.user, TIER_STATZ)
        resp = self.add(kind="git", git_repo="ctkoth/x", git_branch="main")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["kind"], "git")
        self.assertEqual(resp.data["git"]["repo"], "ctkoth/x")
        # It appears in the same list as everything else.
        self.assertEqual(len(self.client.get("/api/economy/occ/taskz/").data["tasks"]), 1)

    def test_gitz_is_statz_gated(self):
        resp = self.add(kind="git")
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.data["required_tier"], "statz")

    def test_automation_marks_a_task_as_run_without_asking(self):
        as_tier(self.user, TIER_STATZ)
        s = occ_settings_for(self.user)
        s.automation = True
        s.save(update_fields=["automation"])
        self.assertTrue(self.add().data["automated"])

    def test_a_suggestion_is_never_automated_even_with_automation_on(self):
        # The whole point of a suggestion is that it waits to be read.
        as_tier(self.user, TIER_STATZ)
        s = occ_settings_for(self.user)
        s.automation = True
        s.save(update_fields=["automation"])
        resp = self.add(suggested=True, what="a", why="b", how="c")
        self.assertFalse(resp.data["automated"])
        self.assertEqual(resp.data["status"], "suggested")

    def test_progress_and_status_advance(self):
        pk = self.add().data["id"]
        resp = self.client.patch(f"/api/economy/occ/taskz/{pk}/",
                                 {"status": "running", "progress": 40, "eta_seconds": 90},
                                 format="json")
        self.assertEqual(resp.data["status"], "running")
        self.assertEqual(resp.data["progress"], 40)
        self.assertEqual(resp.data["eta_seconds"], 90)
        self.assertIsNotNone(resp.data["started_at"])

    def test_progress_is_clamped(self):
        pk = self.add().data["id"]
        self.assertEqual(self.client.patch(f"/api/economy/occ/taskz/{pk}/",
                                           {"progress": 900}, format="json").data["progress"], 100)

    def test_only_my_tasks(self):
        pk = self.add().data["id"]
        self.client.force_authenticate(User.objects.create_user("x", "x@e.com", PW))
        self.assertEqual(self.client.patch(f"/api/economy/occ/taskz/{pk}/",
                                           {"progress": 10}, format="json").status_code, 404)


class UndoTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", PW)
        self.client.force_authenticate(self.user)

    def done(self, undo=True):
        t = OccTask.objects.create(
            user=self.user, title="Rename", status=OccTask.STATUS_DONE,
            finished_at=timezone.now(),
            undo_payload={"restore": "old.py"} if undo else {})
        return t

    def undo(self, t):
        return self.client.post(f"/api/economy/occ/taskz/{t.pk}/undo/", {}, format="json")

    def test_a_finished_task_can_be_taken_back(self):
        t = self.done()
        resp = self.undo(t)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["status"], "undone")

    def test_a_task_that_cannot_describe_its_reversal_says_so(self):
        # Better to refuse than to offer a button that can't put anything back.
        resp = self.undo(self.done(undo=False))
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertIn("can't be undone", resp.data["detail"])

    def test_the_window_is_the_tier_ladder(self):
        as_tier(self.user, TIER_FREE)
        self.assertEqual(occ_undo_window(TIER_FREE), 4 * 60)
        self.assertEqual(occ_undo_window(TIER_STATZ), 4 * 3600)

    def test_past_the_window_it_is_refused_with_the_number(self):
        t = self.done()
        OccTask.objects.filter(pk=t.pk).update(
            finished_at=timezone.now() - timedelta(hours=5))
        resp = self.undo(t)
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.data["undo_window_seconds"], 4 * 60)

    def test_statz_still_has_time_where_free_does_not(self):
        as_tier(self.user, TIER_STATZ)
        t = self.done()
        OccTask.objects.filter(pk=t.pk).update(
            finished_at=timezone.now() - timedelta(minutes=30))
        self.assertEqual(self.undo(t).status_code, 200)

    def test_the_list_says_whether_each_one_is_undoable(self):
        self.done()
        self.done(undo=False)
        rows = self.client.get("/api/economy/occ/taskz/").data["tasks"]
        self.assertEqual({r["undoable"] for r in rows}, {True, False})

    def test_a_queued_task_is_cancelled_not_undone(self):
        t = OccTask.objects.create(user=self.user, title="x", status=OccTask.STATUS_QUEUED)
        self.assertEqual(self.undo(t).status_code, 409)
        resp = self.client.delete(f"/api/economy/occ/taskz/{t.pk}/")
        self.assertEqual(resp.data["status"], "cancelled")
