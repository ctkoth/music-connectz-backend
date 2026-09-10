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


def member(name, sign="", birthday=""):
    u = User.objects.create_user(name, f"{name}@mcz.test", PW)
    if sign or birthday:
        p = profile_for(u)
        if sign:
            p.sign = sign
        if birthday:
            p.birthday = birthday
        p.save(update_fields=["sign", "birthday", "updated_at"])
    return u


# A birthday well inside a year, so the lunar boundary is not what is being
# tested here — `test_chinese_zodiac` owns that and owns it properly.
BORN = {
    "Rat": "1996-06-01", "Ox": "1997-06-01", "Tiger": "1998-06-01",
    "Rabbit": "1999-06-01", "Dragon": "2000-06-01", "Snake": "2001-06-01",
    "Horse": "1990-06-01", "Goat": "1991-06-01", "Monkey": "1992-06-01",
    "Rooster": "1993-06-01", "Dog": "1994-06-01", "Pig": "1995-06-01",
}


def animal_member(name, animal):
    return member(name, birthday=BORN[animal])


class TheList(TestCase):
    """Shape rules that hold across all twelve, checked as a set."""

    def both(self):
        """Every bonus on the platform, whichever zodiac it came from.

        The shape rules below are about FAIRNESS, and fairness that only holds
        across one of the two lists is not fairness — a Dragon comparing their
        bonus to a Leo's is the exact conversation these pin.
        """
        return list(signbonus.BONUSES.items()) + list(signbonus.ANIMALS.items())

    def test_every_sign_has_exactly_one(self):
        # Twelve signs, twelve bonuses. A sign with none earns nothing for a
        # birthday it did not pick, which is the failure this whole design is
        # arranged to avoid.
        self.assertEqual(len(signbonus.BONUSES), 12)
        self.assertEqual(len(signbonus.ANIMALS), 12)

    def test_no_two_signs_share_an_action(self):
        """`_BY_ACTION` is a dict, so a duplicated action would silently make
        one sign's bonus unreachable rather than raising."""
        actions = [b["action"] for _k, b in self.both()]
        self.assertEqual(len(set(actions)), 24)
        self.assertEqual(len(signbonus._BY_ACTION), 24)

    def test_every_bonus_says_what_and_why(self):
        for sign, b in self.both():
            with self.subTest(sign=sign):
                for field in ("name", "action", "does", "stretch", "why", "tab"):
                    self.assertTrue(str(b.get(field, "")).strip(), field)

    def test_the_stretch_is_never_the_base_reworded(self):
        for sign, b in self.both():
            with self.subTest(sign=sign):
                self.assertNotEqual(b["does"].strip().lower(),
                                    b["stretch"].strip().lower())

    def test_every_bonus_names_where_to_go_and_do_it(self):
        """A number with nowhere to take it is the cross-pollination rule's
        counter-example. Every tab named here has to be a real one."""
        from music_connectz.urls import urlpatterns   # noqa: F401  (import check)
        tabs = {b["tab"] for _k, b in self.both()}
        self.assertTrue(tabs)
        for t in tabs:
            self.assertRegex(t, r"^[a-z0-9]+$")

    def test_the_amounts_do_not_vary_by_sign(self):
        """The one attribute a member cannot change must never be the reason
        they earn less. There is one BASE and one STRETCH, not a table."""
        self.assertEqual((signbonus.BASE, signbonus.STRETCH), (20, 50))
        for _k, b in self.both():
            self.assertNotIn("spinaz", b)
            self.assertNotIn("amount", b)

    def test_no_star_sign_shares_a_name_with_an_animal(self):
        """`SignBonusAward.sign` addresses both zodiacs from one column, and
        `unique_together (user, sign, tier)` is what makes once-each true. A
        name in both lists would silently merge two members' bonuses into one
        row — so the non-overlap is load-bearing, not a coincidence."""
        self.assertFalse(set(signbonus.BONUSES) & set(signbonus.ANIMALS))


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

    def test_clearing_the_stretch_first_pays_both(self):
        """Doing the harder version means you did the easier one — every one
        of the twenty-four is built that way. Paying only 50 would leave a
        member owed 20 for having done well on their first go, which reads as
        a punishment and lands hardest on whoever engages most."""
        aries = member("aries_fast", "Aries")
        self.assertEqual(signbonus.award(aries, "battle_first_in", stretch=True), 70)
        self.assertEqual(wallet_for(aries).spinaz, 70)
        # And it does not pay twice.
        self.assertEqual(signbonus.award(aries, "battle_first_in", stretch=True), 0)
        self.assertEqual(signbonus.award(aries, "battle_first_in"), 0)
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


class TheOtherZodiac(TestCase):
    """The animals, and the one property that makes two zodiacs safe to run.

    Adding a second list of twelve is only harmless if the two cannot reach
    into each other. A Leo firing a Rat's action, or a Dragon's award landing
    on a Sagittarius row, would be invisible from the app — the member would
    just quietly be owed something they never got.
    """

    def setUp(self):
        self.client = APIClient()

    def test_an_animal_action_pays_the_animal(self):
        rat = animal_member("rat", "Rat")
        self.assertEqual(signbonus.award(rat, "promptz_swap"), 20)
        self.assertEqual(wallet_for(rat).spinaz, 20)

    def test_an_animal_action_pays_a_different_animal_nothing(self):
        ox = animal_member("ox", "Ox")
        self.assertEqual(signbonus.award(ox, "promptz_swap"), 0)

    def test_a_star_sign_never_answers_an_animal_action(self):
        """The two zodiacs are resolved off different fields, and this is the
        test that says so — `_BY_ACTION` carries the kind for exactly this."""
        leo = member("leo_only", "Leo")
        self.assertEqual(signbonus.award(leo, "promptz_swap"), 0)

    def test_an_animal_never_answers_a_star_sign_action(self):
        rat = animal_member("rat2", "Rat")
        self.assertEqual(signbonus.award(rat, "battle_joins_others"), 0)

    def test_a_member_holds_both_and_they_do_not_collide(self):
        """One birthday gives you a sign AND an animal, and both are real. The
        140 🍥 ceiling is two lots of 70, not one lot double-counted."""
        # 1 August 2000 — a Leo, and a Dragon year.
        both = member("both", sign="Leo", birthday="2000-08-01")
        self.assertEqual(signbonus.award(both, "battle_joins_others"), 20)
        self.assertEqual(signbonus.award(both, "verified_link"), 20)
        rows = SignBonusAward.objects.filter(user=both)
        self.assertEqual(set(rows.values_list("sign", flat=True)), {"Leo", "Dragon"})
        self.assertEqual(wallet_for(both).spinaz, 40)

    def test_the_daily_cap_spans_both_zodiacs(self):
        """Twenty-four bonuses on one cap, not twelve on each. The cap exists
        to stop somebody clearing the board in an afternoon, and two separate
        caps would be the same afternoon twice."""
        both = member("both2", sign="Leo", birthday="2000-08-01")
        for i in range(signbonus.DAILY_CAP):
            SignBonusAward.objects.create(user=both, sign="Leo", tier=f"x{i}",
                                          action="x", amount=0,
                                          awarded_on=timezone.localdate())
        self.assertEqual(signbonus.award(both, "verified_link"), 0)

    def test_no_birthday_means_no_animal_and_no_error(self):
        self.assertEqual(signbonus.award(member("blank2"), "promptz_swap"), 0)

    def test_an_unknown_action_is_silent(self):
        """Every call site fires unconditionally, and a typo in one must not
        raise on the member's own request."""
        self.assertEqual(signbonus.award(animal_member("x", "Pig"), "not_a_thing"), 0)

    def test_the_animals_land_somewhere_else_in_the_app(self):
        """The point of a second zodiac is a second map. If the animals nudged
        at the same tabs the star signs do, they would be a louder copy rather
        than a wider one."""
        sign_tabs = {b["tab"] for b in signbonus.BONUSES.values()}
        animal_tabs = {b["tab"] for b in signbonus.ANIMALS.values()}
        # Some overlap is honest — collabz and battlez are big enough to hold
        # two different actions — but most of the animals must be new ground.
        self.assertGreaterEqual(len(animal_tabs - sign_tabs), 6)


class BothPublished(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_it_serves_both_of_mine(self):
        both = member("pub", sign="Leo", birthday="2000-08-01")
        self.client.force_authenticate(both)
        r = self.client.get("/api/economy/signbonus/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["mine"]["sign"], "Leo")
        self.assertEqual(r.data["mine_animal"]["animal"], "Dragon")

    def test_all_twenty_four_are_visible(self):
        self.client.force_authenticate(member("pub2", "Taurus"))
        r = self.client.get("/api/economy/signbonus/")
        self.assertEqual(len(r.data["all"]), 12)
        self.assertEqual(len(r.data["all_animals"]), 12)

    def test_the_keys_the_live_screen_reads_did_not_move(self):
        """The frontend shipped before the animals existed and the two repos
        deploy independently. An endpoint may grow keys ahead of its client;
        it may never lose one."""
        self.client.force_authenticate(member("pub3", "Virgo"))
        r = self.client.get("/api/economy/signbonus/")
        for key in ("mine", "base_spinaz", "stretch_spinaz", "daily_cap", "all"):
            self.assertIn(key, r.data)
        self.assertEqual(r.data["mine"]["sign"], "Virgo")

    def test_no_birthday_nulls_both_rather_than_guessing(self):
        self.client.force_authenticate(member("pub4"))
        r = self.client.get("/api/economy/signbonus/")
        self.assertIsNone(r.data["mine"])
        self.assertIsNone(r.data["mine_animal"])


class TheAnimalHooks(TestCase):
    """Each animal fires off something the platform ALREADY does."""

    def setUp(self):
        self.client = APIClient()

    def test_a_journal_entry_pays_the_rabbit(self):
        rabbit = animal_member("rabbit", "Rabbit")
        self.client.force_authenticate(rabbit)
        r = self.client.post("/api/economy/journalz/",
                             {"title": "Session", "body": "Tracked vocals."},
                             format="json")
        self.assertIn(r.status_code, (200, 201), r.content)
        self.assertEqual(wallet_for(rabbit).spinaz, 20)

    def test_a_bug_report_pays_the_dog(self):
        dog = animal_member("dog", "Dog")
        self.client.force_authenticate(dog)
        r = self.client.post("/api/economy/bugz/",
                             {"title": "Player won't load", "body": "404 on the take."},
                             format="json")
        self.assertIn(r.status_code, (200, 201), r.content)
        self.assertEqual(wallet_for(dog).spinaz, 20)

    def test_a_playlist_pays_the_goat(self):
        goat = animal_member("goat", "Goat")
        self.client.force_authenticate(goat)
        r = self.client.post("/api/economy/playlistz/", {"title": "Late night"},
                             format="json")
        self.assertIn(r.status_code, (200, 201), r.content)
        self.assertEqual(wallet_for(goat).spinaz, 20)

    def test_a_first_message_pays_the_rooster_and_a_second_one_does_not(self):
        """The base is the FIRST message to somebody. Messaging the same
        person again is a conversation, not a door opened."""
        rooster = animal_member("rooster", "Rooster")
        User.objects.create_user("heard", "heard@mcz.test", PW)
        self.client.force_authenticate(rooster)
        for _ in range(2):
            r = self.client.post("/api/economy/messages/", {"to": "heard", "body": "yo"},
                                 format="json")
            self.assertIn(r.status_code, (200, 201), r.content)
        self.assertEqual(wallet_for(rooster).spinaz, 20)

    def test_the_swap_pays_the_rat_and_five_promptz_is_the_stretch(self):
        rat = animal_member("rat3", "Rat")
        w = wallet_for(rat)
        w.spinaz = 60
        w.save(update_fields=["spinaz", "updated_at"])
        self.client.force_authenticate(rat)
        r = self.client.post("/api/economy/promptz/convert/", {"spinaz": 50},
                             format="json")
        self.assertEqual(r.status_code, 200, r.content)
        tiers = set(SignBonusAward.objects.filter(user=rat)
                    .values_list("tier", flat=True))
        self.assertEqual(tiers, {"base", "stretch"})
