"""LeaderboardZ: it has to answer at all, and answer with the real number.

There was no test file here, which is the whole story. `leaderboardz.py`
imported a model that has never existed, and because `LeaderboardsView` imports
the module INSIDE the request rather than at module scope, nothing failed at
boot — both endpoints simply answered 500 for every caller, from the day they
were written until someone opened the screen in a browser.

So the first test is the dull one: does it return 200. That is the test that
would have caught it, and it is worth more than the five below it.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.skillz.models import TrainingEvent, TrainingProfile

from .models import Membership, Transaction, Wallet, wallet_for

User = get_user_model()


def _earn(user, resource, amount, kind=Transaction.KIND_REWARD,
          visibility=Transaction.VIS_PUBLIC, when=None):
    t = Transaction.objects.create(
        user=user, kind=kind, resource=resource, amount=amount,
        amount_cents=0, visibility=visibility,
    )
    if when:
        # auto_now_add ignores an assigned value, so the row is moved after.
        Transaction.objects.filter(pk=t.pk).update(created_at=when)
    return t


def _trained(user, app_key, xp, when=None):
    p, _ = TrainingProfile.objects.get_or_create(user=user, app_key=app_key)
    p.xp = xp
    p.save()
    e = TrainingEvent.objects.create(profile=p, drill_key="d", xp_awarded=xp)
    if when:
        TrainingEvent.objects.filter(pk=e.pk).update(created_at=when)
    return p


class ItAnswersAtAll(TestCase):
    """The regression. Both endpoints 500'd for their whole life."""

    def setUp(self):
        self.u = User.objects.create_user(username="lb1", password="pw")

    def test_the_board_returns_200(self):
        self.assertEqual(self.client.get("/api/economy/leaderboardz/").status_code, 200)

    def test_every_period_returns_200(self):
        for period in ("all", "week", "month"):
            with self.subTest(period=period):
                r = self.client.get(f"/api/economy/leaderboardz/?period={period}")
                self.assertEqual(r.status_code, 200)

    def test_the_instrument_board_returns_200(self):
        for period in ("all", "week"):
            with self.subTest(period=period):
                r = self.client.get(f"/api/economy/leaderboardz/xp/singz/?period={period}")
                self.assertEqual(r.status_code, 200)

    def test_an_empty_platform_is_an_empty_board_not_an_error(self):
        r = self.client.get("/api/economy/leaderboardz/xp/nobody_plays_this/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["leaders"], [])

    def test_the_module_imports_at_module_scope(self):
        """The deferred import in the view is what hid this for so long.

        Importing it here means a bad top-level import fails THIS test rather
        than every request in production.
        """
        from . import leaderboardz
        self.assertTrue(hasattr(leaderboardz, "top_xp_earners_by_instrument"))

    def test_nothing_imports_the_model_that_never_existed(self):
        import pathlib
        src = (pathlib.Path(__file__).parent / "leaderboardz.py").read_text()
        # Named in the docstring as the bug; must not come back as code.
        self.assertNotIn("import SkillProgression", src)


class TheXpBoardRanksRealTraining(TestCase):
    def setUp(self):
        self.a = User.objects.create_user(username="drummer", password="pw")
        self.b = User.objects.create_user(username="singer", password="pw")
        self.c = User.objects.create_user(username="idle", password="pw")

    def test_it_ranks_by_the_profiles_own_xp(self):
        _trained(self.a, "singz", 1200)
        _trained(self.b, "singz", 300)
        from . import leaderboardz
        rows = leaderboardz.top_xp_earners_by_instrument("singz")
        self.assertEqual([r["username"] for r in rows], ["drummer", "singer"])
        self.assertEqual(rows[0]["xp_earned"], 1200)
        # 1200 XP at 500/level is level 3, computed by the model not by us.
        self.assertEqual(rows[0]["level"], 3)

    def test_it_is_per_instrument(self):
        _trained(self.a, "singz", 900)
        _trained(self.b, "rapz", 5000)
        from . import leaderboardz
        rows = leaderboardz.top_xp_earners_by_instrument("singz")
        self.assertEqual([r["username"] for r in rows], ["drummer"])

    def test_nobody_with_no_xp_is_on_the_board(self):
        _trained(self.a, "singz", 100)
        TrainingProfile.objects.create(user=self.c, app_key="singz", xp=0)
        from . import leaderboardz
        rows = leaderboardz.top_xp_earners_by_instrument("singz")
        self.assertEqual([r["username"] for r in rows], ["drummer"])

    def test_a_period_counts_only_the_events_inside_it(self):
        """The lifetime total cannot answer 'this week', so events do."""
        old = timezone.now() - timedelta(days=30)
        _trained(self.a, "singz", 5000, when=old)      # big, but long ago
        _trained(self.b, "singz", 400)                 # small, this week
        from . import leaderboardz

        week = leaderboardz.top_xp_earners_by_instrument("singz", period_days=7)
        self.assertEqual([r["username"] for r in week], ["singer"])
        self.assertEqual(week[0]["xp_earned"], 400)
        # …while the level shown stays the lifetime one: a member's level is
        # not a function of the window you happen to be looking at.
        self.assertEqual(week[0]["xp_progress"], 400)

        alltime = leaderboardz.top_xp_earners_by_instrument("singz")
        self.assertEqual([r["username"] for r in alltime], ["drummer", "singer"])

    def test_limit_is_honoured(self):
        for i in range(5):
            u = User.objects.create_user(username=f"p{i}", password="pw")
            _trained(u, "singz", 100 * (i + 1))
        from . import leaderboardz
        self.assertEqual(len(leaderboardz.top_xp_earners_by_instrument("singz", limit=3)), 3)


class TheEarningsBoardsReportRealNumbers(TestCase):
    def setUp(self):
        self.u = User.objects.create_user(username="earner", password="pw")

    def test_current_spinaz_is_the_real_balance(self):
        """It was `hasattr(u, "wallet_for")` — never true, so always 0."""
        _earn(self.u, Transaction.RES_SPINAZ, 500)
        w = wallet_for(self.u)
        w.spinaz = 320
        w.save()
        from . import leaderboardz
        row = leaderboardz.top_spinaz_earners()[0]
        self.assertEqual(row["spinaz_earned"], 500)
        self.assertEqual(row["current_spinaz"], 320)

    def test_private_earnings_stay_off_the_board(self):
        _earn(self.u, Transaction.RES_SPINAZ, 900,
              visibility=Transaction.VIS_PRIVATE)
        from . import leaderboardz
        self.assertEqual(leaderboardz.top_spinaz_earners(), [])

    def test_a_member_with_no_membership_or_wallet_row_does_not_500(self):
        """A board is the one screen guaranteed to touch strangers' accounts,
        so a row that was never created is a matter of time, not an edge."""
        _earn(self.u, Transaction.RES_ENERGY, 40)
        Membership.objects.filter(user=self.u).delete()
        Wallet.objects.filter(user=self.u).delete()
        from . import leaderboardz
        row = leaderboardz.top_energy_earners()[0]
        self.assertEqual(row["username"], "earner")
        self.assertEqual(row["tier"], "free")      # the default they really have
        self.assertEqual(row["current_energy"], 0)

    def test_the_energy_board_does_not_query_per_row(self):
        """It was two .get() calls per member — 2N queries for one page."""
        for i in range(6):
            u = User.objects.create_user(username=f"e{i}", password="pw")
            _earn(u, Transaction.RES_ENERGY, 10 * (i + 1))
        from . import leaderboardz
        with self.assertNumQueries(3):     # the page, then tiers, then wallets
            leaderboardz.top_energy_earners(limit=6)
