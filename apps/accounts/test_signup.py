"""What the signup form accepts, and whether the two writers agree.

`RegisterSerializer` is a plain Serializer rather than a ModelSerializer, so
Django's `UnicodeUsernameValidator` never ran, and `create_user()` does not
call `full_clean()`. The field was `CharField(max_length=150)` and nothing
else — while `check-username/` carried a real rule, behind IsAuthenticated,
reachable from no screen that needs it, and applied to nothing.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import (PROMPT_ALLOWANCE, SIGNUP_WELCOME_SPINAZ,
                                 TrialTake)

from .usernames import RESERVED, USERNAME_RE
from .views import _unique_username

User = get_user_model()


class WhatAUsernameMayBeTests(TestCase):

    def setUp(self):
        self.c = APIClient()

    def reg(self, username, email=None, password="hunter2hunter2"):
        return self.c.post("/api/auth/register/", {
            "username": username, "email": email or f"{username!r}@x.test".replace("'", ""),
            "password": password}, format="json")

    def test_a_handle_that_breaks_its_own_url_is_refused(self):
        """"a/b" registered, and their public profile 404'd — an account no
        screen on the platform could address."""
        self.assertEqual(self.reg("a/b").status_code, 400)
        self.assertEqual(self.reg("who?").status_code, 400)
        self.assertEqual(self.reg("hash#tag").status_code, 400)

    def test_a_handle_that_breaks_its_own_referral_link_is_refused(self):
        """The invite is `?ref=<username>`, so a `#` truncates it to a
        fragment and a `?` starts a second query — and the referral ladder is
        the growth mechanic."""
        self.assertEqual(self.reg("hash#tag").status_code, 400)

    def test_markup_is_refused(self):
        self.assertEqual(self.reg("<script>x</script>").status_code, 400)

    def test_a_handle_that_reads_as_somebody_else_is_refused(self):
        for name in ("admin", "support", "everyone", "official"):
            self.assertEqual(self.reg(name).status_code, 400, name)

    def test_ordinary_handles_still_work(self):
        for name in ("good_name", "GoodName9", "abc", "a" * 20):
            r = self.reg(name)
            self.assertEqual(r.status_code, 201, f"{name}: {r.data}")

    def test_the_bounds_are_the_bounds(self):
        self.assertEqual(self.reg("ab").status_code, 400)
        self.assertEqual(self.reg("a" * 21).status_code, 400)


class ThePasswordRuleAppliedOnTheWrongEndTests(TestCase):
    """`passwords.py` runs Django's validators on a RESET. Registration ran
    only `min_length=8`. So you could sign up with "password" and then be
    refused that same password when changing it — the rule enforced at the
    weaker moment and not the stronger one, and the only way to find out was
    to try to stop using it."""

    def reg(self, password, username="pwtest"):
        return APIClient().post("/api/auth/register/", {
            "username": username, "email": "pw@x.test", "password": password},
            format="json")

    def test_the_commonest_passwords_are_refused_at_signup(self):
        for pw in ("password", "12345678", "qwertyui"):
            r = self.reg(pw)
            self.assertEqual(r.status_code, 400, pw)
            self.assertIn("password", r.data)

    def test_a_real_password_still_works(self):
        self.assertEqual(self.reg("hunter2hunter2").status_code, 201)


class TheCheckIsOpenToThePeopleWhoNeedItTests(TestCase):
    """It was behind IsAuthenticated, so it could only answer for people who
    had already stopped asking — which is why nothing called it and why a
    whole form got filled in before "that username is taken"."""

    def setUp(self):
        self.c = APIClient()

    def test_a_logged_out_visitor_may_ask(self):
        r = self.c.get("/api/auth/check-username/?username=freehandle")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["available"])

    def test_the_rule_travels_even_on_a_good_answer(self):
        """So the form can state it BEFORE somebody picks a handle that breaks
        it, rather than only after."""
        r = self.c.get("/api/auth/check-username/?username=freehandle")
        self.assertTrue(r.data["rule"])

    def test_it_refuses_exactly_what_register_refuses(self):
        """One rule. The checker used to be the only thing that had it and the
        only thing that could not create an account."""
        for name in ("a/b", "admin", "ab", "<script>"):
            said = self.c.get(f"/api/auth/check-username/?username={name}").data
            made = self.c.post("/api/auth/register/", {
                "username": name, "email": "x@y.test", "password": "hunter2hunter2"},
                format="json")
            self.assertFalse(said["available"], name)
            self.assertEqual(made.status_code, 400, name)

    def test_a_taken_handle_is_reported_as_taken(self):
        User.objects.create_user("already", "a@b.test", "hunter2hunter2")
        r = self.c.get("/api/auth/check-username/?username=ALREADY")
        self.assertFalse(r.data["available"])


class TheOtherUsernameWriterTests(TestCase):
    """OAuth builds a handle out of whatever a provider called somebody. It
    allowed `.` and `-` and ran to 140 characters, so the two writers
    disagreed: "bob.obrien" and "admin" registered here and are refused on the
    form."""

    def test_every_provider_name_becomes_a_legal_handle(self):
        for raw in ["bob.obrien", "admin", "Bob O'Brien", "", None, "a",
                    "x" * 200, "!!!", "K-Oth", "用户名", "support"]:
            out = _unique_username(raw)
            self.assertTrue(USERNAME_RE.match(out), f"{raw!r} -> {out!r}")
            self.assertNotIn(out.lower(), RESERVED, f"{raw!r} -> {out!r}")

    def test_it_sanitizes_and_never_refuses(self):
        """An OAuth sign-in must not fail because a display name has an
        apostrophe in it — that is a wall in front of the easiest door."""
        self.assertTrue(_unique_username("!!!"))

    def test_collisions_still_resolve_inside_the_rule(self):
        User.objects.create_user("taken", "a@b.test", "hunter2hunter2")
        out = _unique_username("taken")
        self.assertNotEqual(out.lower(), "taken")
        self.assertTrue(USERNAME_RE.match(out))


class TheJoinNumbersAreServedNotTypedTests(TestCase):
    """Register.jsx had "3 scored takes/day", "5 scored takes/day", "2x faster
    Energy" and both referral amounts typed into the copy, because this
    endpoint served none of them."""

    def setUp(self):
        self.r = APIClient().get("/api/economy/tiers/")

    def test_the_allowance_the_screen_sells_on_is_published(self):
        for t in self.r.data["tiers"]:
            self.assertEqual(t["daily_prompts"], PROMPT_ALLOWANCE[t["key"]])

    def test_the_energy_rate_is_published_and_premium_is_not_2x(self):
        """The copy claimed 2x. At the FLOOR — which is the rate that applies
        to anybody reading a signup page, because reach is 0 until an external
        account is verified — it is 3x."""
        by = {t["key"]: t["energy_per_hour"] for t in self.r.data["tiers"]}
        self.assertEqual(by["premium"], by["free"] * 3)

    def test_what_joining_pays_is_published(self):
        join = self.r.data["join"]
        self.assertEqual(join["welcome_spinaz"], SIGNUP_WELCOME_SPINAZ)
        self.assertTrue(join["referrer_spinaz"])
        self.assertTrue(join["joinee_spinaz"])


class TheThingThatMadeThemSignUpTests(TestCase):
    """A trial take, scored before they had anywhere to put it."""

    def test_registering_with_the_token_keeps_the_take(self):
        t = TrialTake.objects.create(token="tok123", app_key="singz",
                                     result={"score": 7})
        r = APIClient().post("/api/auth/register/", {
            "username": "keeper", "email": "k@x.test",
            "password": "hunter2hunter2", "trial_token": "tok123"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        t.refresh_from_db()
        self.assertTrue(t.claimed_by_id)

    def test_a_junk_token_never_blocks_the_signup(self):
        r = APIClient().post("/api/auth/register/", {
            "username": "keeper2", "email": "k2@x.test",
            "password": "hunter2hunter2", "trial_token": "nonsense"}, format="json")
        self.assertEqual(r.status_code, 201)

    def test_a_junk_referral_never_blocks_the_signup(self):
        r = APIClient().post("/api/auth/register/", {
            "username": "keeper3", "email": "k3@x.test",
            "password": "hunter2hunter2", "ref": "nobody"}, format="json")
        self.assertEqual(r.status_code, 201)


class TrialSplitOnRegisterTests(TestCase):
    """The BodieZ trial's "Build a week" is built free, client-side, no
    account and no AI — see bodiez.py's clean_trial_split docstring. What was
    built only becomes real if registration actually completes, which is
    what these pin."""

    def setUp(self):
        from apps.economy.models import BodieZExercise
        self.squat = BodieZExercise.objects.create(name="Register Split Test Squat", muscle_group="legs", equipment="barbell")
        self.bench = BodieZExercise.objects.create(name="Register Split Test Bench", muscle_group="chest", equipment="barbell")

    def _split(self, days=2):
        base = [
            {"title": "Day 1 — Legs", "exercises": [
                {"exercise_id": self.squat.id, "order": 0, "sets": 4, "reps": 8, "weight_kg": 60}]},
            {"title": "Day 2 — Chest", "exercises": [
                {"exercise_id": self.bench.id, "order": 0, "sets": 3, "reps": 10, "weight_kg": None}]},
        ]
        return base[:days]

    def test_registering_with_a_built_split_keeps_it_as_real_routines(self):
        from apps.economy.models import BodieZRoutine
        r = APIClient().post("/api/auth/register/", {
            "username": "weekbuilder", "email": "wb@x.test",
            "password": "hunter2hunter2", "trial_split": self._split()}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        user = User.objects.get(username="weekbuilder")
        routines = list(BodieZRoutine.objects.filter(user=user).order_by("id"))
        self.assertEqual(len(routines), 2)
        self.assertEqual(routines[0].title, "Day 1 — Legs")
        self.assertEqual(routines[0].exercises[0]["exercise_id"], self.squat.id)
        self.assertEqual(routines[1].exercises[0]["exercise_id"], self.bench.id)
        self.assertTrue(all(r.bucket == "inbox" for r in routines))

    def test_an_unknown_exercise_id_is_dropped_not_rejected(self):
        from apps.economy.models import BodieZRoutine
        split = [{"title": "Day 1", "exercises": [
            {"exercise_id": 999999, "order": 0, "sets": 3, "reps": 10}]}]
        r = APIClient().post("/api/auth/register/", {
            "username": "sneaky", "email": "sneaky@x.test",
            "password": "hunter2hunter2", "trial_split": split}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        user = User.objects.get(username="sneaky")
        # A day with no valid exercises left is dropped entirely rather than
        # saved empty — a routine with nothing in it is not a routine.
        self.assertEqual(BodieZRoutine.objects.filter(user=user).count(), 0)

    def test_junk_trial_split_never_blocks_the_signup(self):
        r = APIClient().post("/api/auth/register/", {
            "username": "junkweek", "email": "junkweek@x.test",
            "password": "hunter2hunter2", "trial_split": "not a list"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_more_than_six_days_is_truncated_not_rejected(self):
        from apps.economy.models import BodieZRoutine
        split = [{"title": f"Day {i}", "exercises": [
            {"exercise_id": self.squat.id, "order": 0, "sets": 3, "reps": 10}]} for i in range(9)]
        r = APIClient().post("/api/auth/register/", {
            "username": "sevendays", "email": "sevendays@x.test",
            "password": "hunter2hunter2", "trial_split": split}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        user = User.objects.get(username="sevendays")
        self.assertLessEqual(BodieZRoutine.objects.filter(user=user).count(), 6)


class TheThirdUsernameWriterTests(TestCase):
    """`PATCH /api/auth/me/` lets a Premium member change their handle, and it
    carried its OWN copy of the regex — the third — with no reserved list. So
    a Premium member could rename themselves `admin`, `support` or `official`:
    impersonation, behind a paywall."""

    def setUp(self):
        from apps.economy.models import membership_for
        self.u = User.objects.create_user("premium1", "p@x.test", "hunter2hunter2")
        m = membership_for(self.u)
        m.tier = "premium"
        m.save(update_fields=["tier"])
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def rename(self, to):
        return self.c.patch("/api/auth/me/", {"username": to}, format="json")

    def test_a_reserved_handle_cannot_be_bought(self):
        for name in ("admin", "support", "official", "everyone"):
            r = self.rename(name)
            self.assertEqual(r.status_code, 400, name)
            self.u.refresh_from_db()
            self.assertEqual(self.u.username, "premium1")

    def test_a_broken_shape_is_still_refused(self):
        self.assertEqual(self.rename("a/b").status_code, 400)

    def test_an_ordinary_rename_still_works(self):
        self.assertEqual(self.rename("new_handle").status_code, 200)
        self.u.refresh_from_db()
        self.assertEqual(self.u.username, "new_handle")

    def test_keeping_your_own_handle_is_not_reported_as_taken(self):
        """`username_problem(taken=False)` exists for exactly this: the
        uniqueness question on a rename has to exclude yourself."""
        self.assertEqual(self.rename("premium1").status_code, 200)


class TheRenameReportedFailureOnSuccessTests(TestCase):
    """`changed.append("username")` fed `Profile.save(update_fields=...)`, and
    `username` is a User column — so every Premium handle change raised
    "fields do not exist in this model" and 500'd, one line AFTER the handle
    had already been saved.

    The rename worked and reported failure. The member sees an error, tries
    again, and is told the handle is taken — by themselves. `first_name` and
    `last_name` hit the same trap and were given their own `named` list; this
    one was missed."""

    def setUp(self):
        from apps.economy.models import membership_for
        self.u = User.objects.create_user("premium2", "p2@x.test", "hunter2hunter2")
        m = membership_for(self.u)
        m.tier = "premium"
        m.save(update_fields=["tier"])
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def test_a_rename_alone_returns_200(self):
        r = self.c.patch("/api/auth/me/", {"username": "renamed_ok"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.u.refresh_from_db()
        self.assertEqual(self.u.username, "renamed_ok")

    def test_a_rename_alongside_a_profile_field_still_saves_both(self):
        r = self.c.patch("/api/auth/me/",
                         {"username": "renamed2", "location": "Leeds"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.u.refresh_from_db()
        self.assertEqual(self.u.username, "renamed2")
        from apps.economy.models import Profile
        self.assertEqual(Profile.objects.get(user=self.u).location, "Leeds")


class TheSweepForWhoeverIsAlreadyOverTests(TestCase):
    """"Never lower a live limit without a plan for the members already over
    it." The rule was applied by nothing that creates accounts, so anything
    could be registered; tightening it strands whoever got in first."""

    def test_it_names_them_and_changes_nothing(self):
        from io import StringIO

        from django.core.management import call_command

        bad = User.objects.create(username="a/b", email="ab@x.test")
        User.objects.create_user("fine_one", "f@x.test", "hunter2hunter2")
        out = StringIO()
        call_command("audit_usernames", stdout=out)
        text = out.getvalue()
        self.assertIn("a/b", text)
        self.assertNotIn("fine_one", text)
        bad.refresh_from_db()
        self.assertEqual(bad.username, "a/b", "the sweep must never rewrite a handle")

    def test_broken_only_separates_damage_from_mere_non_compliance(self):
        from io import StringIO

        from django.core.management import call_command

        User.objects.create(username="a/b", email="ab@x.test")
        User.objects.create(username="ok.name", email="ok@x.test")
        out = StringIO()
        call_command("audit_usernames", "--broken-only", stdout=out)
        text = out.getvalue()
        self.assertIn("a/b", text)
        self.assertNotIn("ok.name", text)
