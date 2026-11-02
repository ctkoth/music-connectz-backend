"""PhilosophieZ: two declarations, never scores, never inferred, politics private by default.

The lines pinned here are the ones that keep it allowed: the lists are closed and
unranked, junk is "hasn't said", nothing writes the columns but the two profile
writers, and — the one that matters most — a hidden declaration can be read off
neither the card nor the search.
"""
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import philosophiez as ph
from apps.economy.models import profile_for
from apps.economy.visibility import DEFAULTS, MEMBER, PRIVATE, can_see

User = get_user_model()
PW = "hunter2hunter2"
LIST_URL = "/api/economy/philosophiez/"
MEMBERS = "/api/economy/members/"
PROFILE = "/api/economy/profile/"


class ListTests(TestCase):
    def test_keys_are_unique_and_fit_the_column(self):
        for rows in (ph.PHILOSOPHIES, ph.POLITICS):
            keys = [k for k, _ in rows]
            self.assertEqual(len(set(keys)), len(keys))
            self.assertTrue(all(len(k) <= 32 for k in keys))

    def test_a_row_is_a_key_and_a_label_and_nothing_else(self):
        # No weight, no rank, no head-count: the change that would look harmless and turn
        # a declaration into a measurement.
        for row in ph.PHILOSOPHIES + ph.POLITICS:
            self.assertEqual(len(row), 2)

    def test_the_order_implies_nothing(self):
        # Alphabetical by label with Other last. A left-to-right order would be a claim
        # about the spectrum; this one is read by nothing but the picker.
        for rows in (ph.PHILOSOPHIES, ph.POLITICS):
            labels = [l for k, l in rows if k != "other"]
            self.assertEqual(labels, sorted(labels, key=str.lower))
            self.assertEqual(rows[-1][0], "other")

    def test_politics_names_outlooks_not_parties(self):
        words = " ".join(l.lower() for _, l in ph.POLITICS)
        for party in ("democrat party", "republican", "labour", "tory", "gop", "maga"):
            self.assertNotIn(party, words)


class CleanTests(TestCase):
    def test_known_keys_read_straight_and_every_listed_key_survives(self):
        self.assertEqual(ph.clean_philosophy(" Stoicism "), "stoicism")
        self.assertEqual(ph.clean_politics("CENTRIST"), "centrist")
        for k, _ in ph.PHILOSOPHIES:
            self.assertEqual(ph.clean_philosophy(k), k)
        for k, _ in ph.POLITICS:
            self.assertEqual(ph.clean_politics(k), k)

    def test_junk_is_nothing_said_and_never_refuses_a_save(self):
        for bad in ("nonsense", None, "", 7, {"a": 1}):
            self.assertEqual(ph.clean_philosophy(bad), "")
            self.assertEqual(ph.clean_politics(bad), "")

    def test_the_two_lists_do_not_answer_each_others_keys(self):
        # A politics value must not be accepted as a philosophy, or a client mixing them
        # up would store a wrong declaration instead of a blank one.
        self.assertEqual(ph.clean_philosophy("liberal"), "")
        self.assertEqual(ph.clean_politics("stoicism"), "")


class EndpointTests(TestCase):
    def test_it_opens_logged_out_and_serves_both_lists(self):
        r = APIClient().get(LIST_URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["philosophies"]), len(ph.PHILOSOPHIES))
        self.assertEqual(len(r.data["politics"]), len(ph.POLITICS))
        for row in r.data["philosophies"] + r.data["politics"]:
            self.assertEqual(set(row), {"key", "label"})

    def test_it_says_politics_is_private_before_anything_is_declared(self):
        self.assertIn("private by default", APIClient().get(LIST_URL).data["politics_note"])


class PrivacyDefaultTests(TestCase):
    def test_philosophy_is_open_to_members_and_politics_is_private(self):
        self.assertEqual(DEFAULTS["philosophy"], MEMBER)
        self.assertEqual(DEFAULTS["politics"], PRIVATE)

    def test_a_member_cannot_read_anothers_politics_until_it_is_opened(self):
        owner = User.objects.create_user("owner", "o@e.com", PW)
        viewer = User.objects.create_user("viewer", "v@e.com", PW)
        p = profile_for(owner)
        self.assertFalse(can_see(p, "politics", viewer))
        self.assertTrue(can_see(p, "politics", owner))
        p.visibility = {"politics": ["member"]}
        p.save()
        self.assertTrue(can_see(p, "politics", viewer))


class WritersTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("w", "w@e.com", PW)
        self.client = APIClient()
        self.client.force_authenticate(self.u)

    def test_the_profile_writer_stores_both_and_cleans_junk(self):
        r = self.client.post(PROFILE, {"philosophy": "stoicism", "politics": "nope"}, format="json")
        self.assertEqual(r.status_code, 200)
        p = profile_for(self.u)
        self.assertEqual((p.philosophy, p.politics), ("stoicism", ""))

    def test_the_account_writer_stores_both_through_the_same_cleaners(self):
        r = self.client.patch("/api/auth/me/", {"philosophy": "humanism", "politics": "liberal"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        p = profile_for(self.u)
        self.assertEqual((p.philosophy, p.politics), ("humanism", "liberal"))

    def test_the_owner_reads_their_own_politics_back(self):
        self.client.post(PROFILE, {"politics": "centrist"}, format="json")
        self.assertEqual(self.client.get(PROFILE).data["politics"], "centrist")

    def test_nothing_else_writes_the_columns(self):
        """Declared, never inferred: only the two profile writers may assign either column.
        A third writer is how "we detected you lean…" gets in."""
        root = Path(__file__).resolve().parents[1]
        allowed = {"accounts/views.py", "economy/social.py", "economy/models.py"}
        pat = re.compile(r"\.(philosophy|politics)\s*=(?!=)|setattr\([^)]*[\"'](philosophy|politics)[\"']")
        offenders = []
        for f in root.rglob("*.py"):
            rel = str(f.relative_to(root))
            if "/migrations/" in rel or "/test" in rel or rel.split("/")[-1].startswith("test_") or rel in allowed:
                continue
            if pat.search(f.read_text(errors="ignore")):
                offenders.append(rel)
        self.assertEqual(offenders, [])


class SearchTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("searcher", "s@e.com", PW)
        profile_for(self.me)
        self.client = APIClient()
        self.client.force_authenticate(self.me)

    def member(self, name, **fields):
        u = User.objects.create_user(name, f"{name}@e.com", PW)
        p = profile_for(u)
        for k, v in fields.items():
            setattr(p, k, v)
        p.save()
        return u

    def names(self, query):
        return {m["username"] for m in self.client.get(f"{MEMBERS}?{query}").data["members"]}

    def test_philosophy_filters_and_ors(self):
        self.member("a", philosophy="stoicism")
        self.member("b", philosophy="humanism")
        self.member("c", philosophy="nihilism")
        self.assertEqual(self.names("philosophies=stoicism"), {"a"})
        self.assertEqual(self.names("philosophies=stoicism,humanism"), {"a", "b"})

    def test_undeclared_never_matches(self):
        self.member("blank")
        self.assertEqual(self.names("philosophies=stoicism"), set())

    def test_a_private_politics_is_not_found_by_searching_for_it(self):
        # Politics is private by default. If the filter matched it anyway, stepping
        # through the list would read every member's declaration off who appears.
        self.member("hidden", politics="centrist")
        self.assertEqual(self.names("politics=centrist"), set())

    def test_an_opened_politics_is_found(self):
        self.member("open", politics="centrist", visibility={"politics": ["member"]})
        self.assertEqual(self.names("politics=centrist"), {"open"})

    def test_the_card_blanks_a_hidden_politics_and_keeps_an_open_philosophy(self):
        self.member("both", politics="liberal", philosophy="stoicism")
        card = next(m for m in self.client.get(MEMBERS).data["members"] if m["username"] == "both")
        self.assertEqual(card["politics"], "")
        self.assertEqual(card["philosophy"], "stoicism")

    def test_a_hidden_religion_is_no_longer_found_by_the_religion_filter(self):
        # The same oracle, found while building this: the religion filter matched on the
        # column without asking whether the member had hidden it.
        self.member("quiet", religion="catholic", visibility={"religion": ["private"]})
        self.member("loud", religion="catholic")
        self.assertEqual(self.names("religions=catholic"), {"loud"})
