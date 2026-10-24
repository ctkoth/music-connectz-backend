from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import ItemRating, Post, ScoreShare
from apps.economy.scoreshare import share_dict
from apps.economy.vocalcoach import listener_reasons, listeners_for

User = get_user_model()


class ListenerReasonTests(TestCase):
    """A human reason beside the AI's — shown to the person it is about, and only them."""

    def setUp(self):
        self.author = User.objects.create_user("perf", "p@e.com", "pw-Long-enough-1")
        self.post = Post.objects.create(author=self.author, title="Song", kind="audio") \
            if "kind" in [f.name for f in Post._meta.fields] else Post.objects.create(author=self.author, title="Song")
        self.raters = [User.objects.create_user(f"lis{i}", f"l{i}@e.com", "pw-Long-enough-1") for i in range(4)]

    def test_a_rating_can_carry_a_one_line_reason_and_it_is_cleaned_and_capped(self):
        c = APIClient()
        c.force_authenticate(self.raters[0])
        r = c.post("/api/economy/social/rate/", {"item": "face:1", "action": "rate", "score": 9,
                                                  "reason": "  the   hook\nstuck " + "x" * 400}, format="json")
        self.assertEqual(r.status_code, 200)
        row = ItemRating.objects.get(user=self.raters[0])
        self.assertTrue(row.reason.startswith("the hook stuck"))
        self.assertLessEqual(len(row.reason), 200)
        self.assertNotIn("\n", row.reason)

    def test_the_author_reads_the_reasons_without_names_and_the_model_never_sees_them(self):
        for u, s, why in zip(self.raters, (9, 8, 3, 9), ("hook stuck", "tight flow", "", "")):
            ItemRating.objects.create(user=u, item_id=f"post:{self.post.id}", score=s, reason=why)
        ItemRating.objects.create(user=self.author, item_id=f"post:{self.post.id}", score=10, reason="mine")
        got = listener_reasons(self.post)
        self.assertEqual({r["text"] for r in got}, {"hook stuck", "tight flow"})   # no empties, not the author's own
        self.assertTrue(all(set(r) == {"score", "text"} for r in got))             # no usernames
        dumped = repr(listeners_for(self.post))
        self.assertNotIn("hook stuck", dumped)                                       # the prompt input stays numbers

    def test_a_public_card_gets_the_numbers_and_never_the_words(self):
        row = ScoreShare.objects.create(token="r" * 12, app_key="rapz", score=6, user=self.author,
                                        payload={"listeners": {"median": 9, "count": 4,
                                                               "reasons": [{"score": 9, "text": "rude words"}]}})
        d = share_dict(row)
        self.assertEqual(d["listeners"], {"median": 9, "count": 4})
        self.assertNotIn("rude words", repr(d))
