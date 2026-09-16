"""Turning a private draft public — the control SoundCloud import promised
and never had.

`soundcloud_import.py` lands every track as `visibility="private"` and says,
in three places, that they stay that way "until you publish them" and that
"the normal cost of a post applies when they publish one." Nothing in
`_edit()` accepted a `visibility` change at all, so that promise had no
control behind it: a member's only real option was deleting a private draft
and recreating a public one from scratch.

`visibility` is a SETTING, exactly like `allow_in_playlists` right above it
in `_edit()` — held to no edit window, because a private import sitting for
two years must still be publishable, and a rewrite-after-people-rated-it
window makes no sense for a post nobody has been able to see yet.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import Post, profile_for, wallet_for

User = get_user_model()
PW = "hunter2hunter2"
EDIT_URL = "/api/economy/postz/"


class PublishingAPrivateDraftTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user("author", "a@e.com", PW)
        self.client = APIClient()
        self.client.force_authenticate(self.author)

    def make(self, **kw):
        kw.setdefault("visibility", "private")
        kw.setdefault("author", self.author)
        kw.setdefault("title", "Draft")
        return Post.objects.create(**kw)

    def test_publishing_a_private_post_makes_it_public(self):
        p = self.make()
        r = self.client.post(EDIT_URL, {"edit_id": p.pk, "visibility": "public"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        p.refresh_from_db()
        self.assertEqual(p.visibility, "public")

    def test_it_is_not_held_to_the_free_tier_edit_window(self):
        """The whole point: a private import sitting for months must still be
        publishable. A window built to stop rewriting a RATED post makes no
        sense for one nobody has ever been able to see."""
        from datetime import timedelta
        from django.utils import timezone
        p = self.make()
        Post.objects.filter(pk=p.pk).update(
            created_at=timezone.now() - timedelta(days=365))
        r = self.client.post(EDIT_URL, {"edit_id": p.pk, "visibility": "public"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_restricted_is_also_a_valid_destination(self):
        p = self.make()
        r = self.client.post(EDIT_URL, {"edit_id": p.pk, "visibility": "restricted"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        p.refresh_from_db()
        self.assertEqual(p.visibility, "restricted")

    def test_junk_is_ignored_never_defaults_to_public(self):
        """Creation defaults an unrecognised value to public; an EDIT must not
        — a typo here should never be the thing that publishes a draft."""
        p = self.make()
        r = self.client.post(EDIT_URL, {"edit_id": p.pk, "visibility": "loud"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        p.refresh_from_db()
        self.assertEqual(p.visibility, "private")

    def test_somebody_elses_private_post_cannot_be_published_by_a_stranger(self):
        stranger = User.objects.create_user("stranger", "s@e.com", PW)
        p = self.make()
        c = APIClient()
        c.force_authenticate(stranger)
        r = c.post(EDIT_URL, {"edit_id": p.pk, "visibility": "public"}, format="json")
        self.assertEqual(r.status_code, 404)
        p.refresh_from_db()
        self.assertEqual(p.visibility, "private")


class PublishingChargesTheShortfallTests(TestCase):
    """The docstring's own promise: "the normal cost of a post applies when
    they publish one" — but only the SHORTFALL, so a post already charged in
    full at creation is never charged twice for the same skills."""

    def setUp(self):
        self.author = User.objects.create_user("author", "a@e.com", PW)
        self.client = APIClient()
        self.client.force_authenticate(self.author)
        p = profile_for(self.author)
        p.personas = [{"key": "p", "name": "P",
                       "skills": [{"name": "Mixing", "rate_cents": 40}]}]
        p.save(update_fields=["personas"])
        w = wallet_for(self.author)
        w.energy = 1000
        w.save(update_fields=["energy", "updated_at"])

    def test_an_import_with_no_skills_publishes_free(self):
        # Every SoundCloud track lands with no skills_used — there is nothing
        # to price, so nothing is owed on publish, the same as import itself
        # being free.
        p = Post.objects.create(author=self.author, title="Track",
                                visibility="private", skill_cost_cents=0)
        w = wallet_for(self.author)
        before = w.energy
        self.client.post(EDIT_URL, {"edit_id": p.pk, "visibility": "public"}, format="json")
        w.refresh_from_db()
        self.assertEqual(w.energy, before)

    def test_a_never_charged_draft_is_charged_in_full_on_publish(self):
        """A member added a priced skill to an imported draft before
        publishing — the moment it can first reach anybody is the moment the
        normal cost applies, per soundcloud_import.py's own promise."""
        p = Post.objects.create(author=self.author, title="Track",
                                visibility="private", skill_cost_cents=0,
                                skills_used=["Mixing"])
        w = wallet_for(self.author)
        before = w.energy
        r = self.client.post(EDIT_URL, {"edit_id": p.pk, "visibility": "public"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        w.refresh_from_db()
        self.assertEqual(before - w.energy, 40)
        p.refresh_from_db()
        self.assertEqual(p.skill_cost_cents, 40)

    def test_a_post_already_charged_at_creation_is_never_charged_again(self):
        """A normal composer-made private post pays at creation regardless of
        visibility — publishing it later must not bill the same skills twice."""
        p = Post.objects.create(author=self.author, title="Track",
                                visibility="private", skill_cost_cents=40,
                                skills_used=["Mixing"])
        w = wallet_for(self.author)
        before = w.energy
        self.client.post(EDIT_URL, {"edit_id": p.pk, "visibility": "public"}, format="json")
        w.refresh_from_db()
        self.assertEqual(w.energy, before, "the same 40c must not be taken twice")

    def test_toggling_private_and_back_does_not_charge_a_second_time(self):
        p = Post.objects.create(author=self.author, title="Track",
                                visibility="private", skill_cost_cents=0,
                                skills_used=["Mixing"])
        self.client.post(EDIT_URL, {"edit_id": p.pk, "visibility": "public"}, format="json")
        w = wallet_for(self.author)
        after_first_publish = w.energy
        self.client.post(EDIT_URL, {"edit_id": p.pk, "visibility": "private"}, format="json")
        self.client.post(EDIT_URL, {"edit_id": p.pk, "visibility": "public"}, format="json")
        w.refresh_from_db()
        self.assertEqual(w.energy, after_first_publish)

    def test_a_free_member_short_on_energy_is_charged_only_what_they_have(self):
        # Same rule the normal creation path follows: charged = min(cost, balance).
        w = wallet_for(self.author)
        w.energy = 10
        w.save(update_fields=["energy", "updated_at"])
        p = Post.objects.create(author=self.author, title="Track",
                                visibility="private", skill_cost_cents=0,
                                skills_used=["Mixing"])
        self.client.post(EDIT_URL, {"edit_id": p.pk, "visibility": "public"}, format="json")
        w.refresh_from_db()
        self.assertEqual(w.energy, 0)
