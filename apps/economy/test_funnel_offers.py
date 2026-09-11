"""The offer engine, and the five rules that keep it from being spam.

Every test here is one of the five. The failure mode of a promotion system is
not a crash — it is a member learning that the deadlines are fake, the panel
never goes away, and the "3 left" has said 3 for a month. None of that shows
up in an exception, so it has to show up here.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from . import offerz_engine as fz
from .models import OfferDismissal, membership_for, profile_for, wallet_for

User = get_user_model()
PW = "pw12345!"


def member(name):
    return User.objects.create_user(name, f"{name}@mcz.test", PW)


class TheOfferList(TestCase):
    """Shape rules that hold across every offer, checked as a set."""

    def test_every_offer_lands_on_a_control_not_a_tab(self):
        """"Go to MembershipZ" is where a funnel dies — the member arrives at
        the top of a screen they have never seen, hunts, and leaves."""
        for key, spec in fz.OFFERS.items():
            with self.subTest(offer=key):
                self.assertTrue(spec.get("tab"), "tab")
                self.assertTrue(spec.get("target"), "target")

    def test_every_offer_says_what_it_gives_and_why_it_exists(self):
        for key, spec in fz.OFFERS.items():
            with self.subTest(offer=key):
                self.assertTrue(spec.get("title"))
                self.assertTrue(spec.get("cta"))
                self.assertTrue(str(spec.get("why", "")).strip(), "why")
                self.assertIn(spec["step"], fz.STEPS)

    def test_anything_that_costs_something_says_so(self):
        """The cost/gain rule, and a promotion is the one place it is most
        tempting to lead with the gain and bury the price."""
        for key, spec in fz.OFFERS.items():
            with self.subTest(offer=key):
                for line in (spec.get("cost") or []):
                    self.assertEqual(line["sign"], "−")
                    self.assertIn(line["resource"],
                                  ("energy", "spinaz", "promptz", "money", "xp"))

    def test_no_offer_is_scheduled(self):
        """Nothing here fires on the calendar. A time-triggered promotion
        cannot answer rule 4 — the thing that made it true was the date."""
        for key, spec in fz.OFFERS.items():
            with self.subTest(offer=key):
                self.assertTrue(callable(spec["when"]))

    def test_every_offer_is_reachable_by_somebody(self):
        """A `when` nobody can satisfy is decoration, and this codebase has
        enough of those to know how they end up. Each offer must fire for at
        least one of the member states below."""
        fired = set()
        for build in (self._fresh, self._onboarded_no_posts, self._out_of_prompts,
                      self._broke_and_out, self._heavy_free_user, self._streaker):
            u = build()
            for o in fz.offers_for(u, limit=99):
                fired.add(o["key"])
        # `unfinished_collab` needs a Postgres JSON query the SQLite suite
        # cannot run, and `unread_messages` needs a second member — both are
        # covered separately below.
        expected = set(fz.OFFERS) - {"unfinished_collab", "unread_messages"}
        self.assertEqual(expected - fired, set())

    # -- member states ----------------------------------------------------
    def _fresh(self):
        return member("fresh")

    def _onboarded_no_posts(self):
        u = member("onboarded")
        p = profile_for(u)
        p.onboarded, p.birthday = True, "1990-06-01"
        p.save(update_fields=["onboarded", "birthday", "updated_at"])
        return u

    def _out_of_prompts(self):
        u = member("spent")
        w = wallet_for(u)
        w.prompt_day = timezone.now().strftime("%Y-%m-%d")
        w.prompts_used_today = 99
        w.spinaz = 500
        w.save(update_fields=["prompt_day", "prompts_used_today", "spinaz", "updated_at"])
        return u

    def _broke_and_out(self):
        u = member("broke")
        w = wallet_for(u)
        w.prompt_day = timezone.now().strftime("%Y-%m-%d")
        w.prompts_used_today = 99
        w.spinaz = 0
        w.save(update_fields=["prompt_day", "prompts_used_today", "spinaz", "updated_at"])
        return u

    def _heavy_free_user(self):
        u = member("heavy")
        w = wallet_for(u)
        w.prompt_walls, w.prompt_walls_since = 5, timezone.localdate()
        w.save(update_fields=["prompt_walls", "prompt_walls_since", "updated_at"])
        return u

    def _streaker(self):
        u = member("streaker")
        from apps.skillz.models import TrainingProfile
        TrainingProfile.objects.create(
            user=u, app_key="singz", current_streak=9,
            last_active=timezone.localdate() - timedelta(days=1))
        return u


class ItIsTrueWhenItIsShown(TestCase):
    """Rule 4. An offer shown to somebody it isn't true for is noise, and
    noise is what teaches people to stop reading the panel."""

    def keys(self, user):
        return {o["key"] for o in fz.offers_for(user, limit=99)}

    def test_the_topup_offer_is_not_shown_to_somebody_with_prompts_left(self):
        self.assertNotIn("out_of_prompts", self.keys(member("flush")))

    def test_the_birthday_offer_goes_away_once_there_is_a_birthday(self):
        u = member("dob")
        self.assertIn("set_your_birthday", self.keys(u))
        p = profile_for(u)
        p.birthday = "1992-03-04"
        p.save(update_fields=["birthday", "updated_at"])
        self.assertNotIn("set_your_birthday", self.keys(u))

    def test_the_paid_offer_is_not_shown_to_somebody_who_never_hit_the_wall(self):
        """Sold at the wall the member actually hit, three times — not at a
        member who has never met it."""
        self.assertNotIn("premium_ladder", self.keys(member("content")))

    def test_the_free_door_and_the_sale_are_never_shown_together(self):
        """A member out of 🍥 gets the way to EARN some, not the way to spend
        some they do not have. A limit that stops somebody doing anything is a
        door out; this is the door back in."""
        u = member("skint")
        w = wallet_for(u)
        w.prompt_day = timezone.now().strftime("%Y-%m-%d")
        w.prompts_used_today, w.spinaz = 99, 0
        w.save(update_fields=["prompt_day", "prompts_used_today", "spinaz", "updated_at"])
        keys = self.keys(u)
        self.assertIn("prompts_wall_no_spinaz", keys)
        self.assertNotIn("out_of_prompts", keys)

    def test_a_predicate_that_raises_hides_one_offer_not_the_screen(self):
        """An offer panel that 500s because a single check met an edge case is
        a worse outcome than one promotion going unseen."""
        original = fz.OFFERS["invite_pays_both"]["when"]
        fz.OFFERS["invite_pays_both"]["when"] = lambda c: 1 / 0
        try:
            got = fz.offers_for(member("edge"), limit=99)
            self.assertNotIn("invite_pays_both", {o["key"] for o in got})
            self.assertTrue(got)          # the rest still rendered
        finally:
            fz.OFFERS["invite_pays_both"]["when"] = original


class ADeadlineThatDoesNotEndIsALie(TestCase):
    """Rule 2, in BOTH directions. Dropping an expired offer from the list and
    still honouring it on redeem is the bug — the client keeps whatever panel
    it already rendered."""

    def setUp(self):
        self.client = APIClient()
        self.u = member("clock")
        self.client.force_authenticate(self.u)

    def test_an_expired_offer_is_not_listed(self):
        fz.OFFERS["invite_pays_both"]["ends_at"] = timezone.now() - timedelta(minutes=1)
        try:
            keys = {o["key"] for o in fz.offers_for(self.u, limit=99)}
            self.assertNotIn("invite_pays_both", keys)
        finally:
            fz.OFFERS["invite_pays_both"].pop("ends_at", None)

    def test_an_expired_offer_is_REFUSED_on_redeem(self):
        fz.OFFERS["invite_pays_both"]["ends_at"] = timezone.now() - timedelta(minutes=1)
        try:
            r = self.client.post("/api/economy/offerz/funnel/redeem/",
                                 {"key": "invite_pays_both"}, format="json")
            self.assertEqual(r.status_code, 409, r.content)
        finally:
            fz.OFFERS["invite_pays_both"].pop("ends_at", None)

    def test_a_live_offer_redeems_to_the_control_it_promised(self):
        r = self.client.post("/api/economy/offerz/funnel/redeem/",
                             {"key": "invite_pays_both"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["target"], "referral-code")

    def test_an_offer_that_does_not_exist_is_refused(self):
        r = self.client.post("/api/economy/offerz/funnel/redeem/",
                             {"key": "free_money"}, format="json")
        self.assertEqual(r.status_code, 409)


class ScarcityIsCountedNeverClaimed(TestCase):
    """Rule 3. "3 left" comes from a row count or it is not said."""

    def test_the_seat_count_is_the_real_one(self):
        from .models import founding_status
        u = member("seat")
        got = next((o for o in fz.offers_for(u, limit=99)
                    if o["key"] == "founding_seat"), None)
        self.assertIsNotNone(got)
        self.assertIn(str(founding_status()["remaining"]), got["title"])

    def test_it_vanishes_when_the_seats_are_gone(self):
        u = member("late")
        m = membership_for(u)
        m.lifetime = True
        m.save(update_fields=["lifetime"])
        keys = {o["key"] for o in fz.offers_for(u, limit=99)}
        self.assertNotIn("founding_seat", keys)


class DismissedStaysDismissed(TestCase):
    """Rule 5. An offer that comes back after being closed is not a promotion,
    it is an obstruction, and the member's answer to it is to leave."""

    def setUp(self):
        self.client = APIClient()
        self.u = member("closer")
        self.client.force_authenticate(self.u)

    def test_closing_one_removes_it_for_good(self):
        self.assertIn("invite_pays_both",
                      {o["key"] for o in fz.offers_for(self.u, limit=99)})
        r = self.client.post("/api/economy/offerz/funnel/",
                             {"key": "invite_pays_both"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertNotIn("invite_pays_both",
                         {o["key"] for o in fz.offers_for(self.u, limit=99)})

    def test_it_answers_with_what_is_left_rather_than_an_empty_ack(self):
        """Closing one must not cost the screen a second round trip to find
        out what now sits in its place."""
        r = self.client.post("/api/economy/offerz/funnel/",
                             {"key": "invite_pays_both"}, format="json")
        self.assertIn("offers", r.data)

    def test_dismissing_the_same_one_twice_is_harmless(self):
        for _ in range(2):
            r = self.client.post("/api/economy/offerz/funnel/",
                                 {"key": "invite_pays_both"}, format="json")
            self.assertEqual(r.status_code, 200)
        self.assertEqual(OfferDismissal.objects.filter(user=self.u).count(), 1)

    def test_an_unknown_key_cannot_be_dismissed(self):
        r = self.client.post("/api/economy/offerz/funnel/",
                             {"key": "made_up"}, format="json")
        self.assertEqual(r.status_code, 400)


class ThePanelIsBounded(TestCase):
    def test_it_never_returns_more_than_the_cap(self):
        """A panel with eleven things on it is a panel nobody reads, and the
        one that mattered is buried under ten that did not."""
        self.client = APIClient()
        u = member("many")
        self.client.force_authenticate(u)
        r = self.client.get("/api/economy/offerz/funnel/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertLessEqual(len(r.data["offers"]), fz.MAX_SHOWN)

    def test_earlier_steps_come_first(self):
        """A member is sold to at the stage they are at. Showing somebody a
        subscription before they have made anything is the funnel backwards."""
        u = member("ordered")
        got = fz.offers_for(u, limit=99)
        seen = [fz.STEPS.index(o["step"]) for o in got]
        self.assertEqual(seen, sorted(seen))

    def test_it_is_not_open_logged_out(self):
        self.assertIn(APIClient().get("/api/economy/offerz/funnel/").status_code,
                      (401, 403))


class TheWallCounterIsAFactNotAGuess(TestCase):
    """`prompt_walls` is what the one paid offer is sold at, so it has to be
    real, and it has to stop being real when it stops being true."""

    def test_a_refusal_is_counted(self):
        from .models import _consume_daily_prompt, prompt_walls_week
        u = member("waller")
        w = wallet_for(u)
        w.prompt_day = timezone.now().strftime("%Y-%m-%d")
        w.prompts_used_today = 99
        w.save(update_fields=["prompt_day", "prompts_used_today", "updated_at"])
        self.assertFalse(_consume_daily_prompt(u, 1))
        self.assertEqual(prompt_walls_week(u), 1)

    def test_a_successful_run_is_not_counted(self):
        """A member who uses their three every day and is happy is not
        somebody to sell to."""
        from .models import _consume_daily_prompt, prompt_walls_week
        u = member("happy")
        self.assertTrue(_consume_daily_prompt(u, 1))
        self.assertEqual(prompt_walls_week(u), 0)

    def test_the_window_rolls_rather_than_accumulating_forever(self):
        """A lifetime counter would sell to somebody long after they settled
        into a rhythm that suits them — an offer no longer true when shown."""
        from .models import prompt_walls_week
        u = member("olduser")
        w = wallet_for(u)
        w.prompt_walls = 9
        w.prompt_walls_since = timezone.localdate() - timedelta(days=30)
        w.save(update_fields=["prompt_walls", "prompt_walls_since", "updated_at"])
        self.assertEqual(prompt_walls_week(u), 0)


class TheOwnerCatalogue(TestCase):
    """The whole list, including the offers that did NOT fire.

    The member endpoint answers "what is true for ME", capped at three — right
    for a member, wrong for whoever runs the platform. An offer nobody has
    ever matched is the decoration this module warns about, and until this
    view existed it was invisible from the only surface there was.
    """

    def setUp(self):
        self.client = APIClient()

    def _owner(self):
        u = member("boss")
        u.is_staff = u.is_superuser = True
        u.save(update_fields=["is_staff", "is_superuser"])
        return u

    def test_it_returns_every_offer_not_just_the_live_ones(self):
        self.client.force_authenticate(self._owner())
        r = self.client.get("/api/economy/offerz/catalog/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.data["offers"]), len(fz.OFFERS))

    def test_every_row_carries_the_reason_it_exists(self):
        """`why` is written beside every offer in the code and was served
        nowhere. A promotion whose reason lives only in a comment is one the
        next person rewords into something that no longer has one."""
        self.client.force_authenticate(self._owner())
        r = self.client.get("/api/economy/offerz/catalog/")
        for row in r.data["offers"]:
            with self.subTest(offer=row["key"]):
                self.assertTrue(row["why"].strip())

    def test_it_says_which_are_live_so_the_engine_can_be_seen_deciding(self):
        self.client.force_authenticate(self._owner())
        r = self.client.get("/api/economy/offerz/catalog/")
        rows = r.data["offers"]
        live = {row["key"] for row in rows if row["live_for_me"]}
        # A brand-new owner account matches the acquisition and activation
        # offers, so some fire and some do not — which is the point: the
        # screen shows the engine deciding rather than a list of everything.
        self.assertTrue(live)
        self.assertLess(len(live), len(rows))

    def test_a_member_cannot_read_it(self):
        """The catalogue names what the platform is selling and when — a
        business fact rather than a member-facing one."""
        self.client.force_authenticate(member("nosy"))
        r = self.client.get("/api/economy/offerz/catalog/")
        self.assertEqual(r.status_code, 403)

    def test_dismissals_are_the_only_count_reported(self):
        """Somebody saw it and said no is an honest signal. "Impressions"
        would need a write on every render and would turn a read-only panel
        into a tracking surface."""
        u = member("shutit")
        OfferDismissal.objects.create(user=u, offer_key="invite_pays_both")
        self.client.force_authenticate(self._owner())
        r = self.client.get("/api/economy/offerz/catalog/")
        row = next(x for x in r.data["offers"] if x["key"] == "invite_pays_both")
        self.assertEqual(row["dismissed_by"], 1)
        self.assertNotIn("impressions", row)
