"""Lilith tags: one more door on a task.

What these pin:

  - A tag is owner-only. Another member's task and a task that does not exist
    get the same answer, so the endpoint cannot be used to ask whose tasks exist.
  - The app key and the control name are checked on the server, because the
    control name is written into a CSS attribute selector on the client; a quote
    or bracket there would make the lookup throw.
  - Ten a task, and one of each door. The cap and the uniqueness rule are what
    keep a tag list from becoming a second to-do list.
  - A tag pays nothing. No coin, no energy, no ledger row.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .lilith_tags import TAGS_PER_TASK
from .models import LilithTag, LilithTask, Transaction, Wallet, wallet_for

User = get_user_model()
PW = "pw12345!"

TAGS = "/api/economy/lilith/tags/"
ADD = "/api/economy/lilith/tag/"


def member(name):
    return User.objects.create_user(name, f"{name}@mcz.test", PW)


def task(user, title="record the verse"):
    return LilithTask.objects.create(user=user, title=title, source="self")


def tag_url(tag_id):
    return f"/api/economy/lilith/tag/{tag_id}/"


def add(client, task_id, app, target):
    return client.post(ADD, {"task_id": task_id, "to_app_key": app, "to_target": target},
                       format="json")


class TagRoundTripTests(TestCase):
    def setUp(self):
        self.u = member("tagger")
        self.c = APIClient()
        self.c.force_authenticate(self.u)
        self.t = task(self.u)

    def test_add_list_and_remove(self):
        r = add(self.c, self.t.pk, "postz", "post:12")
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertEqual((body["to_app_key"], body["to_target"]), ("postz", "post:12"))

        r = self.c.get(f"{TAGS}?task_id={self.t.pk}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x["id"] for x in r.json()], [body["id"]])

        r = self.c.delete(tag_url(body["id"]))
        self.assertEqual(r.status_code, 200)
        # JSON, not an empty 204: the client refreshes only when it gets a body back.
        self.assertEqual(r.json(), {"deleted": body["id"]})
        self.assertEqual(self.c.get(f"{TAGS}?task_id={self.t.pk}").json(), [])

    def test_the_list_is_a_bare_list_oldest_first(self):
        for app, target in (("singz", "singz:coach"), ("battlez", "battlez:enter"),
                            ("lilith", "lilith:logbook")):
            self.assertEqual(add(self.c, self.t.pk, app, target).status_code, 201)
        r = self.c.get(f"{TAGS}?task_id={self.t.pk}")
        self.assertIsInstance(r.json(), list)
        self.assertEqual([x["to_target"] for x in r.json()],
                         ["singz:coach", "battlez:enter", "lilith:logbook"])


class OwnershipTests(TestCase):
    def setUp(self):
        self.owner = member("owner")
        self.other = member("other")
        self.t = task(self.owner)
        self.c = APIClient()
        self.c.force_authenticate(self.other)

    def test_someone_elses_task_is_refused_on_every_door(self):
        self.assertEqual(self.c.get(f"{TAGS}?task_id={self.t.pk}").status_code, 404)
        self.assertEqual(add(self.c, self.t.pk, "postz", "post:1").status_code, 404)
        self.assertFalse(LilithTag.objects.exists())

    def test_a_task_that_does_not_exist_gets_the_same_answer(self):
        self.assertEqual(self.c.get(f"{TAGS}?task_id=999999").status_code, 404)
        self.assertEqual(add(self.c, 999999, "postz", "post:1").status_code, 404)

    def test_someone_elses_tag_cannot_be_removed(self):
        mine = LilithTag.objects.create(user=self.owner, task=self.t,
                                        to_app_key="postz", to_target="post:1")
        self.assertEqual(self.c.delete(tag_url(mine.pk)).status_code, 404)
        self.assertTrue(LilithTag.objects.filter(pk=mine.pk).exists())

    def test_a_removed_or_missing_tag_is_a_plain_404(self):
        self.assertEqual(self.c.delete(tag_url(999999)).status_code, 404)

    def test_anonymous_is_refused(self):
        anon = APIClient()
        self.assertIn(anon.get(f"{TAGS}?task_id={self.t.pk}").status_code, (401, 403))
        r = anon.post(ADD, {"task_id": self.t.pk, "to_app_key": "postz", "to_target": "post:1"},
                      format="json")
        self.assertIn(r.status_code, (401, 403))
        self.assertFalse(LilithTag.objects.exists())


class ValidationTests(TestCase):
    def setUp(self):
        self.u = member("checker")
        self.c = APIClient()
        self.c.force_authenticate(self.u)
        self.t = task(self.u)

    def test_task_id_must_be_a_number(self):
        self.assertEqual(self.c.get(TAGS).status_code, 400)
        self.assertEqual(self.c.get(f"{TAGS}?task_id=abc").status_code, 400)
        self.assertEqual(
            self.c.post(ADD, {"task_id": "abc", "to_app_key": "postz", "to_target": "post:1"},
                        format="json").status_code, 400)
        self.assertEqual(
            self.c.post(ADD, {"to_app_key": "postz", "to_target": "post:1"},
                        format="json").status_code, 400)

    def test_the_app_key_must_look_like_a_tab_key(self):
        for bad in ("", "P", "PostZ", "post z", "post-z", "post/z", "9lives", "x" * 33):
            with self.subTest(app=bad):
                self.assertEqual(add(self.c, self.t.pk, bad, "post:1").status_code, 400)
        self.assertFalse(LilithTag.objects.exists())

    def test_the_control_name_is_checked_because_it_becomes_a_selector(self):
        for bad in ('post"x', "post]", "a b", "a'b", "post;drop", "p" * 65, ""):
            with self.subTest(target=bad):
                self.assertEqual(add(self.c, self.t.pk, "postz", bad).status_code, 400)
        self.assertFalse(LilithTag.objects.exists())

    def test_real_control_names_are_accepted(self):
        for ok in ("singz:coach", "post:123", "lilith:logbook", "user.abc-1_x", "p" * 64):
            with self.subTest(target=ok):
                self.assertEqual(add(self.c, self.t.pk, "postz", ok).status_code, 201)


class CapAndUniquenessTests(TestCase):
    def setUp(self):
        self.u = member("capper")
        self.c = APIClient()
        self.c.force_authenticate(self.u)
        self.t = task(self.u)

    def test_the_same_door_twice_is_refused_and_the_request_still_works(self):
        self.assertEqual(add(self.c, self.t.pk, "postz", "post:1").status_code, 201)
        r = add(self.c, self.t.pk, "postz", "post:1")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"], "That tag is already on this task.")
        # The duplicate was caught inside a savepoint, so the same test can still read.
        self.assertEqual(len(self.c.get(f"{TAGS}?task_id={self.t.pk}").json()), 1)

    def test_the_same_door_is_fine_on_a_different_task(self):
        other = task(self.u, title="another verse")
        self.assertEqual(add(self.c, self.t.pk, "postz", "post:1").status_code, 201)
        self.assertEqual(add(self.c, other.pk, "postz", "post:1").status_code, 201)

    def test_a_task_holds_at_most_ten_tags(self):
        for n in range(TAGS_PER_TASK):
            LilithTag.objects.create(user=self.u, task=self.t,
                                     to_app_key="postz", to_target=f"post:{n}")
        r = add(self.c, self.t.pk, "postz", "post:999")
        self.assertEqual(r.status_code, 400)
        self.assertIn(f"holds {TAGS_PER_TASK} tags", r.json()["detail"])
        self.assertEqual(LilithTag.objects.filter(task=self.t).count(), TAGS_PER_TASK)

    def test_removing_one_makes_room(self):
        tags = [LilithTag.objects.create(user=self.u, task=self.t,
                                         to_app_key="postz", to_target=f"post:{n}")
                for n in range(TAGS_PER_TASK)]
        self.assertEqual(self.c.delete(tag_url(tags[0].pk)).status_code, 200)
        self.assertEqual(add(self.c, self.t.pk, "postz", "post:999").status_code, 201)


class CascadeAndPaysNothingTests(TestCase):
    def setUp(self):
        self.u = member("cascade")
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def test_deleting_the_task_takes_its_tags(self):
        t = task(self.u)
        LilithTag.objects.create(user=self.u, task=t, to_app_key="postz", to_target="post:1")
        t.delete()
        self.assertFalse(LilithTag.objects.exists())

    def test_a_tag_moves_no_coin_energy_or_ledger(self):
        t = task(self.u)
        wallet_for(self.u)  # create the wallet first, so the baseline is a real row
        before = list(Wallet.objects.filter(user=self.u).values_list("spinaz", "energy"))
        ledger = Transaction.objects.count()

        self.assertEqual(add(self.c, t.pk, "postz", "post:1").status_code, 201)

        after = list(Wallet.objects.filter(user=self.u).values_list("spinaz", "energy"))
        self.assertEqual(before, after)
        self.assertEqual(Transaction.objects.count(), ledger)


class ColumnWidthTests(TestCase):
    """SQLite ignores varchar length and Postgres does not, so the longest value a door accepts
    has to fit the column it is written to. Run this module against Postgres as well."""

    def setUp(self):
        self.u = member("widest")
        self.c = APIClient()
        self.c.force_authenticate(self.u)
        self.t = task(self.u)

    def test_the_longest_legal_app_key_and_target_are_stored_whole(self):
        app = "a" + "b" * 31           # 32: the most a tab key may be
        target = "p" * 64              # 64: the most a control name may be
        r = add(self.c, self.t.pk, app, target)
        self.assertEqual(r.status_code, 201, r.content)
        row = LilithTag.objects.get(pk=r.json()["id"])
        self.assertEqual((row.to_app_key, row.to_target), (app, target))
