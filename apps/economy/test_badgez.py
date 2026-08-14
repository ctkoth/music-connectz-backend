"""BadgeZ — a title you wear and an effect you feel.

The standard every badge is held to: it changes a number the member can point
at, and the effect is read by the system it affects. A badge whose multiplier
lived only in its description would be a sticker.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import (
    BADGES,
    Badge,
    ItemRating,
    Post,
    PostContributor,
    RATING_REWARD_DAILY_CAP,
    TIER_FREE,
    TIER_STATZ,
    badge_effects,
    energy_rate_per_hour,
    grant_badge,
    membership_for,
    profile_for,
    recheck_badges,
)

User = get_user_model()
PW = "hunter2hunter2"
BADGEZ = "/api/economy/badgez/"
GIFT = "/api/economy/badgez/gift/"


class BadgeBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="maker", password=PW)
        membership_for(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.owner = User.objects.create_user(username="owner", password=PW,
                                              is_staff=True, is_superuser=True)
        membership_for(self.owner)
        self.oc = APIClient(); self.oc.force_authenticate(self.owner)


class EveryBadgeDoesSomethingTests(BadgeBase):
    def test_no_badge_is_only_decoration(self):
        # The whole rule, asserted once.
        for key, spec in BADGES.items():
            self.assertTrue(spec.get("effects"), f"{key} has no effect")
            self.assertTrue(spec.get("effect_note"), f"{key} doesn't say what it does")

    def test_every_badge_says_how_it_is_come_by(self):
        for key, spec in BADGES.items():
            self.assertTrue(spec.get("how"), key)
            # Earned badges carry a check; gifted ones say they're gifted.
            self.assertTrue(spec.get("check") or spec.get("gifted"), key)

    def test_the_seat_count_has_one_source(self):
        from apps.economy.catalog import FOUNDING_LIMIT
        from apps.economy.models import FOUNDING_SEATS
        self.assertIs(FOUNDING_SEATS, FOUNDING_LIMIT)

    def test_effects_add_up_across_badges(self):
        grant_badge(self.user, "verified_reach")     # ×1.25
        grant_badge(self.user, "founding")           # ×2
        # Multiplied at full precision and rounded once, not at each step.
        self.assertEqual(badge_effects(self.user)["energy_multiplier"], 2.5)

    def test_a_paid_seat_outranks_a_looks_rating(self):
        # A member who paid $150 for one of fifty scarce seats earning less
        # than a member the room rated attractive reads badly, and it is the
        # founder who would notice.
        self.assertGreaterEqual(BADGES["founding"]["effects"]["energy_multiplier"],
                                BADGES["sexy"]["effects"]["energy_multiplier"])
        paid_and_proven = (BADGES["founding"]["effects"]["energy_multiplier"]
                           * BADGES["verified_reach"]["effects"]["energy_multiplier"])
        self.assertGreater(paid_and_proven, BADGES["sexy"]["effects"]["energy_multiplier"])

    def test_the_energy_stack_has_a_ceiling(self):
        # Multipliers compound. Without a cap the maximum is whatever badges
        # happen to exist rather than something anybody chose.
        from apps.economy.models import MAX_ENERGY_MULTIPLIER
        for key in ("founding", "verified_reach", "sexy"):
            grant_badge(self.user, key)
        raw = 2.0 * 1.25 * 2.0
        self.assertGreater(raw, MAX_ENERGY_MULTIPLIER)      # the cap binds
        self.assertEqual(badge_effects(self.user)["energy_multiplier"],
                         MAX_ENERGY_MULTIPLIER)

    def test_the_cap_does_not_touch_a_stack_below_it(self):
        grant_badge(self.user, "founding")
        self.assertEqual(badge_effects(self.user)["energy_multiplier"], 2.0)

    def test_effects_are_computed_not_stored(self):
        # A stored copy is how an effect outlives the badge that justified it.
        grant_badge(self.user, "verified_reach")
        self.assertIn("energy_multiplier", badge_effects(self.user))
        Badge.objects.filter(user=self.user, key="verified_reach").delete()
        self.assertNotIn("energy_multiplier", badge_effects(self.user))


class TheEffectsActuallyBiteTests(BadgeBase):
    def test_the_energy_multiplier_moves_the_energy_rate(self):
        p = profile_for(self.user)
        p.links = [{"label": "IG", "url": "https://x.test", "verified": True,
                    "followers": 1000, "verified_count": 1000}]
        p.save(update_fields=["links"])
        fresh = User.objects.get(pk=self.user.pk)
        before = energy_rate_per_hour(fresh)
        self.assertGreater(before, 0)
        grant_badge(self.user, "founding")
        self.assertEqual(energy_rate_per_hour(User.objects.get(pk=self.user.pk)),
                         int(before * 2.0))

    def test_the_rating_cap_bonus_raises_the_cap_that_pays(self):
        from apps.economy.models import Transaction, reward_for_rating
        # Fill the base cap.
        for i in range(RATING_REWARD_DAILY_CAP):
            reward_for_rating(self.user, f"post:{i}")
        self.assertEqual(reward_for_rating(self.user, "post:x"), 0)
        grant_badge(self.user, "ear")
        self.assertGreater(reward_for_rating(self.user, "post:y"), 0)

    def test_the_owner_badge_grants_statz_the_moment_it_lands(self):
        # A tier that only applies on some later unrelated save is a promise
        # with a delay nobody explained.
        self.assertEqual(membership_for(self.user).tier, TIER_FREE)
        grant_badge(self.user, "owner")
        self.assertEqual(membership_for(self.user).tier, TIER_STATZ)

    def test_the_owner_badge_carries_the_tax_and_the_royalties(self):
        grant_badge(self.user, "owner")
        fx = badge_effects(self.user)
        self.assertEqual(fx["dev_tax_share"], 1.0)
        self.assertTrue(fx["intelligence_royalties"])


class EarnedNotClaimedTests(BadgeBase):
    def test_verified_reach_lands_when_an_account_is_verified(self):
        p = profile_for(self.user)
        p.links = [{"label": "IG", "url": "https://x.test", "verified": True,
                    "followers": 500}]
        p.save(update_fields=["links"])
        self.assertIn("verified_reach", recheck_badges(User.objects.get(pk=self.user.pk)))

    def test_it_does_not_land_on_an_unverified_link(self):
        p = profile_for(self.user)
        p.links = [{"label": "IG", "url": "https://x.test", "followers": 999999}]
        p.save(update_fields=["links"])
        self.assertNotIn("verified_reach", recheck_badges(User.objects.get(pk=self.user.pk)))

    def test_the_collaborator_badge_counts_shipped_collabs(self):
        for i in range(10):
            post = Post.objects.create(author=self.owner, title=f"c{i}")
            PostContributor.objects.create(post=post, user=self.user, slot="image")
        self.assertIn("collaborator", recheck_badges(self.user))

    def test_nine_is_not_ten(self):
        for i in range(9):
            post = Post.objects.create(author=self.owner, title=f"c{i}")
            PostContributor.objects.create(post=post, user=self.user, slot="image")
        self.assertNotIn("collaborator", recheck_badges(self.user))

    def test_the_ear_counts_ratings_given_not_received(self):
        for i in range(100):
            ItemRating.objects.create(user=self.user, item_id=f"post:{i}", score=8)
        self.assertIn("ear", recheck_badges(self.user))

    def test_an_earned_badge_cannot_be_gifted(self):
        # Handing out an earned badge by favour would make every earned badge
        # unreadable — nobody could tell which were met and which were granted.
        r = self.oc.post(GIFT, {"key": "collaborator", "username": "maker"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("earned, not gifted", r.data["detail"])

    def test_only_the_owner_gifts(self):
        r = self.client.post(GIFT, {"key": "founding", "username": "maker"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_the_owner_can_gift_a_gifted_badge(self):
        r = self.oc.post(GIFT, {"key": "bug_hunter", "username": "maker"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(Badge.objects.filter(user=self.user, key="bug_hunter").exists())

    def test_gifting_twice_does_not_duplicate(self):
        self.oc.post(GIFT, {"key": "bug_hunter", "username": "maker"}, format="json")
        again = self.oc.post(GIFT, {"key": "bug_hunter", "username": "maker"}, format="json")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(Badge.objects.filter(user=self.user).count(), 1)

    def test_a_founding_seat_cannot_be_handed_out(self):
        # The seat is real — 50 of them, priced in catalog.FOUNDING_PLANS and
        # recorded on Membership. A badge gifted by hand would say somebody
        # holds one when the record says they don't.
        r = self.oc.post(GIFT, {"key": "founding", "username": "maker"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_claiming_a_seat_grants_the_badge_there_and_then(self):
        # Waiting to be noticed is a poor way to be told you got the thing you
        # just paid for.
        from apps.economy.models import grant_lifetime
        grant_lifetime(self.user)
        self.assertTrue(Badge.objects.filter(user=self.user, key="founding").exists())

    def test_the_founding_badge_follows_the_membership_record(self):
        self.assertNotIn("founding", recheck_badges(self.user))
        m = membership_for(self.user)
        m.founding = True
        m.save(update_fields=["founding"])
        self.assertIn("founding", recheck_badges(self.user))

    def test_the_founding_badge_does_not_claim_to_own_the_discount(self):
        # The half-price lives in catalog.FOUNDING_PLANS. A badge asserting a
        # second version of it is two sources of truth for one fact.
        self.assertNotIn("lifetime_discount_pct", BADGES["founding"]["effects"])

    def test_the_member_is_told_what_it_does(self):
        grant_badge(self.user, "founding")
        note = self.user.notifications.first()
        self.assertIn("Founding Fifty", note.text)
        # What the BADGE adds — not the seat's discount, which the badge
        # deliberately no longer claims to own.
        self.assertIn("Double Energy", note.text)


class TitlesAndPrivacyTests(BadgeBase):
    def setUp(self):
        super().setUp()
        grant_badge(self.user, "straight_shooter")

    def test_a_title_can_be_worn_once_the_badge_is_held(self):
        r = self.client.patch(BADGEZ, {"title": "Straight Shooter"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["title"], "Straight Shooter")

    def test_a_title_you_do_not_hold_is_refused(self):
        r = self.client.patch(BADGEZ, {"title": "Owner"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(profile_for(self.user).badge_title, "")

    def test_a_badge_can_be_hidden(self):
        # An achievement is also a disclosure.
        self.client.patch(BADGEZ, {"key": "straight_shooter", "visible": False},
                          format="json")
        seen = self.oc.get(f"{BADGEZ}?username=maker").data["badges"]
        self.assertEqual(seen, [])

    def test_hiding_a_badge_does_not_cost_you_its_effect(self):
        # Privacy that costs you something you earned is privacy with a price.
        self.client.patch(BADGEZ, {"key": "straight_shooter", "visible": False},
                          format="json")
        self.assertTrue(badge_effects(self.user)["stake_waived"])

    def test_hiding_the_badge_takes_its_title_down_too(self):
        # Otherwise the title leaks what the switch was meant to conceal.
        self.client.patch(BADGEZ, {"title": "Straight Shooter"}, format="json")
        self.client.patch(BADGEZ, {"key": "straight_shooter", "visible": False},
                          format="json")
        self.assertEqual(profile_for(self.user).badge_title, "")

    def test_only_the_holder_sees_the_privacy_switch(self):
        mine = self.client.get(BADGEZ).data["badges"][0]
        theirs = self.oc.get(f"{BADGEZ}?username=maker").data["badges"][0]
        self.assertIn("visible", mine)
        self.assertNotIn("visible", theirs)

    def test_the_whole_catalogue_is_shown_so_nothing_is_a_surprise(self):
        keys = {b["key"] for b in self.client.get(BADGEZ).data["catalogue"]}
        self.assertEqual(keys, set(BADGES))


class GiftedAndSexyTests(BadgeBase):
    """The two newest, and the line between them.

    Gifted rewards the WORK and pays in the work economy. Sexy rewards nothing
    in the work economy on purpose.
    """

    def rate_my_posts(self, score, n=5):
        from django.contrib.auth import get_user_model
        U = get_user_model()
        for i in range(n):
            post = Post.objects.create(author=self.user, title=f"p{i}")
            rater = U.objects.create_user(username=f"r{i}", password=PW)
            ItemRating.objects.create(user=rater, item_id=f"post:{post.id}", score=score)

    def test_gifted_lands_on_well_rated_work(self):
        self.rate_my_posts(9)
        self.assertIn("gifted", recheck_badges(self.user))

    def test_it_needs_enough_rated_posts_to_mean_anything(self):
        # One 10 is not a track record.
        self.rate_my_posts(10, n=2)
        self.assertNotIn("gifted", recheck_badges(self.user))

    def test_middling_work_does_not_earn_it(self):
        self.rate_my_posts(6)
        self.assertNotIn("gifted", recheck_badges(self.user))

    def test_gifted_actually_makes_posting_cheaper(self):
        from apps.economy.postz import post_cost_cents
        p = profile_for(self.user)
        p.personas = [{"key": "p", "name": "P",
                       "skills": [{"name": "Beat Producer", "rate_cents": 40}]}]
        p.save(update_fields=["personas"])
        full, _ = post_cost_cents(self.user, ["Beat Producer"])
        self.assertEqual(full, 40)
        grant_badge(self.user, "gifted")
        discounted, _ = post_cost_cents(self.user, ["Beat Producer"])
        self.assertEqual(discounted, 30)          # 25% off, on the button

    def test_sexy_lands_above_eight(self):
        from apps.economy.models import AttractivenessRating
        from django.contrib.auth import get_user_model
        U = get_user_model()
        for i in range(3):
            rater = U.objects.create_user(username=f"a{i}", password=PW)
            AttractivenessRating.objects.create(rater=rater, target=self.user, score=9)
        self.assertIn("sexy", recheck_badges(self.user))

    def test_exactly_eight_is_not_above_eight(self):
        from apps.economy.models import AttractivenessRating
        from django.contrib.auth import get_user_model
        U = get_user_model()
        for i in range(3):
            rater = U.objects.create_user(username=f"b{i}", password=PW)
            AttractivenessRating.objects.create(rater=rater, target=self.user, score=8)
        self.assertNotIn("sexy", recheck_badges(self.user))

    def test_sexy_doubles_the_energy_rate(self):
        # Corey's call. I argued for keeping attractiveness out of the economy;
        # he decided ⚡×2, and it's temporary, which is most of what worried me.
        p = profile_for(self.user)
        p.links = [{"label": "IG", "url": "https://x.test", "verified": True,
                    "followers": 1000, "verified_count": 1000}]
        p.save(update_fields=["links"])
        before = energy_rate_per_hour(User.objects.get(pk=self.user.pk))
        grant_badge(self.user, "sexy")
        self.assertEqual(energy_rate_per_hour(User.objects.get(pk=self.user.pk)),
                         before * 2)


class ArtworkTests(BadgeBase):
    def test_a_badge_with_art_names_it(self):
        self.assertEqual(BADGES["owner"]["icon"], "badge_owner.png")
        self.assertEqual(BADGES["founding"]["icon"], "badge_founding.png")
        self.assertEqual(BADGES["gifted"]["icon"], "badge_gifted.png")

    def test_the_icon_is_served_with_the_badge(self):
        grant_badge(self.user, "owner")
        row = self.client.get(BADGEZ).data["badges"][0]
        self.assertEqual(row["icon"], "badge_owner.png")

    def test_a_badge_without_art_still_has_its_emoji(self):
        # The emoji is the fallback, so it is never optional.
        for key, spec in BADGES.items():
            self.assertTrue(spec.get("emoji"), key)

    def test_no_two_badges_share_artwork(self):
        icons = [s["icon"] for s in BADGES.values() if s.get("icon")]
        self.assertEqual(len(icons), len(set(icons)))


class TemporaryBadgesTests(BadgeBase):
    """A badge tracking a live median has to be able to lapse.

    Otherwise the first member to touch 8 keeps the effect forever and the
    number stops meaning anything.
    """

    def rate_me(self, score, n=3):
        from apps.economy.models import AttractivenessRating
        from django.contrib.auth import get_user_model
        U = get_user_model()
        AttractivenessRating.objects.filter(target=self.user).delete()
        for i in range(n):
            rater = U.objects.filter(username=f"a{i}").first() or \
                U.objects.create_user(username=f"a{i}", password=PW)
            AttractivenessRating.objects.create(rater=rater, target=self.user, score=score)

    def test_sexy_lands_above_eight(self):
        self.rate_me(9)
        self.assertIn("sexy", recheck_badges(self.user))

    def test_exactly_eight_is_not_above_eight(self):
        self.rate_me(8)
        self.assertNotIn("sexy", recheck_badges(self.user))

    def test_sexy_doubles_energy_while_you_hold_it(self):
        p = profile_for(self.user)
        p.links = [{"label": "IG", "url": "https://x.test", "verified": True,
                    "followers": 1000, "verified_count": 1000}]
        p.save(update_fields=["links"])
        before = energy_rate_per_hour(User.objects.get(pk=self.user.pk))
        grant_badge(self.user, "sexy")
        self.assertEqual(energy_rate_per_hour(User.objects.get(pk=self.user.pk)),
                         before * 2)

    def test_it_is_taken_back_when_the_median_falls(self):
        self.rate_me(9)
        recheck_badges(self.user)
        self.assertTrue(Badge.objects.filter(user=self.user, key="sexy").exists())
        self.rate_me(4)
        recheck_badges(User.objects.get(pk=self.user.pk))
        self.assertFalse(Badge.objects.filter(user=self.user, key="sexy").exists())

    def test_losing_it_takes_the_effect_with_it(self):
        self.rate_me(9)
        recheck_badges(self.user)
        self.assertIn("energy_multiplier", badge_effects(self.user))
        self.rate_me(3)
        recheck_badges(User.objects.get(pk=self.user.pk))
        self.assertNotIn("energy_multiplier", badge_effects(self.user))

    def test_losing_it_is_never_silent(self):
        # The member's Energy rate changes; nothing else would explain why.
        self.rate_me(9)
        recheck_badges(self.user)
        self.user.notifications.all().delete()
        self.rate_me(2)
        recheck_badges(User.objects.get(pk=self.user.pk))
        note = self.user.notifications.first()
        self.assertIn("lapsed", note.text)
        self.assertIn("returns by itself", note.text)

    def test_losing_it_takes_the_title_down_too(self):
        self.rate_me(9)
        recheck_badges(self.user)
        self.client.patch(BADGEZ, {"title": "Sexy"}, format="json")
        self.assertEqual(profile_for(self.user).badge_title, "Sexy")
        self.rate_me(2)
        recheck_badges(User.objects.get(pk=self.user.pk))
        self.assertEqual(profile_for(self.user).badge_title, "")

    def test_gifted_lapses_when_the_work_stops_scoring(self):
        from django.contrib.auth import get_user_model
        U = get_user_model()
        posts = []
        for i in range(5):
            post = Post.objects.create(author=self.user, title=f"p{i}")
            posts.append(post)
            rater = U.objects.create_user(username=f"g{i}", password=PW)
            ItemRating.objects.create(user=rater, item_id=f"post:{post.id}", score=9)
        self.assertIn("gifted", recheck_badges(self.user))
        ItemRating.objects.filter(item_id__in=[f"post:{p.id}" for p in posts]).update(score=4)
        recheck_badges(self.user)
        self.assertFalse(Badge.objects.filter(user=self.user, key="gifted").exists())

    def test_a_permanent_badge_is_never_taken_back(self):
        # A shipped collab HAPPENED. No later state undoes it.
        for i in range(10):
            post = Post.objects.create(author=self.owner, title=f"c{i}")
            PostContributor.objects.create(post=post, user=self.user, slot="image")
        self.assertIn("collaborator", recheck_badges(self.user))
        PostContributor.objects.filter(user=self.user).delete()
        recheck_badges(self.user)
        self.assertTrue(Badge.objects.filter(user=self.user, key="collaborator").exists())

    def test_only_the_median_badges_are_temporary(self):
        temp = {k for k, s in BADGES.items() if s.get("temporary")}
        self.assertEqual(temp, {"gifted", "sexy"})

    def test_a_row_says_whether_it_can_lapse(self):
        # The condition has to be MET, not just the badge granted: reading the
        # list re-checks, and a temporary badge whose condition is false is
        # revoked on the spot. That's the feature working.
        self.rate_me(9)
        recheck_badges(self.user)
        row = [b for b in self.client.get(BADGEZ).data["badges"] if b["key"] == "sexy"][0]
        self.assertTrue(row["temporary"])
        self.assertEqual(row["icon"], "badge_sexy.png")


class PolyglotTests(BadgeBase):
    """Fifty translations lifts the daily character allowance.

    The badge's own wording is "translation stops costing", and translation
    already costs no 💵 and no 🏷️ — it's free at every tier on purpose. What it
    actually costs is the daily allowance, so that is what has to move. A badge
    removing a price nobody was charged would be the sticker this catalogue
    doesn't ship.
    """

    def translate_times(self, n, chars=10):
        from apps.economy.models import KeyTranslation
        for _ in range(n):
            KeyTranslation.objects.create(user=self.user, source_lang="en",
                                          target_lang="es", chars=chars)

    def test_fifty_translations_earns_it(self):
        self.translate_times(50)
        self.assertIn("polyglot", recheck_badges(self.user))

    def test_forty_nine_does_not(self):
        self.translate_times(49)
        self.assertNotIn("polyglot", recheck_badges(self.user))

    def test_the_allowance_stops_applying(self):
        from apps.economy.models import KEY_TRANSLATE_DAILY_CHARS, key_translate_state
        used, cap, left = key_translate_state(self.user)
        self.assertEqual(cap, KEY_TRANSLATE_DAILY_CHARS)
        grant_badge(self.user, "polyglot")
        used, cap, left = key_translate_state(User.objects.get(pk=self.user.pk))
        # None, not a very large number: a made-up ceiling printed on screen is
        # a limit pretending somebody chose it.
        self.assertIsNone(cap)
        self.assertIsNone(left)

    def test_the_keyboard_says_so_before_anyone_types(self):
        resp = self.client.get("/api/economy/keyz/")
        self.assertFalse(resp.data["translate_uncapped"])
        grant_badge(self.user, "polyglot")
        resp = self.client.get("/api/economy/keyz/")
        self.assertTrue(resp.data["translate_uncapped"])
        self.assertIsNone(resp.data["translate_daily_chars"])

    def test_a_spent_allowance_no_longer_refuses_the_holder(self):
        from apps.economy.models import KEY_TRANSLATE_DAILY_CHARS
        self.translate_times(1, chars=KEY_TRANSLATE_DAILY_CHARS)
        resp = self.client.post("/api/economy/keyz/translate/",
                                {"text": "hola", "target_lang": "en"}, format="json")
        self.assertEqual(resp.status_code, 429)
        grant_badge(self.user, "polyglot")
        resp = self.client.post("/api/economy/keyz/translate/",
                                {"text": "hola", "target_lang": "en"}, format="json")
        # It gets past the allowance. Whether the model answers is the
        # translator's problem, not the badge's.
        self.assertNotEqual(resp.status_code, 429)

    def test_it_is_not_temporary(self):
        # Fifty translations happened. Unlike a live median, that can't un-happen.
        self.assertFalse(BADGES["polyglot"].get("temporary"))


class PatronTests(BadgeBase):
    """Five clean deals you BANKROLLED shortens escrow on deals you fund.

    The effect spends the holder's own protection and nobody else's — the
    auto-release window is each payer's last chance to open a dispute. That is
    the whole reason it's safe to hand out, and the reason every payer on a
    deal has to hold it before it applies.
    """

    def setUp(self):
        super().setUp()
        from apps.economy.collab import escrow_release_days
        from django.conf import settings
        self.escrow_release_days = escrow_release_days
        self.base = settings.ESCROW_AUTO_RELEASE_DAYS
        self.floor = settings.ESCROW_MIN_RELEASE_DAYS

    def deal(self, status, payers=(("maker", True),), **over):
        from apps.economy.models import CollabDeal
        return CollabDeal.objects.create(
            initiator=self.user, title="EP", status=status,
            participants=[{"username": n, "pays_cents": 1000, "funded": f,
                           "receives_cents": 0} for n, f in payers],
            **over)

    # --- earning it ---
    def test_five_funded_clean_releases_earns_it(self):
        for _ in range(5):
            self.deal("released")
        self.assertIn("patron", recheck_badges(self.user))

    def test_four_does_not(self):
        for _ in range(4):
            self.deal("released")
        self.assertNotIn("patron", recheck_badges(self.user))

    def test_being_on_a_deal_is_not_funding_one(self):
        # Credited but never paid in. Straight Shooter counts that; this doesn't.
        for _ in range(5):
            self.deal("released", payers=(("maker", False),))
        self.assertNotIn("patron", recheck_badges(self.user))

    def test_a_refunded_deal_is_not_a_clean_release(self):
        for _ in range(5):
            self.deal("refunded")
        self.assertNotIn("patron", recheck_badges(self.user))

    def test_one_open_dispute_and_it_is_not_yours(self):
        for _ in range(5):
            self.deal("released")
        self.deal("disputed")
        self.assertNotIn("patron", recheck_badges(self.user))

    # --- the effect ---
    def test_without_it_the_window_is_the_default(self):
        d = self.deal("funded")
        self.assertEqual(self.escrow_release_days(d), self.base)

    def test_with_it_the_window_shortens(self):
        grant_badge(self.user, "patron")
        d = self.deal("funded")
        self.assertEqual(self.escrow_release_days(d),
                         max(self.floor, self.base - 7))

    def test_it_never_goes_below_the_floor(self):
        # The window is the payer's safety rail. A badge that could drive it to
        # zero would be a badge for skipping one.
        grant_badge(self.user, "patron")
        d = self.deal("funded")
        self.assertGreaterEqual(self.escrow_release_days(d), self.floor)

    def test_one_patron_cannot_shorten_a_co_payers_window(self):
        # The thing being spent is protection. Spending your own is generous;
        # spending somebody else's is a badge aimed at a person.
        mate = User.objects.create_user(username="mate", password=PW)
        membership_for(mate)
        grant_badge(self.user, "patron")
        d = self.deal("funded", payers=(("maker", True), ("mate", True)))
        self.assertEqual(self.escrow_release_days(d), self.base)

    def test_both_holding_it_does_shorten(self):
        mate = User.objects.create_user(username="mate", password=PW)
        membership_for(mate)
        grant_badge(self.user, "patron")
        grant_badge(mate, "patron")
        d = self.deal("funded", payers=(("maker", True), ("mate", True)))
        self.assertEqual(self.escrow_release_days(d), max(self.floor, self.base - 7))

    def test_an_unknown_payer_is_never_assumed_to_have_agreed(self):
        grant_badge(self.user, "patron")
        d = self.deal("funded", payers=(("maker", True), ("ghost", True)))
        self.assertEqual(self.escrow_release_days(d), self.base)

    def test_the_window_is_published_before_anybody_funds(self):
        # Cost/gain: a payer is told how long their money sits BEFORE it does.
        from apps.economy.collab import deal_dict
        grant_badge(self.user, "patron")
        d = self.deal("draft")
        row = deal_dict(d, self.user)
        self.assertEqual(row["auto_release_days"], max(self.floor, self.base - 7))
        self.assertEqual(row["auto_release_default_days"], self.base)

    def test_funding_the_deal_uses_the_shortened_window(self):
        from datetime import timedelta
        from django.utils import timezone
        from apps.economy.models import CollabDeal, wallet_for
        mate = User.objects.create_user(username="mate", password=PW)
        membership_for(mate)
        grant_badge(self.user, "patron")
        w = wallet_for(self.user)
        w.spinaz = 10_000
        w.save(update_fields=["spinaz"])
        deal = CollabDeal.objects.create(
            initiator=self.user, title="EP", status=CollabDeal.STATUS_DRAFT,
            currency=CollabDeal.CURRENCY_SPINAZ,
            participants=[{"username": "maker", "pays_cents": 100, "funded": False,
                           "receives_cents": 0},
                          {"username": "mate", "pays_cents": 0, "funded": False,
                           "receives_cents": 100}])
        resp = self.client.post(f"/api/economy/collab/{deal.id}/fund/", {}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        deal.refresh_from_db()
        want = timezone.now() + timedelta(days=max(self.floor, self.base - 7))
        self.assertLess(abs((deal.auto_release_at - want).total_seconds()), 120)


class BadgesOnProfileZTests(BadgeBase):
    """A badge nobody can see is a database row. ProfileZ is where it's worn.

    The BadgeZ tab is where a badge is explained and switched; the profile is
    where it does its job — telling the room something true about the member
    before they've said a word.
    """

    PROFILE = "/api/economy/profile/"

    def member(self, username):
        return f"/api/economy/members/{username}/"

    def test_your_own_profile_wears_your_badges(self):
        grant_badge(self.user, "owner")
        row = self.client.get(self.PROFILE).data["badges"][0]
        self.assertEqual(row["key"], "owner")
        self.assertEqual(row["emoji"], "👑")
        self.assertEqual(row["icon"], "badge_owner.png")
        # What it DOES travels with it. A badge on a card that explains
        # nothing is the sticker this whole file refuses to be.
        self.assertTrue(row["effect_note"])
        # And it's a door, not a dead end.
        self.assertEqual(row["open_in"], "badgez")

    def test_another_member_sees_the_badge_too(self):
        grant_badge(self.user, "ear")
        d = self.oc.get(self.member("maker")).data
        self.assertEqual([b["key"] for b in d["badges"]], ["ear"])

    def test_a_hidden_badge_is_not_on_the_profile(self):
        # The privacy switch in BadgeZ is only worth anything if the surface
        # it's meant to control actually honours it.
        grant_badge(self.user, "ear")
        Badge.objects.filter(user=self.user, key="ear").update(visible=False)
        self.assertEqual(self.oc.get(self.member("maker")).data["badges"], [])
        mine = self.client.get(self.PROFILE).data
        self.assertEqual(mine["badges"], [])
        # You can see THAT you're hiding one. Naming it here would undo it.
        self.assertEqual(mine["badges_hidden"], 1)

    def test_the_worn_title_is_on_the_card(self):
        grant_badge(self.user, "straight_shooter")
        p = profile_for(self.user)
        p.badge_title = "Straight Shooter"
        p.save(update_fields=["badge_title"])
        self.assertEqual(self.oc.get(self.member("maker")).data["badge_title"],
                         "Straight Shooter")

    def test_the_effect_total_is_yours_alone(self):
        # An effect total is a read of somebody's economy, not a fact to
        # publish about them. The badge is public; the arithmetic isn't.
        grant_badge(self.user, "verified_reach")
        self.assertEqual(self.client.get(self.PROFILE).data["badge_effects"]
                         ["energy_multiplier"], 1.25)
        self.assertEqual(self.oc.get(self.member("maker")).data["badge_effects"], {})
        self.assertEqual(self.oc.get(self.member("maker")).data["badges_hidden"], 0)

    def test_opening_your_own_profile_grants_what_you_earned(self):
        p = profile_for(self.user)
        p.links = [{"label": "IG", "url": "https://x.test", "verified": True,
                    "followers": 500}]
        p.save(update_fields=["links"])
        self.assertEqual([b["key"] for b in self.client.get(self.PROFILE).data["badges"]],
                         ["verified_reach"])

    def test_looking_at_somebody_else_does_not_move_their_badges(self):
        # Re-checking a stranger's badges on read would let anybody grant or
        # lapse somebody else's by opening their card.
        grant_badge(self.user, "sexy")          # temporary, and no median backs it
        self.assertEqual([b["key"] for b in self.oc.get(self.member("maker")).data["badges"]],
                         ["sexy"])
        self.assertTrue(Badge.objects.filter(user=self.user, key="sexy").exists())

    def test_a_lapsed_badge_leaves_the_profile_with_its_title(self):
        grant_badge(self.user, "sexy")          # nothing supports the median
        p = profile_for(self.user)
        p.badge_title = "Sexy"
        p.save(update_fields=["badge_title"])
        d = self.client.get(self.PROFILE).data
        self.assertEqual(d["badges"], [])
        # The title went with it. Wearing a title for a badge you no longer
        # hold is the badge outliving its own condition.
        self.assertEqual(d["badge_title"], "")

    def test_member_search_wears_badges_in_one_query(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        for i in range(4):
            other = User.objects.create_user(username=f"m{i}", password=PW)
            membership_for(other)
            profile_for(other)
            grant_badge(other, "ear")
        with CaptureQueriesContext(connection) as ctx:
            d = self.client.get("/api/economy/members/").data
        self.assertTrue(any(b["key"] == "ear"
                            for card in d["members"] for b in card["badges"]))
        badge_queries = [q for q in ctx.captured_queries
                         if "economy_badge" in q["sql"] and "economy_badge_" not in q["sql"]]
        # One for the whole page. Per-card would put a query per member behind
        # a search that already does enough work.
        self.assertLessEqual(len(badge_queries), 2, badge_queries)


class PublicCardWearsBadgesTests(BadgeBase):
    """A shared profile is somebody's proof they're worth hiring."""

    def public(self, username):
        return f"/api/economy/public/members/{username}/"

    def test_the_public_card_carries_the_badge(self):
        profile_for(self.user)
        grant_badge(self.user, "straight_shooter")
        anon = APIClient()
        d = anon.get(self.public("maker")).data
        row = d["badges"][0]
        self.assertEqual(row["key"], "straight_shooter")
        self.assertEqual(row["emoji"], "🎯")
        # What it took to get one — that's the part a stranger came to find out.
        self.assertTrue(row["how"])

    def test_the_public_card_does_not_carry_what_the_badge_pays(self):
        # Effects are a read of somebody's economy and belong behind the login.
        profile_for(self.user)
        grant_badge(self.user, "straight_shooter")
        row = APIClient().get(self.public("maker")).data["badges"][0]
        self.assertNotIn("effect_note", row)
        self.assertNotIn("open_in", row)

    def test_a_hidden_badge_stays_hidden_from_the_open_web(self):
        profile_for(self.user)
        grant_badge(self.user, "straight_shooter")
        Badge.objects.filter(user=self.user).update(visible=False)
        self.assertEqual(APIClient().get(self.public("maker")).data["badges"], [])


class TheOwnerHoldsTheOwnerBadgeTests(TestCase):
    """"This is whose app it is" is a fact the server already knows.

    Leaving it to a gift POST would mean the owner has to hand it to
    themselves, and would leave it missing on every account promoted before
    BadgeZ existed.
    """

    def owner_user(self, **kw):
        return User.objects.create_user(password=PW, **kw)

    def test_the_configured_owner_lands_with_the_badge(self):
        from apps.economy.views import ensure_owner
        with self.settings(OWNER_EMAILS=["boss@test.test"], OWNER_USERNAMES=[]):
            u = self.owner_user(username="boss", email="boss@test.test")
            ensure_owner(User.objects.get(pk=u.pk))
        self.assertTrue(Badge.objects.filter(user=u, key="owner").exists())
        self.assertEqual(membership_for(u).tier, TIER_STATZ)
        fx = badge_effects(u)
        self.assertEqual(fx["dev_tax_share"], 1.0)
        self.assertTrue(fx["intelligence_royalties"])

    def test_it_lands_by_username_too(self):
        from apps.economy.views import ensure_owner
        with self.settings(OWNER_EMAILS=[], OWNER_USERNAMES=["K-Oth"]):
            u = self.owner_user(username="K-Oth", email="")
            ensure_owner(User.objects.get(pk=u.pk))
        self.assertTrue(Badge.objects.filter(user=u, key="owner").exists())

    def test_stats_hands_it_over_on_the_way_in(self):
        # The self-heal path: the owner never has to do anything.
        from rest_framework.test import APIClient
        with self.settings(OWNER_EMAILS=["boss@test.test"], OWNER_USERNAMES=[]):
            u = self.owner_user(username="boss", email="boss@test.test")
            membership_for(u)
            c = APIClient(); c.force_authenticate(u)
            self.assertTrue(c.get("/api/auth/stats/").data["is_owner"])
        self.assertTrue(Badge.objects.filter(user=u, key="owner").exists())

    def test_nobody_else_gets_it(self):
        from apps.economy.views import ensure_owner
        with self.settings(OWNER_EMAILS=["boss@test.test"], OWNER_USERNAMES=[]):
            u = self.owner_user(username="rando", email="rando@test.test")
            ensure_owner(User.objects.get(pk=u.pk))
        self.assertFalse(Badge.objects.filter(user=u, key="owner").exists())

    def test_a_deliberate_debug_switch_outranks_the_badge(self):
        # The badge applies StatZ when it lands. Debug is god-mode chosen on
        # purpose, and this function has never overridden it.
        from apps.economy.models import TIER_DEBUG
        from apps.economy.views import ensure_owner
        with self.settings(OWNER_EMAILS=["boss@test.test"], OWNER_USERNAMES=[]):
            u = self.owner_user(username="boss", email="boss@test.test")
            m = membership_for(u)
            m.tier = TIER_DEBUG
            m.save(update_fields=["tier"])
            ensure_owner(User.objects.get(pk=u.pk))
        self.assertEqual(membership_for(u).tier, TIER_DEBUG)
        self.assertTrue(Badge.objects.filter(user=u, key="owner").exists())

    def test_make_owner_grants_it_too(self):
        from django.core.management import call_command
        from io import StringIO
        u = self.owner_user(username="boss", email="boss@test.test")
        membership_for(u)
        out = StringIO()
        call_command("make_owner", "boss@test.test", stdout=out)
        self.assertTrue(Badge.objects.filter(user=u, key="owner").exists())
        self.assertTrue(User.objects.get(pk=u.pk).is_superuser)
        self.assertIn("👑", out.getvalue())

    def test_it_is_idempotent(self):
        from apps.economy.views import ensure_owner
        with self.settings(OWNER_EMAILS=["boss@test.test"], OWNER_USERNAMES=[]):
            u = self.owner_user(username="boss", email="boss@test.test")
            for _ in range(3):
                ensure_owner(User.objects.get(pk=u.pk))
        self.assertEqual(Badge.objects.filter(user=u, key="owner").count(), 1)
