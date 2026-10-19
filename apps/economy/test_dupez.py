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
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase
from rest_framework.test import APIClient

from apps.accounts.models import OAuthIdentity
from apps.economy import dupez
from apps.economy.models import (
    AccountClaim,
    DupeFlag,
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


def _pair(one, two, shared="shared@gmail.com", verified=True):
    """Two accounts the platform can PROVE are one person.

    Since `accounts_user_email_ci_uniq` landed, two accounts CANNOT share an
    address — so a duplicate pair is built the way a real one now arrives:
    different addresses, one sign-in behind both. The provider confirmed that
    address on both, which is what makes it proof rather than a hint; see
    `_unconfirmed_pair` for the case that is not.
    """
    a = member(one, f"{one}@x.com")
    b = member(two, f"{two}@x.com")
    oauth(a, "google", f"g-{one}", shared, verified=verified)
    oauth(b, "soundcloud", f"s-{two}", shared, verified=verified)
    return a, b


def _unconfirmed_pair(one, two, shared="shared@gmail.com"):
    """The same shape as `_pair`, with an address no provider confirmed.

    Strong enough for the owner to look at, and NOT proof: it is a string
    somebody typed into a provider's profile. This is the pair the self-serve
    close used to accept, and the one a member could aim at somebody else.
    """
    return _pair(one, two, shared, verified=False)


def _weak_pair(one, two):
    """Two accounts tied only by a coincidence — one invite between them.

    Weak is the interesting case now: it is never self-serve, and it is not
    the owner's guess either. The account being claimed answers for itself.
    """
    ref = member(f"ref-{one}", f"ref-{one}@x.com")
    a, b = member(one, f"{one}@x.com"), member(two, f"{two}@x.com")
    record_referral(ref, a)
    record_referral(ref, b)
    return a, b


def owner(name="boss"):
    # Per-name, because two accounts can no longer share an address — and a
    # second owner is exactly what test_an_owner_account_cannot_be_deleted_here
    # needs.
    u = User.objects.create_user(name, f"{name}@mcz.net", PW)
    u.is_staff = u.is_superuser = True
    u.save(update_fields=["is_staff", "is_superuser"])
    return u


def oauth(user, provider, uid, email, verified=False):
    return OAuthIdentity.objects.create(user=user, provider=provider,
                                        provider_uid=uid, email=email,
                                        email_verified=verified)


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
        # Set in memory, not saved: the index now refuses a second account on
        # one address, so this pair cannot EXIST (see SameEmailTests).
        # `signals_between` reads the objects it is handed, so the detection
        # itself is still exercised exactly as written — which keeps the branch
        # honest for any row that predates the index.
        a, b = member("a", "one@x.com"), member("b", "two@x.com")
        a.email, b.email = "same@x.com", "SAME@x.com"
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
        self.assertEqual(dupez.duplicate_groups()["groups"], [])

    def test_unrelated_accounts_share_nothing(self):
        self.assertEqual(dupez.signals_between(member("a", "a@x.com"),
                                               member("b", "b@x.com")), [])

    def test_an_empty_email_never_matches_another_empty_email(self):
        # Every OAuth-only account has a blank email. Matching on "" would put
        # the whole platform in one group.
        self.assertEqual(dupez.signals_between(member("a", ""), member("b", "")), [])

    def test_nothing_returns_a_likelihood(self):
        a, b = member("a", "one@x.com"), member("b", "two@x.com")
        a.email = b.email = "same@x.com"          # in memory; see above
        for s in dupez.signals_between(a, b):
            self.assertEqual(set(s), {"key", "detail", "label", "weight", "proof"})


class GroupTests(TestCase):
    def test_three_accounts_chained_by_different_signals_are_one_group(self):
        # a~b by email, b~c by sign-in. The owner gets one group of three, not
        # two overlapping pairs to reconcile by eye.
        a, b, c = member("a", "one@x.com"), member("b", "two@x.com"), member("c", "other@x.com")
        oauth(a, "spotify", "s1", "chain@gmail.com")
        oauth(b, "google", "g1", "chain@gmail.com")     # a~b
        oauth(b, "github", "h1", "corey@gmail.com")
        oauth(c, "microsoft", "m1", "corey@gmail.com")  # b~c
        groups = dupez.duplicate_groups()["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual({x["username"] for x in groups[0]["accounts"]}, {"a", "b", "c"})

    def test_the_oldest_is_suggested_and_only_suggested(self):
        a, b = _pair("a", "b")
        g = dupez.duplicate_groups()["groups"][0]
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
        a, b = _pair("a", "b")
        _pair("c", "d", "someone@else.com")             # somebody else's pair
        r = client_for(a).get("/api/economy/dupez/")
        self.assertFalse(r.data["owner"])
        self.assertEqual(len(r.data["groups"]), 1)
        self.assertEqual({x["username"] for x in r.data["groups"][0]["accounts"]}, {"a", "b"})

    def test_the_owner_sees_every_group(self):
        _pair("a", "b")
        _pair("c", "d", "someone@else.com")
        r = client_for(owner()).get("/api/economy/dupez/")
        self.assertTrue(r.data["owner"])
        self.assertEqual(len(r.data["groups"]), 2)

    def test_a_member_never_sees_an_account_only_weakly_tied_to_them(self):
        # a and b share an email; c is chained in through b only. Showing c to
        # a would be a people-search built by accident.
        a, b = _pair("a", "b")
        c = member("c", "other@x.com")
        oauth(b, "github", "h1", "corey@gmail.com")
        oauth(c, "microsoft", "m1", "corey@gmail.com")
        r = client_for(a).get("/api/economy/dupez/")
        self.assertEqual(r.data["groups"], [])


class SelfServeTests(TestCase):
    """Closing your own duplicate, and keeping what was in it.

    The bar is PROOF, not a hunch: a strong signal means the same person
    authenticated on both accounts. It used to be `account_email` alone, which
    `accounts_user_email_ci_uniq` made unreachable — the database refuses a
    second account on one address — so the gate is the strength now, which
    keeps the path open for the case that still happens and is the one this
    module was written for.

    Weak signals still wait for the owner. Two friends on one invite are two
    people, and an accusation built out of a coincidence is worse than a
    duplicate nobody noticed.
    """

    def test_the_database_refuses_a_second_account_on_one_address(self):
        member("me", "same@x.com")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                member("dupe", "SAME@x.com")

    def test_it_asks_before_it_deletes_and_shows_what_goes(self):
        me, _ = _pair("me", "dupe")
        r = client_for(me).post("/api/economy/dupez/claim/",
                                {"username": "dupe"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.data["needs_confirm"])
        self.assertIn("account", r.data)
        self.assertTrue(User.objects.filter(username="dupe").exists())

    def test_confirmed_it_goes(self):
        me, _ = _pair("me", "dupe")
        r = client_for(me).post("/api/economy/dupez/claim/",
                                {"username": "dupe", "confirm": "DELETE"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username="dupe").exists())

    def test_the_money_comes_with_it(self):
        """It was already theirs. Making them wait on a review to keep it is
        the platform holding a member's own balance hostage to its paperwork."""
        me, dupe = _pair("me", "dupe")
        w = wallet_for(dupe)
        w.money_cents, w.royalties_cents = 900, 350
        w.save()
        r = client_for(me).post("/api/economy/dupez/claim/",
                                {"username": "dupe", "confirm": "DELETE"}, format="json")
        self.assertEqual(r.status_code, 200)
        kept = wallet_for(me)
        self.assertEqual(kept.money_cents, 900)
        self.assertEqual(kept.royalties_cents, 350)
        self.assertFalse(User.objects.filter(username="dupe").exists())

    def test_the_sweep_is_stated_before_the_button(self):
        me, dupe = _pair("me", "dupe")
        w = wallet_for(dupe)
        w.money_cents = 900
        w.save()
        r = client_for(me).post("/api/economy/dupez/claim/",
                                {"username": "dupe"}, format="json")
        self.assertEqual(r.data["sweeps_cents"], 900)
        self.assertIn("9.00", r.data["detail"])

    def test_the_swept_balance_is_written_down(self):
        """A balance that appears with no reason behind it is what LogZ exists
        to stop — and money arriving from a closed account is exactly that."""
        me, dupe = _pair("me", "dupe")
        w = wallet_for(dupe)
        w.money_cents = 900
        w.save()
        client_for(me).post("/api/economy/dupez/claim/",
                            {"username": "dupe", "confirm": "DELETE"}, format="json")
        t = Transaction.objects.get(user=me, kind=Transaction.KIND_TRANSFER)
        self.assertEqual(t.amount_cents, 900)

    def test_a_weak_tie_is_never_self_serve(self):
        """The owner decides, except where the member can prove it."""
        ref = member("ref", "r@x.com")
        a, b = member("a", "a@x.com"), member("b", "b@x.com")
        record_referral(ref, a)
        record_referral(ref, b)
        r = client_for(a).post("/api/economy/dupez/claim/",
                               {"username": "b", "confirm": "DELETE"}, format="json")
        self.assertEqual(r.status_code, 202)          # filed, not deleted
        self.assertTrue(User.objects.filter(username="b").exists())

    def test_a_stranger_cannot_take_an_account_by_asking(self):
        a, b = member("a", "a@x.com"), member("b", "b@x.com")
        r = client_for(a).post("/api/economy/dupez/claim/",
                               {"username": "b", "confirm": "DELETE"}, format="json")
        self.assertEqual(r.status_code, 202)
        self.assertTrue(User.objects.filter(username="b").exists())


class ClaimTests(TestCase):
    def setUp(self):
        # Weak on purpose: a strong pair is provable and self-serves, so it
        # never reaches a queue at all.
        self.me, self.other = _weak_pair("me", "other")
        self.c = client_for(self.me)

    def test_a_weak_tie_files_a_claim_and_deletes_nothing(self):
        r = self.c.post("/api/economy/dupez/claim/",
                        {"username": "other", "confirm": "DELETE", "note": "mine"},
                        format="json")
        self.assertEqual(r.status_code, 202)
        self.assertTrue(User.objects.filter(username="other").exists())
        claim = AccountClaim.objects.get()
        self.assertEqual(claim.status, AccountClaim.OPEN)
        # The evidence is recorded, not recomputed at review time.
        self.assertEqual([s["key"] for s in claim.signals], ["same_referrer"])

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
        # Weak, so it reaches the queue at all — the owner's queue is the
        # backstop for a claim the target never answered, not the first stop.
        self.me, self.other = _weak_pair("me", "other")
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
        self.assertEqual([s["key"] for s in row["signals"]], ["same_referrer"])

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


class AddressTests(TestCase):
    """An address never groups anybody and never deletes anything.

    It is the weakest signal here and weak in both directions, which is the
    whole reason it only ever raises a flag: a studio, a college, a carrier's
    NAT and this app's own referral loop all put different people on one
    address, and a phone puts one person on several.
    """

    def _post(self, path, body, ip="1.2.3.4", client=None):
        return (client or APIClient()).post(path, body, format="json", REMOTE_ADDR=ip)

    def signup(self, name, email, ip="1.2.3.4"):
        r = self._post("/api/auth/register/",
                       {"username": name, "email": email, "password": PW}, ip=ip)
        self.assertEqual(r.status_code, 201, r.content)
        return User.objects.get(username=name)

    def test_a_signup_records_where_it_came_from(self):
        u = self.signup("first", "a@x.com")
        row = u.addresses.get()
        self.assertEqual(row.ip, "1.2.3.4")
        self.assertTrue(row.signup)

    def test_a_second_account_on_one_address_is_flagged_not_blocked(self):
        self.signup("first", "a@x.com")
        second = self.signup("second", "b@x.com")
        # It exists. Nothing was blocked and nothing was deleted.
        self.assertTrue(User.objects.filter(username="second").exists())
        flag = DupeFlag.objects.get()
        self.assertEqual(flag.user, second)
        self.assertEqual(flag.others, ["first"])
        self.assertFalse(flag.strong)

    def test_an_address_alone_never_groups_anybody(self):
        # Two artists at one session are two people. Grouping them would be an
        # accusation built out of a rehearsal room.
        self.signup("first", "a@x.com")
        self.signup("second", "b@x.com")
        self.assertEqual(dupez.duplicate_groups()["groups"], [])

    def _pair_on_one_address(self, ip="7.7.7.7"):
        """Two accounts with a strong tie AND one address.

        Built directly rather than through /register/, because that endpoint
        already refuses a second account on the same email — which is worth
        noticing on its own: a same-email duplicate can only have arrived
        through OAuth or an email edit, never through the signup form.
        """
        a, b = _pair("first", "second")
        for u in (a, b):
            u.addresses.create(ip=ip, signup=True)
        return a, b

    def test_an_address_strengthens_a_group_that_already_exists(self):
        self._pair_on_one_address()
        g = dupez.duplicate_groups()["groups"]
        self.assertEqual(len(g), 1)
        keys = {s["key"] for p in g[0]["pairs"] for s in p["signals"]}
        # `oauth_email`, not `account_email`: `_pair` builds the tie through a
        # shared sign-in, and its own docstring says why — since
        # accounts_user_email_ci_uniq landed, two accounts CANNOT share an
        # account email, so that is no longer a shape a real duplicate can
        # arrive in. The helper was updated for the constraint and this
        # assertion was not.
        self.assertEqual(keys, {"oauth_email", "same_address"})

    def test_a_strong_agreement_tells_the_new_member_the_rule(self):
        a, b = self._pair_on_one_address()
        request = RequestFactory().post("/api/auth/oauth/google/", REMOTE_ADDR="7.7.7.7")
        flag = dupez.flag_signup(b, request)
        self.assertTrue(flag.strong)
        note = b.notifications.filter(item_id="dupez").first()
        self.assertIsNotNone(note)
        # The rule, not an accusation — and read from rulez rather than typed
        # into the notification.
        self.assertIn("one account", note.text.lower())

    def test_an_address_alone_says_nothing_to_the_new_member(self):
        # On a studio wifi the honest reading of "somebody else signed up
        # here" is "somebody else lives here". Messaging them about it is an
        # accusation dressed as a courtesy.
        self.signup("first", "a@x.com")
        second = self.signup("second", "b@x.com")
        self.assertFalse(second.notifications.filter(item_id="dupez").exists())

    def test_a_crowded_address_stops_flagging(self):
        # A college wifi would otherwise raise a flag on every signup forever,
        # the owner would stop reading the queue, and the real entries would go
        # unread with them.
        for i in range(dupez.ADDRESS_CROWD):
            self.signup(f"crowd{i}", f"m{i}@x.com")
        DupeFlag.objects.all().delete()
        self.signup("late", "late@x.com")
        self.assertEqual(DupeFlag.objects.count(), 0)

    def test_different_addresses_raise_nothing(self):
        self.signup("first", "a@x.com", ip="1.1.1.1")
        self.signup("second", "b@x.com", ip="2.2.2.2")
        self.assertEqual(DupeFlag.objects.count(), 0)

    def test_a_shared_address_is_never_flagged_again(self):
        self.signup("first", "a@x.com")
        self.signup("second", "b@x.com")
        flag = DupeFlag.objects.get()
        boss = owner()
        r = client_for(boss).post("/api/economy/dupez/flags/",
                                  {"id": flag.id, "shared": True, "note": "the studio"},
                                  format="json")
        self.assertEqual(r.status_code, 200)
        self.signup("third", "c@x.com")
        self.assertEqual(DupeFlag.objects.filter(status=DupeFlag.OPEN).count(), 0)

    def test_a_broken_address_header_never_costs_a_signup(self):
        # A duplicate check is a hint for a human to read later. It may never
        # be the reason somebody could not create an account.
        r = self._post("/api/auth/register/",
                       {"username": "odd", "email": "odd@x.com", "password": PW},
                       ip="not-an-address")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(User.objects.filter(username="odd").exists())

    def test_the_address_log_is_bounded(self):
        u = self.signup("walker", "w@x.com")
        for i in range(dupez.ADDRESS_KEEP_PER_USER + 6):
            self._post("/api/auth/login/", {"username": "walker", "password": PW},
                       ip=f"9.9.9.{i}")
        # The signup address survives; sightings are capped. An address log
        # that grows forever is a tracking database nobody asked for.
        self.assertLessEqual(u.addresses.filter(signup=False).count(),
                             dupez.ADDRESS_KEEP_PER_USER)
        self.assertTrue(u.addresses.filter(signup=True, ip="1.2.3.4").exists())

    def test_only_signup_addresses_count_as_a_signal(self):
        # A sighting is where somebody happened to be. Two members who once
        # used the same café are not a duplicate.
        a = self.signup("member_a", "a@x.com", ip="1.1.1.1")
        b = self.signup("member_b", "b@x.com", ip="2.2.2.2")
        self._post("/api/auth/login/", {"username": "member_a", "password": PW}, ip="3.3.3.3")
        self._post("/api/auth/login/", {"username": "member_b", "password": PW}, ip="3.3.3.3")
        self.assertEqual(dupez.signals_between(a, b), [])


class FlagQueueTests(TestCase):
    def setUp(self):
        self.boss = owner()
        c = APIClient()
        for name, email in (("first", "a@x.com"), ("second", "b@x.com")):
            c.post("/api/auth/register/",
                   {"username": name, "email": email, "password": PW},
                   format="json", REMOTE_ADDR="5.5.5.5")
        self.flag = DupeFlag.objects.get()

    def test_the_flag_queue_is_owner_only(self):
        member_c = client_for(User.objects.get(username="first"))
        self.assertEqual(member_c.get("/api/economy/dupez/flags/").status_code, 403)
        self.assertEqual(member_c.post("/api/economy/dupez/flags/",
                                       {"id": self.flag.id}, format="json").status_code, 403)

    def test_the_queue_shows_the_account_and_says_it_is_only_an_address(self):
        r = client_for(self.boss).get("/api/economy/dupez/flags/")
        row = r.data["flags"][0]
        self.assertEqual(row["user"], "second")
        self.assertEqual(row["others"], ["first"])
        self.assertFalse(row["strong"])
        self.assertEqual(row["account"]["username"], "second")

    def test_clearing_a_flag_deletes_nothing(self):
        r = client_for(self.boss).post("/api/economy/dupez/flags/",
                                       {"id": self.flag.id, "action": "clear"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(User.objects.filter(username="second").exists())
        self.flag.refresh_from_db()
        self.assertEqual(self.flag.status, DupeFlag.CLEARED)


class VerifyTests(TestCase):
    """A weak claim is answered by the account it is about."""

    def setUp(self):
        self.me, self.them = _weak_pair("me", "them")
        client_for(self.me).post("/api/economy/dupez/claim/",
                                 {"username": "them"}, format="json")
        self.claim = AccountClaim.objects.get()
        self.c = client_for(self.them)

    def test_the_target_is_told_there_is_a_question_for_them(self):
        note = self.them.notifications.filter(item_id="dupez").first()
        self.assertIsNotNone(note)
        self.assertIn("me", note.text)

    def test_they_see_what_agreeing_would_destroy(self):
        w = wallet_for(self.them)
        w.money_cents = 700
        w.save()
        r = self.c.get("/api/economy/dupez/verify/")
        row = r.data["claims"][0]
        self.assertEqual(row["claimant"], "me")
        self.assertEqual(row["sweeps_cents"], 700)
        self.assertIn("posts", row["deletes"])

    def test_saying_no_refuses_it_and_touches_nothing(self):
        r = self.c.post("/api/economy/dupez/verify/",
                        {"claim": self.claim.id, "agree": False}, format="json")
        self.assertEqual(r.status_code, 200)
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, AccountClaim.REFUSED)
        self.assertTrue(User.objects.filter(username="them").exists())

    def test_agreeing_still_asks_before_it_deletes(self):
        r = self.c.post("/api/economy/dupez/verify/",
                        {"claim": self.claim.id, "agree": True}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.data["needs_confirm"])
        self.assertTrue(User.objects.filter(username="them").exists())

    def test_confirmed_it_closes_and_the_money_goes_to_the_claimant(self):
        w = wallet_for(self.them)
        w.money_cents = 700
        w.save()
        r = self.c.post("/api/economy/dupez/verify/",
                        {"claim": self.claim.id, "agree": True, "confirm": "DELETE"},
                        format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username="them").exists())
        self.assertEqual(wallet_for(self.me).money_cents, 700)

    def test_only_the_target_may_answer(self):
        """The claimant answering their own claim is the whole attack."""
        r = client_for(self.me).post("/api/economy/dupez/verify/",
                                     {"claim": self.claim.id, "agree": True,
                                      "confirm": "DELETE"}, format="json")
        self.assertEqual(r.status_code, 404)
        self.assertTrue(User.objects.filter(username="them").exists())

    def test_a_stranger_may_not_answer_it_either(self):
        outsider = member("outsider", "o@x.com")
        r = client_for(outsider).post("/api/economy/dupez/verify/",
                                      {"claim": self.claim.id, "agree": True,
                                       "confirm": "DELETE"}, format="json")
        self.assertEqual(r.status_code, 404)
        self.assertTrue(User.objects.filter(username="them").exists())

    def test_an_already_answered_claim_cannot_be_answered_twice(self):
        self.c.post("/api/economy/dupez/verify/",
                    {"claim": self.claim.id, "agree": False}, format="json")
        r = self.c.post("/api/economy/dupez/verify/",
                        {"claim": self.claim.id, "agree": True, "confirm": "DELETE"},
                        format="json")
        self.assertEqual(r.status_code, 404)
        self.assertTrue(User.objects.filter(username="them").exists())


class ProofGateTests(TestCase):
    """Closing an account WITHOUT signing in to it takes proof, not a hint.

    Corey's bar was better than 90% certainty. There is no honest number to put
    on that (nothing to calibrate one against, and the rule above forbids a
    score behind a deletion), so the bar is evidence: the provider confirmed the
    same address on both accounts. These pin what falls on each side of it.
    """

    def _claim(self, who, target, **extra):
        return client_for(who).post("/api/economy/dupez/claim/",
                                    {"username": target, "confirm": "DELETE", **extra},
                                    format="json")

    def test_an_address_no_provider_confirmed_is_strong_but_not_proof(self):
        a, b = _unconfirmed_pair("a", "b")
        sig = dupez.signals_between(a, b)
        self.assertTrue(dupez.has_strong(sig))
        self.assertFalse(dupez.has_proof(sig))

    def test_confirmed_on_only_one_side_is_not_proof(self):
        a, b = member("a", "a@x.com"), member("b", "b@x.com")
        oauth(a, "google", "g1", "same@gmail.com", verified=True)
        oauth(b, "spotify", "s1", "same@gmail.com", verified=False)
        self.assertFalse(dupez.has_proof(dupez.signals_between(a, b)))

    def test_confirmed_on_both_sides_is_proof(self):
        a, b = _pair("a", "b")
        self.assertTrue(dupez.has_proof(dupez.signals_between(a, b)))

    def test_a_weak_signal_is_never_proof(self):
        a, b = _weak_pair("a", "b")
        self.assertFalse(dupez.has_proof(dupez.signals_between(a, b)))

    def test_the_label_never_reads_as_proof_when_it_is_not(self):
        # Owner and member both read these words; the same sentence must not
        # appear on the two cases.
        a, b = _unconfirmed_pair("a", "b")
        c, d = _pair("c", "d", "other@gmail.com")
        weak = dupez.signals_between(a, b)[0]["label"]
        sure = dupez.signals_between(c, d)[0]["label"]
        self.assertNotEqual(weak, sure)
        self.assertIn("did not confirm", weak)
        self.assertIn("confirmed by the provider", sure)

    def test_an_unconfirmed_pair_cannot_be_closed_from_the_main_account(self):
        a, b = _unconfirmed_pair("me", "dupe")
        r = self._claim(a, "dupe")
        self.assertEqual(r.status_code, 202)                    # filed, not deleted
        self.assertTrue(User.objects.filter(username="dupe").exists())
        self.assertEqual(AccountClaim.objects.get().status, AccountClaim.OPEN)

    def test_a_claim_says_why_and_offers_the_way_through(self):
        a, b = _unconfirmed_pair("me", "dupe")
        r = self._claim(a, "dupe")
        self.assertEqual(r.data["confirm_by_sign_in"], "dupe")
        self.assertIn("provider never confirmed", r.data["detail"])
        self.assertIn("switch straight back", r.data["detail"])

    def test_one_side_confirmed_still_has_to_sign_in(self):
        a, b = member("me", "me@x.com"), member("dupe", "dupe@x.com")
        oauth(a, "google", "g1", "same@gmail.com", verified=True)
        oauth(b, "spotify", "s1", "same@gmail.com", verified=False)
        self.assertEqual(self._claim(a, "dupe").status_code, 202)
        self.assertTrue(User.objects.filter(username="dupe").exists())

    def test_the_attack_that_motivated_this_is_a_claim_and_nothing_more(self):
        # A victim with a confirmed Google address. An attacker links a provider
        # that returns whatever address they typed, and asks to close the
        # victim "as their own other account". It used to delete the victim,
        # sweep their money to the attacker, and show the attacker the victim's
        # email and balance first.
        victim = member("victim", "victim@x.com")
        attacker = member("attacker", "attacker@x.com")
        oauth(victim, "google", "g-victim", "victim@gmail.com", verified=True)
        oauth(attacker, "spotify", "s-attacker", "victim@gmail.com", verified=False)
        w = wallet_for(victim)
        w.money_cents = 5000
        w.save()
        r = self._claim(attacker, "victim")
        self.assertEqual(r.status_code, 202)
        self.assertTrue(User.objects.filter(username="victim").exists())
        self.assertEqual(wallet_for(victim).money_cents, 5000)
        self.assertEqual(wallet_for(attacker).money_cents, 0)

    def test_proof_still_closes_it_and_still_asks_first(self):
        a, b = _pair("me", "dupe")
        r = client_for(a).post("/api/economy/dupez/claim/", {"username": "dupe"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self._claim(a, "dupe").status_code, 200)
        self.assertFalse(User.objects.filter(username="dupe").exists())

    def test_the_owner_can_still_decide_an_unconfirmed_claim(self):
        a, b = _unconfirmed_pair("me", "dupe")
        self._claim(a, "dupe")
        claim = AccountClaim.objects.get()
        r = client_for(owner()).post("/api/economy/dupez/review/",
                                     {"id": claim.id, "action": "approve"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username="dupe").exists())


class MemberViewRedactionTests(TestCase):
    """A member sees what they have PROVED is theirs, and a handle for the rest.

    The full card holds the email and the wallet. Showing it for an address no
    provider confirmed would let a member read a stranger's email and balance by
    typing the address into a profile.
    """

    def test_an_unconfirmed_account_is_a_handle_and_nothing_else(self):
        a, b = _unconfirmed_pair("a", "b")
        w = wallet_for(b)
        w.money_cents = 700
        w.save()
        r = client_for(a).get("/api/economy/dupez/")
        (g,) = r.data["groups"]
        other = next(x for x in g["accounts"] if x["username"] == "b")
        self.assertEqual(other, {"username": "b", "redacted": True, "proof": False})
        self.assertNotIn("email", other)
        self.assertNotIn("money_cents", other)

    def test_a_proven_account_shows_in_full(self):
        a, b = _pair("a", "b")
        r = client_for(a).get("/api/economy/dupez/")
        (g,) = r.data["groups"]
        other = next(x for x in g["accounts"] if x["username"] == "b")
        self.assertTrue(other["proof"])
        self.assertEqual(other["email"], "b@x.com")

    def test_the_members_own_card_is_always_in_full(self):
        a, b = _unconfirmed_pair("a", "b")
        r = client_for(a).get("/api/economy/dupez/")
        (g,) = r.data["groups"]
        mine = next(x for x in g["accounts"] if x["username"] == "a")
        self.assertEqual(mine["email"], "a@x.com")

    def test_pairs_between_two_other_accounts_are_not_served(self):
        a, b = _pair("a", "b")
        c = member("c", "c@x.com")
        oauth(c, "github", "h1", "shared@gmail.com", verified=True)
        r = client_for(a).get("/api/economy/dupez/")
        for g in r.data["groups"]:
            for p in g["pairs"]:
                self.assertIn("a", (p["a"], p["b"]))

    def test_the_owner_still_sees_every_card_in_full(self):
        _unconfirmed_pair("a", "b")
        r = client_for(owner()).get("/api/economy/dupez/")
        (g,) = r.data["groups"]
        self.assertTrue(all("email" in x for x in g["accounts"]))

    def test_the_proof_rule_is_served_and_not_retyped(self):
        a, b = _pair("a", "b")
        r = client_for(a).get("/api/economy/dupez/")
        self.assertEqual(r.data["proof_rule"], dupez.PROOF_RULE)
        self.assertIn("switch straight back", r.data["proof_rule"])


class SignInToConfirmTests(TestCase):
    """The route that replaces self-serve when there is no proof.

    The member files the claim from the main account, signs in to the other one
    (their own password — a better proof than any address) and confirms there.
    """

    def test_the_whole_route_ends_with_the_cash_on_the_main_account(self):
        main, dupe = _unconfirmed_pair("main", "dupe")
        w = wallet_for(dupe)
        w.money_cents = 900
        w.save()
        r = client_for(main).post("/api/economy/dupez/claim/",
                                  {"username": "dupe"}, format="json")
        self.assertEqual(r.status_code, 202)
        # Signed in to the other account now.
        seen = client_for(dupe).get("/api/economy/dupez/verify/")
        (claim,) = seen.data["claims"]
        self.assertEqual(claim["claimant"], "main")
        self.assertEqual(claim["sweeps_cents"], 900)
        r = client_for(dupe).post("/api/economy/dupez/verify/",
                                  {"claim": claim["id"], "agree": True, "confirm": "DELETE"},
                                  format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["kept"], "main")
        self.assertFalse(User.objects.filter(username="dupe").exists())
        self.assertEqual(wallet_for(main).money_cents, 900)

    def test_nobody_but_the_account_itself_can_confirm_it(self):
        main, dupe = _unconfirmed_pair("main", "dupe")
        client_for(main).post("/api/economy/dupez/claim/", {"username": "dupe"}, format="json")
        claim = AccountClaim.objects.get()
        r = client_for(main).post("/api/economy/dupez/verify/",
                                  {"claim": claim.id, "agree": True, "confirm": "DELETE"},
                                  format="json")
        self.assertEqual(r.status_code, 404)
        self.assertTrue(User.objects.filter(username="dupe").exists())


class ProviderConfirmationIsRecordedTests(TestCase):
    """`email_verified` has to be stored, or `has_proof` could never be true."""

    def _info(self, **kw):
        base = {"provider": "google", "uid": "g-1", "email": "me@gmail.com",
                "email_verified": True, "name": "Me"}
        base.update(kw)
        return base

    def test_a_confirmed_address_is_stored_as_confirmed(self):
        from apps.accounts.views import _user_from_oauth
        u = _user_from_oauth(self._info())
        self.assertTrue(OAuthIdentity.objects.get(user=u).email_verified)

    def test_an_unconfirmed_address_is_stored_as_unconfirmed(self):
        from apps.accounts.views import _user_from_oauth
        u = _user_from_oauth(self._info(provider="spotify", uid="s-1", email_verified=False))
        self.assertFalse(OAuthIdentity.objects.get(user=u).email_verified)

    def test_no_address_is_never_confirmed_whatever_the_flag_says(self):
        from apps.accounts.views import _user_from_oauth
        u = _user_from_oauth(self._info(email="", email_verified=True))
        self.assertFalse(OAuthIdentity.objects.get(user=u).email_verified)

    def test_a_later_confirmed_sign_in_upgrades_an_old_row(self):
        from apps.accounts.views import _user_from_oauth
        u = member("old", "old@x.com")
        OAuthIdentity.objects.create(user=u, provider="google", provider_uid="g-old",
                                     email="me@gmail.com")            # before the column
        _user_from_oauth(self._info(uid="g-old"))
        self.assertTrue(OAuthIdentity.objects.get(provider_uid="g-old").email_verified)

    def test_a_later_unconfirmed_sign_in_never_takes_confirmation_back(self):
        from apps.accounts.views import _user_from_oauth
        u = member("old", "old@x.com")
        OAuthIdentity.objects.create(user=u, provider="google", provider_uid="g-old",
                                     email="me@gmail.com", email_verified=True)
        _user_from_oauth(self._info(uid="g-old", email="other@gmail.com", email_verified=False))
        row = OAuthIdentity.objects.get(provider_uid="g-old")
        self.assertTrue(row.email_verified)
        self.assertEqual(row.email, "me@gmail.com")

    def test_linking_stores_what_the_provider_said(self):
        from apps.accounts.views import _pending_token
        u = member("linker", "linker@x.com")
        for provider, flag in (("google", True), ("spotify", False)):
            info = self._info(provider=provider, uid=f"{provider}-1", email_verified=flag)
            r = client_for(u).post(f"/api/auth/oauth/{provider}/link/",
                                   {"pending": _pending_token(info)}, format="json")
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual(OAuthIdentity.objects.get(provider=provider).email_verified, flag)
