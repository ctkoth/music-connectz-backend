from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.economy.models import Post

from .models import CollabMember, CollabProject

User = get_user_model()


def member(name):
    return User.objects.create_user(username=name, password="collabz-pass-1")


class SkillsRequiredTests(TestCase):
    """A collab has to say what it needs. "Skill (optional)" made every post
    unmatchable — nobody can be paired with "help me make a song"."""

    def setUp(self):
        self.u = member("skill_owner")

    def test_no_skills_is_an_error(self):
        p = CollabProject(owner=self.u, title="Vague", kind="original")
        self.assertIn("at least one skill", p.skills_error())

    def test_one_skill_is_enough(self):
        p = CollabProject(owner=self.u, title="Clear", kind="original",
                          skills=["Mixing"])
        self.assertIsNone(p.skills_error())


class SourceRuleTests(TestCase):
    def setUp(self):
        self.u = member("owner")

    def test_a_cover_without_a_source_is_refused(self):
        p = CollabProject(owner=self.u, title="Cover", kind="cover")
        self.assertIn("needs a source", p.source_error())

    def test_a_remix_without_a_source_is_refused(self):
        p = CollabProject(owner=self.u, title="Remix", kind="remix")
        self.assertIsNotNone(p.source_error())

    def test_a_cover_of_something_off_platform_is_allowed_with_credit(self):
        p = CollabProject(owner=self.u, title="Cover", kind="cover",
                          source_credit="Originally by somebody else")
        self.assertIsNone(p.source_error())

    def test_an_original_needs_no_source(self):
        p = CollabProject(owner=self.u, title="New song", kind="original")
        self.assertIsNone(p.source_error())


class SplitTests(TestCase):
    def setUp(self):
        self.owner = member("split_owner")
        self.project = CollabProject.objects.create(owner=self.owner,
                                                    title="Split", kind="original")

    def add(self, name, percent):
        return CollabMember.objects.create(project=self.project,
                                           user=member(name),
                                           split_percent=percent)

    def test_zero_splits_are_fine_while_still_negotiating(self):
        self.add("a", 0)
        self.add("b", 0)
        self.assertIsNone(self.project.split_error())

    def test_splits_that_reach_one_hundred_are_fine(self):
        self.add("c", 60)
        self.add("d", 40)
        self.assertIsNone(self.project.split_error())

    def test_splits_that_look_decided_but_do_not_add_up_are_flagged(self):
        """The dangerous case: not obviously blank, and not correct."""
        self.add("e", 60)
        self.add("f", 30)
        self.assertIn("90%", self.project.split_error())

    def test_over_one_hundred_is_flagged_too(self):
        self.add("g", 70)
        self.add("h", 50)
        self.assertIn("120%", self.project.split_error())


class ApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = member("api_owner")
        self.client.force_authenticate(self.owner)

    def test_catalog_is_public_and_marks_which_kinds_need_a_source(self):
        r = APIClient().get(reverse("collabz-catalog"))
        self.assertEqual(r.status_code, 200)
        needs = {k["key"]: k["needs_source"] for k in r.json()["kinds"]}
        self.assertEqual(needs, {"original": False, "cover": True, "remix": True})

    def test_creating_a_project_makes_you_its_owner(self):
        r = self.client.post(reverse("collabz-projects"),
                             {"title": "Track one", "kind": "original", "skills": ["Mixing"]},
                             format="json")
        self.assertEqual(r.status_code, 201)
        members = r.json()["project"]["members"]
        self.assertEqual(members[0]["user"], "api_owner")
        self.assertEqual(members[0]["role"], "owner")

    def test_cover_without_source_is_rejected_by_the_api(self):
        r = self.client.post(reverse("collabz-projects"),
                             {"title": "Bad cover", "kind": "cover", "skills": ["Mixing"]},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("needs a source", r.json()["detail"])

    def test_cover_with_a_real_source_post_is_accepted(self):
        source = Post.objects.create(author=member("original_artist"),
                                     title="The original")
        r = self.client.post(reverse("collabz-projects"),
                             {"title": "Good cover", "kind": "cover",
                              "skills": ["Mixing"],
                              "source_post_id": source.id}, format="json")
        self.assertEqual(r.status_code, 201)

    def test_only_the_owner_invites_other_people(self):
        r = self.client.post(reverse("collabz-projects"), {"title": "Mine", "skills": ["Mixing"]},
                             format="json")
        pid = r.json()["project"]["id"]

        intruder = APIClient()
        intruder.force_authenticate(member("intruder"))
        r = intruder.post(reverse("collabz-members", args=[pid]),
                          {"username": "api_owner"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_anyone_can_add_themselves_and_the_split_warning_surfaces(self):
        r = self.client.post(reverse("collabz-projects"), {"title": "Open", "skills": ["Mixing"]},
                             format="json")
        pid = r.json()["project"]["id"]

        joiner = APIClient()
        joiner.force_authenticate(member("joiner"))
        r = joiner.post(reverse("collabz-members", args=[pid]),
                        {"persona": "producer", "split_percent": 30},
                        format="json")
        self.assertEqual(r.status_code, 201)
        # Reported, not enforced — 30% alone doesn't reach 100.
        self.assertIn("30%", r.json()["split_warning"])

    def test_the_owner_cannot_be_removed(self):
        r = self.client.post(reverse("collabz-projects"), {"title": "Locked", "skills": ["Mixing"]},
                             format="json")
        pid = r.json()["project"]["id"]
        r = self.client.delete(reverse("collabz-members", args=[pid]))
        self.assertEqual(r.status_code, 409)

    def test_you_cannot_claim_someone_elses_post_as_the_result(self):
        r = self.client.post(reverse("collabz-projects"), {"title": "Result", "skills": ["Mixing"]},
                             format="json")
        pid = r.json()["project"]["id"]
        theirs = Post.objects.create(author=member("stranger"), title="Not yours")
        r = self.client.patch(reverse("collabz-project", args=[pid]),
                              {"result_post_id": theirs.id}, format="json")
        self.assertEqual(r.status_code, 400)


class TabzRegistryTests(TestCase):
    def test_tab_urls_follow_the_minus_z_rule(self):
        from apps.tabz import registry

        self.assertEqual(registry.url_for("BattleZ"), "battle")
        self.assertEqual(registry.url_for("CollabZ"), "collab")
        self.assertEqual(registry.url_for("SingZ"), "sing")
        self.assertEqual(registry.url_for("GameZ"), "game")
        self.assertEqual(registry.url_for("SettingZ"), "setting")
        self.assertEqual(registry.url_for("Trump Toupee"), "trumptoupee")

    def test_no_two_tabs_share_a_url(self):
        from apps.tabz import registry
        self.assertEqual(registry.audit()["duplicate_urls"], [])

    def test_the_audit_finds_every_entry_with_no_icon(self):
        from apps.tabz import registry

        missing = {m["where"] for m in registry.audit()["missing_icons"]}
        self.assertIn("Home", missing)
        self.assertIn("MessageZ → Inbox", missing)
        self.assertIn("CollabZ → OriginalZ", missing)

    def test_battlez_carries_its_three_formats(self):
        from apps.tabz import registry

        battle = registry.find("battle")
        names = [m["name"] for m in battle["modals"]]
        self.assertEqual(names, ["Freestyle", "1v1", "Battle Cypher"])

    def test_tabz_endpoint_is_public(self):
        r = APIClient().get(reverse("tabz"))
        self.assertEqual(r.status_code, 200)
        self.assertGreater(len(r.json()["tabs"]), 30)
