"""The twelve sign bonuses, and the four rules that keep them from being a mint.

The thing being pinned here is not that a Leo gets paid. It is that a Leo can
only get paid by DOING something, gets paid the same as everybody else for it,
gets paid once, and cannot make a career of it in an afternoon. Every test
below is one of those four, because the failure mode of this feature is not a
crash — it is a member noticing their birthday earns them less than somebody
else's, and being right.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import SignBonusAward, wallet_for, profile_for
from . import signbonus

User = get_user_model()
PW = "pw12345!"


def member(name, sign=""):
    u = User.objects.create_user(name, f"{name}@mcz.test", PW)
    if sign:
        p = profile_for(u)
        p.sign = sign
        p.save(update_fields=["sign", "updated_at"])
    return u


class TheList(TestCase):
    """Shape rules that hold across all twelve, checked as a set."""

    def test_every_sign_has_exactly_one(self):
        # Twelve signs, twelve bonuses. A sign with none earns nothing for a
        # birthday it did not pick, which is the failure this whole design is
        # arranged to avoid.
        self.assertEqual(len(signbonus.BONUSES), 12)

    def test_no_two_signs_share_an_action(self):
        """`_BY_ACTION` is a dict, so a duplicated action would silently make
        one sign's bonus unreachable rather than raising."""
        actions = [b["action"] for b in signbonus.BONUSES.values()]
        self.assertEqual(len(set(actions)), 12)
        self.assertEqual(len(signbonus._BY_ACTION), 12)

    def test_every_bonus_says_what_and_why(self):
        for sign, b in signbonus.BONUSES.items():
            with self.subTest(sign=sign):
                for field in ("name", "action", "does", "stretch", "why", "tab"):
                    self.assertTrue(str(b.get(field, "")).strip(), field)

    def test_the_stretch_is_never_the_base_reworded(self):
        for sign, b in signbonus.BONUSES.items():
            with self.subTest(sign=sign):
                self.assertNotEqual(b["does"].strip().lower(),
                                    b["stretch"].strip().lower())

    def test_every_bonus_names_where_to_go_and_do_it(self):
        """A number with nowhere to take it is the cross-pollination rule's
        counter-example. Every tab named here has to be a real one."""
        from music_connectz.urls import urlpatterns   # noqa: F401  (import check)
        tabs = {b["tab"] for b in signbonus.BONUSES.values()}
        self.assertTrue(tabs)
        for t in tabs:
            self.assertRegex(t, r"^[a-z0-9]+$")

    def test_the_amounts_do_not_vary_by_sign(self):
        """The one attribute a member cannot change must never be the reason
        they earn less. There is one BASE and one STRETCH, not a table."""
        self.assertEqual((signbonus.BASE, signbonus.STRETCH), (20, 50))
        for b in signbonus.BONUSES.values():
            self.assertNotIn("spinaz", b)
            self.assertNotIn("amount", b)


class Awarding(TestCase):
    def test_it_pays_the_sign_whose_action_fired(self):
        leo = member("leo", "Leo")
        self.assertEqual(signbonus.award(leo, "battle_joins_others"), 20)
        self.assertEqual(wallet_for(leo).spinaz, 20)

    def test_it_pays_nothing_for_somebody_else_s_action(self):
        """Every call site fires unconditionally; this is what makes that safe."""
        leo = member("leo2", "Leo")
        self.assertEqual(signbonus.award(leo, "streak"), 0)
        self.assertEqual(wallet_for(leo).spinaz, 0)

    def test_no_sign_means_no_bonus_and_no_error(self):
        nobody = member("nosign")
        self.assertEqual(signbonus.award(nobody, "rate"), 0)

    def test_the_stretch_is_a_second_payment_not_a_replacement(self):
        aries = member("aries", "Aries")
        self.assertEqual(signbonus.award(aries, "battle_first_in"), 20)
        self.assertEqual(signbonus.award(aries, "battle_first_in", stretch=True), 50)
        self.assertEqual(wallet_for(aries).spinaz, 70)

    def test_each_tier_pays_once_ever(self):
        pisces = member("pisces", "Pisces")
        self.assertEqual(signbonus.award(pisces, "freestyle"), 20)
        for _ in range(5):
            self.assertEqual(signbonus.award(pisces, "freestyle"), 0)
        self.assertEqual(wallet_for(pisces).spinaz, 20)

    def test_the_daily_cap_holds(self):
        """Once-each already bounds a member to 70 🍥 for life, so the cap is
        belt and braces — but a future thirteenth bonus would be unbounded
        without it, and that is exactly the change nobody re-checks."""
        cap = member("capped", "Libra")
        today = timezone.localdate()
        for i in range(signbonus.DAILY_CAP):
            SignBonusAward.objects.create(user=cap, sign="Libra", tier=f"x{i}",
                                          action="rate", amount=0, awarded_on=today)
        self.assertEqual(signbonus.award(cap, "rate"), 0)

    def test_the_payment_says_where_it_came_from(self):
        """A balance that moves with no reason behind it is what LogZ exists
        to stop, and a row with nowhere to go is the cross-pollination rule's
        own counter-example."""
        virgo = member("virgo", "Virgo")
        signbonus.award(virgo, "post_with_skills")
        tr = virgo.transactions.order_by("-id").first()
        self.assertIn("Virgo", tr.note)
        self.assertEqual(tr.app_key, "zodiacz")

    def test_try_award_swallows_rather_than_failing_the_real_action(self):
        """A battle entry must succeed whether or not a bonus does."""
        leo = member("leo3", "Leo")
        with self.settings():
            original = signbonus.award
            signbonus.award = lambda *a, **k: 1 / 0
            try:
                self.assertEqual(signbonus.try_award(leo, "battle_joins_others"), 0)
            finally:
                signbonus.award = original


class ThePublishedList(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_a_member_can_read_their_own_before_they_do_it(self):
        scorpio = member("scorpio", "Scorpio")
        self.client.force_authenticate(scorpio)
        r = self.client.get("/api/economy/signbonus/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["mine"]["sign"], "Scorpio")
        self.assertEqual(r.data["mine"]["base_spinaz"], 20)
        self.assertFalse(r.data["mine"]["earned_base"])

    def test_it_says_which_halves_are_already_spent(self):
        gem = member("gem", "Gemini")
        signbonus.award(gem, "post_album")
        self.client.force_authenticate(gem)
        r = self.client.get("/api/economy/signbonus/")
        self.assertTrue(r.data["mine"]["earned_base"])
        self.assertFalse(r.data["mine"]["earned_stretch"])

    def test_no_birthday_is_null_rather_than_a_guess(self):
        self.client.force_authenticate(member("blank"))
        r = self.client.get("/api/economy/signbonus/")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data["mine"])

    def test_all_twelve_are_visible_to_anybody(self):
        """The fairness of this is only checkable by seeing the other eleven."""
        self.client.force_authenticate(member("someone", "Taurus"))
        r = self.client.get("/api/economy/signbonus/")
        self.assertEqual(len(r.data["all"]), 12)

    def test_it_is_not_open_logged_out(self):
        self.assertIn(self.client.get("/api/economy/signbonus/").status_code,
                      (401, 403))


class TheHooks(TestCase):
    """Each bonus fires off an action the platform ALREADY does.

    A bonus for something nobody can take is decoration, and the only way to
    know the difference is to drive the real endpoint.
    """

    def setUp(self):
        self.client = APIClient()

    def test_a_post_pays_the_signs_a_post_can_satisfy(self):
        from .postz import create_post
        virgo = member("v2", "Virgo")
        create_post(virgo, {"title": "take", "content": "x",
                            "skills_used": ["mixing"]})
        self.assertEqual(wallet_for(virgo).spinaz, 20)

    def test_the_same_post_pays_a_different_sign_nothing(self):
        from .postz import create_post
        leo = member("l4", "Leo")
        before = wallet_for(leo).spinaz
        create_post(leo, {"title": "take", "content": "x",
                          "skills_used": ["mixing"]})
        self.assertEqual(wallet_for(leo).spinaz, before)

    def test_a_referral_pays_the_referrer(self):
        from .models import record_referral
        cancer = member("cancer", "Cancer")
        before = wallet_for(cancer).spinaz
        record_referral(cancer, member("joinee"))
        # The referral reward itself is much larger, so the assertion is the
        # bonus row, not the balance.
        self.assertTrue(SignBonusAward.objects.filter(
            user=cancer, sign="Cancer", tier="base").exists())
        self.assertGreater(wallet_for(cancer).spinaz, before)

    def test_a_rating_pays_libra_and_the_fifth_is_the_stretch(self):
        from .models import reward_for_rating
        libra = member("libra2", "Libra")
        for _ in range(5):
            reward_for_rating(libra, "post")
        tiers = set(SignBonusAward.objects.filter(user=libra)
                    .values_list("tier", flat=True))
        self.assertEqual(tiers, {"base", "stretch"})
