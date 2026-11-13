"""A skill on somebody's work has to be one they have LEARNED, and the server says so.

The picker only offers a member's own profile skills, but a screen is not a rule: an older tab, a
script or a skill taken off the profile mid-compose all still reach the API. A skill rating lands on
whoever the post names, so a skill nobody declared would be a rating on a claim nobody made.

What is judged, and what deliberately is not:
  * a refusal is free and names the skills and the control that adds them;
  * an EDIT is judged only on what it adds, so nobody loses a skill off an old post when they take it
    off their profile;
  * a system-written tag (OCC's language) is not the member's claim, so it rides through a share;
  * a venue host's "what's on offer" is a list of what visitors should bring, not skills they hold.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy import postz
from apps.economy.models import (
    Battle, OccOutput, Post, VenueEvent, membership_for, profile_for, wallet_for,
)

User = get_user_model()
PW = "hunter2hunter2"
POSTZ = "/api/economy/postz/"


def learn(user, *names, rate=0):
    p = profile_for(user)
    p.personas = [{"key": "producer", "name": "Beat Producer",
                   "skills": [({"name": n, "rate_cents": rate} if rate else {"name": n}) for n in names]}]
    p.save()


class TheHelperTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("h", password=PW)
        learn(self.u, "mixing", "any_daw")

    def test_what_is_learned_is_the_profile(self):
        self.assertEqual(postz.declared_skill_names(self.u), {"mixing", "any_daw"})

    def test_undeclared_lists_only_the_missing_once_in_order(self):
        self.assertEqual(postz.undeclared_skills(self.u, ["flstudio", "mixing", "flstudio", "reaper"]),
                         ["flstudio", "reaper"])

    def test_what_the_thing_already_carries_may_stay(self):
        self.assertEqual(postz.undeclared_skills(self.u, ["flstudio", "reaper"], keep=["flstudio"]), ["reaper"])

    def test_a_refusal_names_the_skills_and_the_door(self):
        payload, code = postz.undeclared_refusal(self.u, ["flstudio"])
        self.assertEqual(code, 400)
        self.assertEqual(payload["undeclared_skills"], ["flstudio"])
        self.assertEqual(payload["open_in"]["tab"], "personaz")
        self.assertIn("Not on your profile: flstudio", payload["detail"])

    def test_nothing_undeclared_is_no_refusal(self):
        self.assertIsNone(postz.undeclared_refusal(self.u, ["mixing"]))
        self.assertIsNone(postz.undeclared_refusal(self.u, []))


class PostingTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("maker", password=PW)
        membership_for(self.u)
        learn(self.u, "mixing", rate=500)
        self.client = APIClient()
        self.client.force_authenticate(self.u)

    def post(self, **over):
        return self.client.post(POSTZ, {"title": "Track", **over}, format="json")

    def test_a_learned_skill_posts(self):
        r = self.post(skills_used=["mixing"])
        self.assertEqual(r.status_code, 201, r.content)

    def test_an_unlearned_skill_is_refused_and_nothing_is_made(self):
        r = self.post(skills_used=["mixing", "flstudio"])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["undeclared_skills"], ["flstudio"])
        self.assertFalse(Post.objects.exists())

    def test_a_refusal_charges_nothing(self):
        before = wallet_for(self.u).energy
        self.post(skills_used=["mixing", "flstudio"])
        self.assertEqual(wallet_for(self.u).energy, before)

    def test_no_skills_is_still_a_post(self):
        self.assertEqual(self.post().status_code, 201)

    def test_a_member_with_no_profile_skills_cannot_list_any(self):
        bare = User.objects.create_user("bare", password=PW)
        membership_for(bare)
        c = APIClient()
        c.force_authenticate(bare)
        self.assertEqual(c.post(POSTZ, {"title": "T", "skills_used": ["mixing"]}, format="json").status_code, 400)

    def test_the_journal_door_to_a_post_is_held_too(self):
        # create_post is the one creation path, so every caller that passes skills answers to it.
        post, _info, err = postz.create_post(self.u, {"title": "T", "skills_used": ["flstudio"]})
        self.assertIsNone(post)
        self.assertEqual(err[1], 400)


class EditingTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("maker", password=PW)
        membership_for(self.u)
        learn(self.u, "mixing", "mastering")
        self.client = APIClient()
        self.client.force_authenticate(self.u)
        self.post = Post.objects.create(author=self.u, title="Old", skills_used=["mixing", "gone_skill"],
                                        visibility="public")

    def edit(self, skills, client=None):
        return (client or self.client).post(POSTZ, {"edit_id": self.post.id, "skills_used": skills}, format="json")

    def test_adding_a_learned_skill_is_fine(self):
        self.assertEqual(self.edit(["mixing", "mastering"]).status_code, 200)

    def test_adding_an_unlearned_skill_is_refused(self):
        r = self.edit(["mixing", "flstudio"])
        self.assertEqual(r.status_code, 400)
        self.post.refresh_from_db()
        self.assertEqual(self.post.skills_used, ["mixing", "gone_skill"])

    def test_a_skill_taken_off_the_profile_stays_on_the_old_post(self):
        # "gone_skill" is no longer learned, but the post already carried it: keeping it is not an add.
        r = self.edit(["mixing", "gone_skill", "mastering"])
        self.assertEqual(r.status_code, 200, r.content)

    def test_the_platform_owner_editing_is_judged_against_the_authors_profile(self):
        owner = User.objects.create_user("boss", password=PW, is_staff=True, is_superuser=True)
        membership_for(owner)
        learn(owner, "flstudio")                       # the OWNER has it; the author does not
        c = APIClient()
        c.force_authenticate(owner)
        self.assertEqual(self.edit(["mixing", "flstudio"], client=c).status_code, 400)


class OtherSubmissionTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("entrant", password=PW)
        membership_for(self.u)
        learn(self.u, "mixing")
        self.client = APIClient()
        self.client.force_authenticate(self.u)

    def test_a_battle_entry_is_judged(self):
        host = User.objects.create_user("bhost", password=PW)
        b = Battle.objects.create(host=host, title="16 bars")
        url = f"/api/economy/battlez/{b.pk}/enter/"
        body = {"title": "t", "media_type": "audio", "media_url": "https://x.test/a.mp3"}
        r = self.client.post(url, {**body, "skills": ["flstudio"]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["undeclared_skills"], ["flstudio"])
        self.assertFalse(b.entries.exists())
        self.assertEqual(self.client.post(url, {**body, "skills": ["mixing"]}, format="json").status_code, 201)

    def test_starting_a_collab_is_judged(self):
        mate = User.objects.create_user("cmate", password=PW)
        body = {"title": "EP", "currency": "spinaz",
                "participants": [{"username": "entrant", "worth_cents": 1000},
                                 {"username": "cmate", "worth_cents": 0}]}
        r = self.client.post("/api/economy/collab/", {**body, "skills": ["flstudio"]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["undeclared_skills"], ["flstudio"])
        self.assertEqual(self.client.post("/api/economy/collab/", {**body, "skills": ["mixing"]},
                                          format="json").status_code, 201)

    def test_asking_for_a_venue_seat_is_judged_by_the_visitors_skills(self):
        host = User.objects.create_user("vhost", password=PW)
        ev = VenueEvent.objects.create(host=host, kind=VenueEvent.KIND_FREE, title="Room", area="Denver",
                                       starts_at=timezone.now() + timedelta(days=1),
                                       skills=["flstudio"], hours=2)
        url = f"/api/economy/venuez/{ev.id}/book/"
        r = self.client.post(url, {"skills": ["flstudio"]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["undeclared_skills"], ["flstudio"])
        # Naming nothing falls back to the room's own list: that is the host's line, not a claim.
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 201)


class OccTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("occer", password=PW)
        membership_for(self.u)
        learn(self.u, "mixing")
        self.client = APIClient()
        self.client.force_authenticate(self.u)

    def test_a_runs_language_tag_survives_a_share(self):
        # occ_run tags the output with its language; the member never chose it, so sharing it is not a claim.
        w = OccOutput.objects.create(user=self.u, title="Run", description="out", skills_used=["python"])
        r = self.client.post(f"/api/economy/occ/workz/{w.id}/share/", {}, format="json")
        self.assertNotEqual(r.status_code, 400, getattr(r, "data", None))
        self.assertTrue(Post.objects.filter(skills_used=["python"]).exists())

    def test_a_skill_the_member_adds_to_saved_work_is_judged(self):
        r = self.client.post("/api/economy/occ/workz/",
                             {"title": "Hook", "description": "x", "skills_used": ["flstudio"]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["undeclared_skills"], ["flstudio"])
        ok = self.client.post("/api/economy/occ/workz/",
                              {"title": "Hook", "description": "x", "skills_used": ["mixing"]}, format="json")
        self.assertEqual(ok.status_code, 201, ok.content)
