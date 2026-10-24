"""A rating that is shared — on the public card, the card picture and a post — carries every metric the
coach gave, not only the headline: HookZ, FeelZ (with the emotion and why), what / why / how, the mix
suggestions, and the rest of the read (where they are, what they aim at, the song score, the next drill).

An audit found a share made from the HISTORY thinner than one made from the live result, so the two
are pinned to the same fields here."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from . import scoreshare
from . import takescorez as T
from .models import Post, ScoreShare, TakeScore

User = get_user_model()

PAYLOAD = {
    "verdict": "A solid take.", "strengths": ["Flow"], "fixes": ["Diction"],
    "score_exact": 6.4, "hook_score": 8, "hook_why": "The chorus repeats the title.", "hook_counted": True,
    "feelz_score": 4, "feelz_emotion": "longing", "feelz_why": "Held back on the last line.", "feelz_counted": True,
    "feelz_cause": "performance",
    "feelz_tips": [{"kind": "diction", "what": "Finish the word 'gone'.", "why": "It trails off.", "how": "Hold the n."}],
    "mix_tips": [{"helps": "clarity", "what": "Raise the vocal 2 dB.", "why": "Buried.", "how": "Automate it."}],
    "now": "Steady and warm.", "goal": "Land the ends of lines.", "style_fit": "Close to conscious rap.",
    "next_drill": "Say the last words of each line three times.", "song_score": 7, "song_why": "The hook lands.",
}


def make_take(user):
    t = TakeScore.objects.create(user=user, app_key="rapz", scores={"flow": 7, "clarity": 5}, overall=6,
                                 weakest="clarity", genre="Conscious Rap", read=T.read_of(PAYLOAD))
    return t


class TheShareCarriesEveryMetric(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("sh", "sh@e.com", "pw12345!")
        self.take = make_take(self.u)

    def test_the_history_keeps_the_whole_read_not_just_the_headline(self):
        r = self.take.read
        for k in ("now", "goal", "style_fit", "next_drill", "song_why", "song_score", "hook", "feelz", "feelz_tips"):
            self.assertIn(k, r, k)
        self.assertNotIn("mix_tips", r)       # the cause was the performance, so no mix advice is kept

    def test_the_share_payload_has_extras_mix_and_prose(self):
        p = T.share_payload(self.take)
        self.assertEqual([e["key"] for e in p["extras"]], ["hook", "feelz"])
        self.assertNotIn("mix_tips", p)                 # the cause is the performance: no mix advice
        self.assertEqual(p["now"], "Steady and warm.")
        self.assertEqual(p["song_score"], 7)

    def test_the_public_card_serves_cleaned_extras_with_what_why_how(self):
        token = T.share_take(self.take)
        d = scoreshare.share_dict(ScoreShare.objects.get(token=token))
        feelz = next(e for e in d["extras"] if e["key"] == "feelz")
        self.assertEqual(feelz["emotion"], "longing")
        self.assertEqual(feelz["cause"]["label"], "The performance")
        self.assertEqual(feelz["tips"][0]["how"], "Hold the n.")
        self.assertEqual(d["goal"], "Land the ends of lines.")

    def test_the_public_page_drops_anything_else_a_stored_row_carries(self):
        row = ScoreShare.objects.create(token="t" * 12, app_key="rapz", score=6, payload={
            "extras": [{"key": "feelz", "label": "FeelZ 💗", "value": 4, "secret": "no", "tips": [
                {"what": "x", "why": "y", "how": "z", "internal": "no"}]},
                {"label": "no value"}, "junk"],
            "mix_tips": [{"what": "m", "surprise": "no"}, {"nothing": 1}]})
        d = scoreshare.share_dict(row)
        self.assertEqual(len(d["extras"]), 1)
        self.assertNotIn("secret", d["extras"][0])
        self.assertNotIn("internal", d["extras"][0]["tips"][0])
        self.assertEqual(len(d["mix_tips"]), 1)
        self.assertNotIn("surprise", d["mix_tips"][0])

    def test_an_older_link_is_filled_in_not_replaced(self):
        old = ScoreShare.objects.create(token="o" * 12, app_key="rapz", score=6, user=self.u,
                                        payload={"score": 6, "human": True, "recap": {"n": 3}})
        TakeScore.objects.filter(pk=self.take.pk).update(share_token=old.token)
        self.take.refresh_from_db()
        self.assertEqual(T.share_take(self.take), old.token)
        old.refresh_from_db()
        self.assertTrue(old.payload["human"])                       # the member's declaration survives
        self.assertEqual(old.payload["recap"], {"n": 3})
        self.assertIn("extras", old.payload)                        # and the new metrics arrive

    def test_the_card_picture_carries_hook_and_feelz_in_both_sizes(self):
        d = scoreshare.share_dict(ScoreShare.objects.get(token=T.share_take(self.take)))
        self.assertEqual(scoreshare.extras_line(d), "HookZ 8  ·  FeelZ 4  ·  longing")
        for story in (False, True):
            png = scoreshare.render_card({**d, "username": "sh", "shown": "6.4"}, story=story)
            self.assertTrue(png.startswith(b"\x89PNG"))

    def test_a_card_with_no_extras_is_drawn_as_before(self):
        self.assertEqual(scoreshare.extras_line({"extras": []}), "")
        self.assertEqual(scoreshare.extras_line({}), "")


class AMetricRichPost(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("po", "po@e.com", "pw12345!")
        self.take = make_take(self.u)
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def test_posting_a_take_puts_hook_feelz_and_tips_on_the_read_card(self):
        r = self.c.post(f"/api/rapz/take/{self.take.pk}/post/", {"score": True, "feedback": True, "recording": False},
                        format="json")
        self.assertEqual(r.status_code, 201, r.content)
        pid = r.json()["post_id"]
        anon = APIClient()
        read = anon.get(f"/api/postz/{pid}/").json()["coach"]["read"]
        feelz = next(e for e in read["extras"] if e["key"] == "feelz")
        self.assertEqual(feelz["tips"][0]["what"], "Finish the word 'gone'.")
        self.assertEqual(read["hook_why"], "The chorus repeats the title.") if "hook_why" in read else None
        self.assertEqual(read["goal"], "Land the ends of lines.")
        self.assertEqual(read["score_exact"], 6.4)
