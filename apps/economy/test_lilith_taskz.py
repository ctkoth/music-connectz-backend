"""Lilith's rewards, and the caps that are the only thing between them and a
faucet.

Nothing here tests that a task can be created — that part is a to-do list and
it either works or the screen is empty. What is tested is every place this
feature could quietly become a way to print currency, because that failure has
no error message: the wallet just grows.

The five that matter:

  1. A self-made task pays a token coin, three a day, and the fourth pays XP
     only. (`SELF_TASK_DAILY_CAP`)
  2. A task pointing at a real action pays NO coin here — the action already
     paid, and paying again is paying twice for one piece of work.
  3. An automation pays nothing at all, ever.
  4. A routine milestone pays once for life, not once per rebuild.
  5. Helping pays on the NEWCOMER'S graduation, with somebody else, and DupeZ
     can veto it. All three refusals are pinned, because each is a different
     way of paying yourself.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from . import lilith_taskz as L
from apps.accounts.models import OAuthIdentity
from .models import (LilithPayout, LilithRoutine, LilithSponsorship, LilithTask,
                     wallet_for)

User = get_user_model()
PW = "pw12345!"


def member(name):
    return User.objects.create_user(name, f"{name}@mcz.test", PW)


def link_accounts(a, b, email="shared@mcz.test"):
    """Give two accounts the same linked sign-in — the STRONG DupeZ signal that
    is actually reachable. The same account email is not: `accounts_user_email_
    ci_uniq` forbids it at the database, so the only cross-email duplicate that
    can exist is this one, which is also the case CLAUDE.md says Corey has."""
    for n, u in enumerate((a, b)):
        OAuthIdentity.objects.create(user=u, provider="google",
                                     provider_uid=f"uid-{u.pk}-{n}", email=email)


def task(user, **kw):
    kw.setdefault("title", "a thing")
    kw.setdefault("source", "self")
    return LilithTask.objects.create(user=user, **kw)


class SelfTaskCapTests(TestCase):
    """The cap is load-bearing: without it, typing is a wage."""

    def setUp(self):
        self.u = member("capper")

    def test_a_self_task_pays_one_coin(self):
        out = L.complete(task(self.u))
        self.assertEqual(out["spinaz"], L.SELF_TASK_SPINAZ)
        self.assertEqual(wallet_for(self.u).spinaz, L.SELF_TASK_SPINAZ)

    def test_the_fourth_one_today_pays_no_coin_and_says_so(self):
        for _ in range(L.SELF_TASK_DAILY_CAP):
            L.complete(task(self.u))
        out = L.complete(task(self.u))
        self.assertEqual(out["spinaz"], 0)
        # The XP still lands — the member did the work, the coin is what is
        # rationed. And they are TOLD, rather than left to notice.
        self.assertTrue(out["xp"])
        self.assertEqual(out["note"], L.VOICE["capped"])
        self.assertEqual(wallet_for(self.u).spinaz, L.SELF_TASK_DAILY_CAP)

    def test_no_energy_on_a_self_task(self):
        """Two currencies for one unverified checkbox is two faucets."""
        self.assertEqual(L.SELF_TASK_ENERGY, 0)
        self.assertEqual(L.complete(task(self.u))["energy"], 0)

    def test_ticking_twice_pays_once(self):
        t = task(self.u)
        L.complete(t)
        again = L.complete(t)
        self.assertTrue(again["already"])
        self.assertEqual(wallet_for(self.u).spinaz, L.SELF_TASK_SPINAZ)

    def test_a_platform_task_pays_no_coin_here(self):
        """The action it points at has its own economy and already paid."""
        out = L.complete(task(self.u, source="platform", app_key="singz", target="singz:coach"))
        self.assertEqual(out["spinaz"], 0)
        self.assertTrue(out["xp"])

    def test_an_automation_pays_nothing_at_all(self):
        out = L.complete(task(self.u, source="auto", kind="auto"))
        self.assertEqual(out["spinaz"], 0)
        self.assertEqual(out["energy"], 0)
        self.assertEqual(out["xp"], 0)
        self.assertEqual(wallet_for(self.u).spinaz, 0)


class RoutineTests(TestCase):
    def setUp(self):
        self.u = member("streaker")
        self.r = LilithRoutine.objects.create(user=self.u, title="warm up")

    def _run_to(self, days):
        """Walk a streak forward without waiting `days` real days."""
        for n in range(days):
            self.r.last_done = timezone.localdate() - timedelta(days=1) if n else None
            self.r.streak = n
            self.r.save(update_fields=["last_done", "streak"])
            out = L.keep_routine(self.r)
        return out

    def test_keeping_it_twice_in_a_day_does_not_advance(self):
        L.keep_routine(self.r)
        out = L.keep_routine(self.r)
        self.assertTrue(out["already"])
        self.assertEqual(self.r.streak, 1)

    def test_seven_days_pays_the_milestone(self):
        out = self._run_to(7)
        self.assertEqual(out["milestone"]["spinaz"], L.ROUTINE_MILESTONES[7])
        self.assertEqual(out["milestone"]["energy"], L.ROUTINE_MILESTONE_ENERGY[7])
        self.assertEqual(wallet_for(self.u).spinaz, L.ROUTINE_MILESTONES[7])

    def test_a_milestone_pays_once_for_life_not_once_per_rebuild(self):
        """Break a run and rebuild it and 7 does not pay again — otherwise the
        optimal play is to break every streak on day eight."""
        self._run_to(7)
        before = wallet_for(self.u).spinaz
        self._run_to(7)
        self.assertEqual(wallet_for(self.u).spinaz, before)

    def test_a_broken_streak_restarts_at_one(self):
        self.r.last_done = timezone.localdate() - timedelta(days=3)
        self.r.streak = 12
        self.r.save(update_fields=["last_done", "streak"])
        self.assertEqual(L.keep_routine(self.r)["streak"], 1)


class BeginnerTests(TestCase):
    def setUp(self):
        self.new = member("newbie")
        self.old = member("veteran")

    def test_a_fresh_account_is_a_beginner(self):
        self.assertTrue(L.is_beginner(self.new))

    def test_a_battle_entry_graduates_you(self):
        from .models import Battle, BattleEntry
        b = Battle.objects.create(host=self.old, title="b")
        BattleEntry.objects.create(battle=b, user=self.new, title="t")
        self.assertFalse(L.is_beginner(self.new))


class GraduationTests(TestCase):
    """Three refusals, three different ways of paying yourself."""

    def setUp(self):
        self.helper = member("helper")
        self.new = member("rookie")
        self.third = member("third")

    def _sponsor(self):
        return L.sponsor(self.helper, self.new)

    def test_sponsoring_pays_nothing_yet(self):
        self._sponsor()
        self.assertEqual(wallet_for(self.helper).spinaz, 0)

    def test_graduating_with_somebody_else_pays_the_helper(self):
        self._sponsor()
        paid = L.graduate(self.new, partner=self.third)
        self.assertEqual(len(paid), 1)
        self.assertEqual(wallet_for(self.helper).spinaz, L.SPONSOR_GRADUATION_SPINAZ)
        self.assertEqual(wallet_for(self.helper).energy, L.SPONSOR_GRADUATION_ENERGY)

    def test_graduating_WITH_the_helper_pays_nothing(self):
        """A pair cannot be its own loop."""
        self._sponsor()
        self.assertEqual(L.graduate(self.new, partner=self.helper), [])
        self.assertEqual(wallet_for(self.helper).spinaz, 0)
        self.assertEqual(LilithSponsorship.objects.get().refused, "graduated with the helper")

    def test_the_helper_being_one_of_several_partners_still_refuses(self):
        """A two-person circle must not become payable by inviting a third."""
        self._sponsor()
        self.assertEqual(L.graduate(self.new, partners=[self.third, self.helper]), [])
        self.assertEqual(wallet_for(self.helper).spinaz, 0)

    def test_a_strong_dupez_link_refuses(self):
        """Same sign-in behind both accounts is one person paying themselves."""
        link_accounts(self.helper, self.new)
        self._sponsor()
        self.assertEqual(L.graduate(self.new, partner=self.third), [])
        self.assertIn("linked", LilithSponsorship.objects.get().refused)

    def test_a_stale_sponsorship_refuses(self):
        row = self._sponsor()
        LilithSponsorship.objects.filter(pk=row.pk).update(
            created_at=timezone.now() - timedelta(days=L.NEW_FOR_DAYS + 1))
        self.assertEqual(L.graduate(self.new, partner=self.third), [])
        self.assertIn("older", LilithSponsorship.objects.get().refused)

    def test_it_pays_once(self):
        self._sponsor()
        L.graduate(self.new, partner=self.third)
        L.graduate(self.new, partner=self.third)
        self.assertEqual(wallet_for(self.helper).spinaz, L.SPONSOR_GRADUATION_SPINAZ)

    def test_you_cannot_sponsor_somebody_already_graduated(self):
        from .models import Battle, BattleEntry
        b = Battle.objects.create(host=self.third, title="b")
        BattleEntry.objects.create(battle=b, user=self.new, title="t")
        self.assertIsNone(L.sponsor(self.helper, self.new))

    def test_you_cannot_sponsor_yourself(self):
        self.assertIsNone(L.sponsor(self.helper, self.helper))


class WorkingTogetherTests(TestCase):
    def setUp(self):
        self.a = member("alfa")
        self.b = member("bravo")

    def test_collabing_with_a_beginner_pays_energy_not_coin(self):
        got = L.collabed_with_beginner(self.a, self.b, beginner=True)
        self.assertEqual(got["energy"], L.COLLAB_WITH_BEGINNER_ENERGY)
        self.assertEqual(wallet_for(self.a).energy, L.COLLAB_WITH_BEGINNER_ENERGY)
        self.assertEqual(wallet_for(self.a).spinaz, 0)

    def test_it_caps_per_day(self):
        for _ in range(L.COLLAB_WITH_BEGINNER_DAILY_CAP):
            L.collabed_with_beginner(self.a, self.b, beginner=True)
        self.assertTrue(L.collabed_with_beginner(self.a, self.b, beginner=True)["capped"])
        self.assertEqual(wallet_for(self.a).energy,
                         L.COLLAB_WITH_BEGINNER_ENERGY * L.COLLAB_WITH_BEGINNER_DAILY_CAP)

    def test_a_strongly_linked_pair_is_paid_nothing(self):
        link_accounts(self.a, self.b)
        self.assertIsNone(L.collabed_with_beginner(self.a, self.b, beginner=True))

    def test_helping_somebody_established_pays_less(self):
        got = L.helped_graduated(self.a, self.b, beginner=False)
        self.assertEqual(got["spinaz"], L.HELP_GRADUATED_SPINAZ)
        self.assertLess(L.HELP_GRADUATED_SPINAZ, L.SPONSOR_GRADUATION_SPINAZ)

    def test_beginners_are_read_before_the_thing_completes(self):
        """The ordering trap this whole design turns on: after a battle entry
        exists, nobody in it is new, so a caller asking afterwards pays zero
        forever with nothing to notice."""
        from .models import Battle, BattleEntry
        before = L.beginners_among([self.a, self.b])
        self.assertEqual(before, {self.a.pk, self.b.pk})
        bt = Battle.objects.create(host=self.a, title="b")
        BattleEntry.objects.create(battle=bt, user=self.b, title="t")
        self.assertNotIn(self.b.pk, L.beginners_among([self.a, self.b]))
        # And with the pre-read set, the payout still lands.
        L.settle_together([self.a, self.b], before)
        self.assertEqual(wallet_for(self.a).energy, L.COLLAB_WITH_BEGINNER_ENERGY)

    def test_settle_never_takes_the_feature_down_with_it(self):
        """A bonus must never be the reason escrow fails to release."""
        self.assertEqual(L.settle_together([None, None], set()),
                         {"beginner": [], "help": [], "graduated": []})


class RewardsTableTests(TestCase):
    """The cost/gain rule: every number stated before anything is pressed."""

    def test_every_payer_in_the_module_appears_in_the_table(self):
        keys = {r["key"] for r in L.rewards_table()}
        for k in ("self_task", "platform_task", "auto_task", "collab_beginner",
                  "sponsor_graduation", "help_graduated"):
            self.assertIn(k, keys)
        for d in L.ROUTINE_MILESTONES:
            self.assertIn(f"routine_{d}", keys)

    def test_the_table_states_the_caps(self):
        by = {r["key"]: r for r in L.rewards_table()}
        self.assertIn(str(L.SELF_TASK_DAILY_CAP), by["self_task"]["cap"])
        self.assertIn(str(L.COLLAB_WITH_BEGINNER_DAILY_CAP), by["collab_beginner"]["cap"])

    def test_the_table_carries_the_numbers_the_code_pays(self):
        """One place, so the screen cannot state a price the server won't pay."""
        by = {r["key"]: r for r in L.rewards_table()}
        self.assertEqual(by["self_task"]["spinaz"], L.SELF_TASK_SPINAZ)
        self.assertEqual(by["collab_beginner"]["energy"], L.COLLAB_WITH_BEGINNER_ENERGY)
        self.assertEqual(by["sponsor_graduation"]["spinaz"], L.SPONSOR_GRADUATION_SPINAZ)


class TierTests(TestCase):
    def test_a_tier_says_how_many_never_whether(self):
        """catalog.py's rule: a limit that answers 'nothing' is a door out."""
        free = L.tier_limits("free")
        self.assertGreater(free["active_tasks"], 0)
        self.assertGreater(free["routines"], 0)

    def test_automation_is_what_a_tier_buys(self):
        self.assertFalse(L.tier_limits("free")["auto_schedule"])
        self.assertTrue(L.tier_limits("statz")["auto_schedule"])
        self.assertGreater(L.tier_limits("statz")["active_tasks"],
                           L.tier_limits("free")["active_tasks"])


class ApiTests(TestCase):
    def setUp(self):
        self.u = member("api")
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def test_the_board_publishes_the_rewards_before_anything_is_pressed(self):
        r = self.c.get("/api/economy/lilith/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["rewards"])
        self.assertEqual(r.data["today"]["self_cap"], L.SELF_TASK_DAILY_CAP)
        self.assertIn("said", r.data)

    def test_a_task_carries_what_ticking_it_pays(self):
        r = self.c.post("/api/economy/lilith/tasks/", {"title": "sing"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["pays"]["spinaz"], L.SELF_TASK_SPINAZ)

    def test_a_task_naming_an_app_is_a_platform_task_and_a_door(self):
        """The client cannot declare its own source — that flag sets the price."""
        r = self.c.post("/api/economy/lilith/tasks/",
                        {"title": "coach it", "app_key": "singz", "target": "singz:coach",
                         "source": "platform"}, format="json")
        self.assertEqual(r.data["source"], "platform")
        self.assertEqual(r.data["open_in"], {"tab": "singz", "target": "singz:coach"})
        self.assertEqual(r.data["pays"]["spinaz"], 0)

    def test_completing_reports_what_the_server_actually_paid(self):
        t = task(self.u)
        r = self.c.post(f"/api/economy/lilith/tasks/{t.pk}/complete/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["spinaz"], L.SELF_TASK_SPINAZ)
        self.assertEqual(r.data["today"]["self_paid"], 1)

    def test_you_cannot_tick_somebody_else_s_task(self):
        t = task(member("other"))
        self.assertEqual(self.c.post(f"/api/economy/lilith/tasks/{t.pk}/complete/").status_code, 404)

    def test_the_task_ceiling_says_what_a_tier_up_buys(self):
        cap = L.tier_limits("free")["active_tasks"]
        LilithTask.objects.bulk_create([LilithTask(user=self.u, title=f"t{n}")
                                        for n in range(cap)])
        r = self.c.post("/api/economy/lilith/tasks/", {"title": "one more"}, format="json")
        self.assertEqual(r.status_code, 402)
        self.assertTrue(r.data["at_limit"])
        self.assertIn("tier up", r.data["detail"])

    def test_sponsoring_records_and_states_what_it_will_pay(self):
        other = member("fresh")
        r = self.c.post("/api/economy/lilith/sponsor/", {"username": "fresh"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["spinaz"], L.SPONSOR_GRADUATION_SPINAZ)
        self.assertTrue(LilithSponsorship.objects.filter(helper=self.u, newcomer=other).exists())
        self.assertEqual(wallet_for(self.u).spinaz, 0)

    def test_the_board_needs_an_account(self):
        self.assertEqual(APIClient().get("/api/economy/lilith/").status_code, 401)
