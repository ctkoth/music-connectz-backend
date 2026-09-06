"""DupeZ — one person, one account, and the only safe way to enforce it.

The rule under test is `rulez.one_account`. What is actually being pinned is
the narrowness of its enforcement, because the enforcement is a deletion:

* nothing infers a duplicate and acts on it,
* a member may only ever ask about their OWN other account,
* the owner decides, except where the member can prove it themselves,
* and no delete destroys money.

That last one is the reason half this file exists. `AccountDeleteView` has
always wiped a wallet holding real cash without a word, which is survivable
when it is your own account and your own decision, and is not survivable when
somebody else pressed the button.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import OAuthIdentity
from apps.economy import dupez
from apps.economy.models import (
    AccountClaim,
    Transaction,
    membership_for,
    record_referral,
    wallet_for,
)
from apps.economy.rulez import RULES_BY_KEY, rule

User = get_user_model()
PW = "hunter2hunter2"


def member(name, email=""):
    return User.objects.create_user(name, email, PW)


def owner(name="boss"):
    u = User.objects.create_user(name, "boss@mcz.net", PW)
    u.is_staff = u.is_superuser = True
    u.save(update_fields=["is_staff", "is_superuser"])
    return u


def oauth(user, provider, uid, email):
    return OAuthIdentity.objects.create(user=user, provider=provider,
                                        provider_uid=uid, email=email)


def client_for(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


class TheRuleIsWrittenDownTests(TestCase):
    def test_the_rule_exists_and_says_what_happens(self):
        r = rule("one_account")
        self.assertIsNotNone(r)
        # A rule with no consequence named is a preference, and members work
        # out the difference fast.
        self.assertTrue(r["what_happens"])
        self.assertTrue(r["why"])

    def test_the_rule_names_the_code_that_enforces_it(self):
        # So a rule cannot quietly become a wish: grep the key, find both ends.
        self.assertEqual(RULES_BY_KEY["one_account"]["enforced_by"], "apps/economy/dupez.py")

    def test_the_rules_are_readable_logged_out(self):
        # The one about how many accounts a person gets is needed on the signup
        # form, which is the one screen where nobody is signed in yet.
        r = APIClient().get("/api/economy/rulez/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any(x["key"] == "one_account" for x in r.data["rules"]))

    def test_dupez_serves_the_rule_rather_than_the_screen_retyping_it(self):
        r = client_for(member("solo", "s@x.com")).get("/api/economy/dupez/")
        self.assertEqual(r.data["rule"]["key"], "one_account")


class SignalTests(TestCase):
    """Reasons, never a score. A number nobody can check behind an action
    nobody can undo is the substance rule's exact failure case."""

    def test_the_same_account_email_is_a_strong_signal(self):
        a, b = member("a", "same@x.com"), member("b", "SAME@x.com")
        sig = dupez.signals_between(a, b)
        self.assertEqual([s["key"] for s in sig], ["account_email"])
        self.assertTrue(dupez.has_strong(sig))

    def test_different_emails_with_the_same_sign_in_is_the_case_that_matters(self):
        # Corey's three: different account emails, one Google identity. The
        # command that shipped before this could not find these — it queried
        # `oauthidentity__email` and the reverse name is `oauth_identities`,
        # so the branch raised FieldError as soon as one existed.
        a, b = member("a", "one@x.com"), member("b", "two@x.com")
        oauth(a, "google", "g1", "corey@gmail.com")
        oauth(b, "soundcloud", "s1", "corey@gmail.com")
        sig = dupez.signals_between(a, b)
        self.assertEqual([s["key"] for s in sig], ["oauth_email"])
        self.assertTrue(dupez.has_strong(sig))

    def test_a_shared_referrer_is_weak_and_never_groups_anybody(self):
        # Two friends who joined on the same invite are two people. Grouping
        # them would be an accusation built out of a coincidence.
        ref = member("ref", "r@x.com")
        a, b = member("a", "a@x.com"), member("b", "b@x.com")
        record_referral(ref, a)
        record_referral(ref, b)
        sig = dupez.signals_between(a, b)
        self.assertEqual([s["key"] for s in sig], ["same_referrer"])
        self.assertFalse(dupez.has_strong(sig))
        self.assertEqual(dupez.duplicate_groups(), [])

    def test_unrelated_accounts_share_nothing(self):
        self.assertEqual(dupez.signals_between(member("a", "a@x.com"),
                                               member("b", "b@x.com")), [])

    def test_an_empty_email_never_matches_another_empty_email(self):
        # Every OAuth-only account has a blank email. Matching on "" would put
        # the whole platform in one group.
        self.assertEqual(dupez.signals_between(member("a", ""), member("b", "")), [])

    def test_nothing_returns_a_likelihood(self):
        a, b = member("a", "same@x.com"), member("b", "same@x.com")
        for s in dupez.signals_between(a, b):
            self.assertEqual(set(s), {"key", "detail", "label", "weight"})


class GroupTests(TestCase):
    def test_three_accounts_chained_by_different_signals_are_one_group(self):
        # a~b by email, b~c by sign-in. The owner gets one group of three, not
        # two overlapping pairs to reconcile by eye.
        a, b, c = member("a", "same@x.com"), member("b", "same@x.com"), member("c", "other@x.com")
        oauth(b, "google", "g1", "corey@gmail.com")
        oauth(c, "github", "h1", "corey@gmail.com")
        groups = dupez.duplicate_groups()
        self.assertEqual(len(groups), 1)
        self.assertEqual({x["username"] for x in groups[0]["accounts"]}, {"a", "b", "c"})

    def test_the_oldest_is_suggested_and_only_suggested(self):
        a, b = member("a", "same@x.com"), member("b", "same@x.com")
        g = dupez.duplicate_groups()[0]
        self.assertEqual(g["suggested_keep"], "a")
        # It is a default in a form. Nothing in this module acts on it.
        self.assertIn("accounts", g)

    def test_a_card_carries_everything_a_delete_would_destroy(self):
        u = member("a", "a@x.com")
        w = wallet_for(u)
        w.money_cents, w.spinaz = 500, 300
        w.save()
        card = dupez.account_card(u)
        for k in ("money_cents", "royalties_cents", "posts", "uploads",
                  "journal_entries", "spinaz", "energy", "tier", "joined"):
            self.assertIn(k, card)
        self.assertEqual(card["money_cents"], 500)


class MemberVisibilityTests(TestCase):
    def test_a_member_sees_only_their_own_group(self):
        a, b = member("a", "same@x.com"), member("b", "same@x.com")
        member("c", "c@x.com"), member("d", "c@x.com")  # somebody else's pair
        r = client_for(a).get("/api/economy/dupez/")
        self.assertFalse(r.data["owner"])
        self.assertEqual(len(r.data["groups"]), 1)
        self.assertEqual({x["username"] for x in r.data["groups"][0]["accounts"]}, {"a", "b"})

    def test_the_owner_sees_every_group(self):
        member("a", "same@x.com"), member("b", "same@x.com")
        member("c", "c@x.com"), member("d", "c@x.com")
        r = client_for(owner()).get("/api/economy/dupez/")
        self.assertTrue(r.data["owner"])
        self.assertEqual(len(r.data["groups"]), 2)

    def test_a_member_never_sees_an_account_only_weakly_tied_to_them(self):
        # a and b share an email; c is chained in through b only. Showing c to
        # a would be a people-search built by accident.
        a, b = member("a", "same@x.com"), member("b", "same@x.com")
        c = member("c", "other@x.com")
        oauth(b, "google", "g1", "corey@gmail.com")
        oauth(c, "github", "h1", "corey@gmail.com")
        r = client_for(a).get("/api/economy/dupez/")
        self.assertEqual(r.data["groups"], [])


class SameEmailTests(TestCase):
    """Your own mess, your own email, your own tidy-up."""

    def setUp(self):
        self.me = member("me", "same@x.com")
        self.dupe = member("dupe", "same@x.com")
        self.c = client_for(self.me)

    def test_it_asks_before_it_deletes_and_shows_what_goes(self):
        r = self.c.post("/api/economy/dupez/claim/", {"username": "dupe"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.data["needs_confirm"])
        self.assertEqual(r.data["account"]["username"], "dupe")
        self.assertTrue(User.objects.filter(username="dupe").exists())

    def test_confirmed_it_goes(self):
        r = self.c.post("/api/economy/dupez/claim/",
                        {"username": "dupe", "confirm": "DELETE"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username="dupe").exists())
        self.assertEqual(AccountClaim.objects.count(), 0)

    def test_money_turns_it_into_a_review_instead(self):
        # The one thing a member may not do to themselves by accident.
        w = wallet_for(self.dupe)
        w.money_cents = 1250
        w.save()
        r = self.c.post("/api/economy/dupez/claim/",
                        {"username": "dupe", "confirm": "DELETE"}, format="json")
        self.assertEqual(r.status_code, 202)
        self.assertIn("12.50", r.data["detail"])
        self.assertTrue(User.objects.filter(username="dupe").exists())
        self.assertEqual(AccountClaim.objects.get().status, AccountClaim.OPEN)


class ClaimTests(TestCase):
    def setUp(self):
        self.me = member("me", "one@x.com")
        self.other = member("other", "two@x.com")
        oauth(self.me, "google", "g1", "corey@gmail.com")
        oauth(self.other, "soundcloud", "s1", "corey@gmail.com")
        self.c = client_for(self.me)

    def test_different_emails_file_a_claim_and_delete_nothing(self):
        r = self.c.post("/api/economy/dupez/claim/",
                        {"username": "other", "confirm": "DELETE", "note": "mine"},
                        format="json")
        self.assertEqual(r.status_code, 202)
        self.assertTrue(User.objects.filter(username="other").exists())
        claim = AccountClaim.objects.get()
        self.assertEqual(claim.status, AccountClaim.OPEN)
        # The evidence is recorded, not recomputed at review time.
        self.assertEqual([s["key"] for s in claim.signals], ["oauth_email"])

    def test_refiling_edits_the_one_claim_rather_than_queueing_a_second(self):
        for note in ("first", "second"):
            self.c.post("/api/economy/dupez/claim/",
                        {"username": "other", "note": note}, format="json")
        self.assertEqual(AccountClaim.objects.count(), 1)
        self.assertEqual(AccountClaim.objects.get().note, "second")

    def test_you_cannot_claim_yourself(self):
        r = self.c.post("/api/economy/dupez/claim/", {"username": "me"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_you_cannot_claim_the_owner(self):
        # A claim that can delete the reviewer is a way to take the platform's
        # admin down with a form.
        owner("boss")
        r = self.c.post("/api/economy/dupez/claim/", {"username": "boss"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_a_claim_on_a_stranger_is_still_only_a_claim(self):
        # Nothing stops somebody naming an account that is not theirs. What
        # stops it mattering is that the answer is a review, never a delete.
        stranger = member("stranger", "nope@x.com")
        r = self.c.post("/api/economy/dupez/claim/",
                        {"username": "stranger", "confirm": "DELETE"}, format="json")
        self.assertEqual(r.status_code, 202)
        self.assertTrue(User.objects.filter(pk=stranger.pk).exists())
        self.assertEqual(AccountClaim.objects.get().signals, [])


class ReviewTests(TestCase):
    def setUp(self):
        self.boss = owner()
        self.me = member("me", "one@x.com")
        self.other = member("other", "two@x.com")
        oauth(self.me, "google", "g1", "c@gmail.com")
        oauth(self.other, "github", "h1", "c@gmail.com")
        client_for(self.me).post("/api/economy/dupez/claim/",
                                 {"username": "other"}, format="json")
        self.claim = AccountClaim.objects.get()
        self.c = client_for(self.boss)

    def test_the_queue_is_owner_only(self):
        self.assertEqual(client_for(self.me).get("/api/economy/dupez/review/").status_code, 403)
        self.assertEqual(client_for(self.me).post(
            "/api/economy/dupez/review/", {"id": self.claim.id, "action": "approve"},
            format="json").status_code, 403)

    def test_the_queue_shows_both_accounts_in_full(self):
        r = self.c.get("/api/economy/dupez/review/")
        row = r.data["claims"][0]
        self.assertEqual(row["target_account"]["username"], "other")
        self.assertEqual(row["claimant_account"]["username"], "me")
        self.assertEqual([s["key"] for s in row["signals"]], ["oauth_email"])

    def test_approve_deletes_the_target(self):
        r = self.c.post("/api/economy/dupez/review/",
                        {"id": self.claim.id, "action": "approve"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username="other").exists())
        self.assertTrue(User.objects.filter(username="me").exists())

    def test_refuse_keeps_the_account_and_says_why_in_writing(self):
        r = self.c.post("/api/economy/dupez/review/",
                        {"id": self.claim.id, "action": "refuse", "note": "not yours"},
                        format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(User.objects.filter(username="other").exists())
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, AccountClaim.REFUSED)
        self.assertEqual(self.claim.resolved_note, "not yours")
        # Told either way. A claim that goes quiet is indistinguishable from
        # one nobody read.
        self.assertTrue(self.me.notifications.filter(item_id="dupez").exists())

    def test_an_unknown_action_changes_nothing(self):
        r = self.c.post("/api/economy/dupez/review/",
                        {"id": self.claim.id, "action": "yolo"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, AccountClaim.OPEN)


class OwnerOverrideTests(TestCase):
    def setUp(self):
        self.boss = owner()
        self.keep = member("keeper", "one@x.com")
        self.dupe = member("dupe", "two@x.com")
        self.c = client_for(self.boss)

    def test_it_is_owner_only(self):
        r = client_for(self.keep).post("/api/economy/dupez/delete/",
                                       {"username": "dupe", "confirm": "DELETE"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(User.objects.filter(username="dupe").exists())

    def test_it_asks_first_and_shows_the_account(self):
        r = self.c.post("/api/economy/dupez/delete/", {"username": "dupe"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data["account"]["username"], "dupe")
        self.assertTrue(User.objects.filter(username="dupe").exists())

    def test_confirmed_with_no_balance_it_goes(self):
        r = self.c.post("/api/economy/dupez/delete/",
                        {"username": "dupe", "confirm": "DELETE"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username="dupe").exists())

    def test_it_refuses_to_destroy_money_and_names_the_amount(self):
        w = wallet_for(self.dupe)
        w.money_cents, w.royalties_cents = 900, 350
        w.save()
        r = self.c.post("/api/economy/dupez/delete/",
                        {"username": "dupe", "confirm": "DELETE"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("12.50", r.data["detail"])
        self.assertTrue(User.objects.filter(username="dupe").exists())

    def test_naming_a_keep_account_sweeps_the_cash_and_leaves_a_line(self):
        w = wallet_for(self.dupe)
        w.money_cents, w.royalties_cents = 900, 350
        w.save()
        r = self.c.post("/api/economy/dupez/delete/",
                        {"username": "dupe", "keep": "keeper", "confirm": "DELETE"},
                        format="json")
        self.assertEqual(r.status_code, 200)
        kept = wallet_for(self.keep)
        self.assertEqual(kept.money_cents, 900)
        self.assertEqual(kept.royalties_cents, 350)
        self.assertFalse(User.objects.filter(username="dupe").exists())
        # A balance that appears with no reason behind it is the thing LogZ
        # exists to stop.
        t = Transaction.objects.get(user=self.keep, kind=Transaction.KIND_TRANSFER)
        self.assertEqual(t.amount_cents, 900)
        self.assertIn("dupe", t.note)

    def test_game_resources_die_with_the_duplicate(self):
        # Sweeping these would turn the tidy-up into the payout: three
        # accounts, three lots of onboarding, merged into one.
        w = wallet_for(self.dupe)
        w.spinaz, w.energy, w.promptz = 500, 80, 20
        w.save()
        self.c.post("/api/economy/dupez/delete/",
                    {"username": "dupe", "keep": "keeper", "confirm": "DELETE"},
                    format="json")
        kept = wallet_for(self.keep)
        self.assertEqual((kept.spinaz, kept.energy, kept.promptz), (0, 0, 0))

    def test_an_owner_account_cannot_be_deleted_here(self):
        second = owner("boss2")
        r = self.c.post("/api/economy/dupez/delete/",
                        {"username": second.username, "confirm": "DELETE"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(User.objects.filter(pk=second.pk).exists())

    def test_the_owner_cannot_delete_the_account_they_are_signed_in_to(self):
        r = self.c.post("/api/economy/dupez/delete/",
                        {"username": self.boss.username, "confirm": "DELETE"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_an_unknown_keep_account_stops_the_whole_thing(self):
        r = self.c.post("/api/economy/dupez/delete/",
                        {"username": "dupe", "keep": "ghost", "confirm": "DELETE"},
                        format="json")
        self.assertEqual(r.status_code, 404)
        self.assertTrue(User.objects.filter(username="dupe").exists())
