"""What the OCC audit found, pinned so it can't come back.

Three findings, in the order they cost something:

1. Four client-supplied fields reached the model uncapped while the charge was
   flat. The per-message prices in AI_MODELS are worked out for a turn of about
   10,000 input tokens and nothing held anyone to it.
2. Seventeen languages advertised, twelve runnable.
3. Twenty-two tabs, six endpoints, and no way into any of them.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.catalog import (
    OCC_MAX_ACRONYM_CHARS,
    OCC_MAX_ACRONYMS,
    OCC_MAX_HISTORY_CHARS,
    OCC_MAX_HISTORY_TURNS,
    OCC_MAX_KNOWLEDGE_CHARS,
    OCC_MAX_KNOWLEDGE_ITEMS,
    OCC_MAX_PROMPT_CHARS,
    OCC_MAX_TOTAL_CHARS,
)
from apps.economy.models import membership_for, wallet_for

User = get_user_model()
PW = "hunter2hunter2"
OCC = "/api/economy/ai/occ/"


class FakeBlock:
    type = "text"
    def __init__(self, text): self.text = text


def recording_client(seen):
    class C:
        class messages:
            @staticmethod
            def create(**kw):
                seen.append(kw)
                return type("R", (), {"content": [FakeBlock("ok")]})()
    return C


def why(resp):
    """Something readable to hand assertEqual, whatever kind of response it is.

    `resp.data` exists on a DRF response and NOT on a plain Django one — so a
    request refused by the transport (a body over DATA_UPLOAD_MAX_MEMORY_SIZE
    never reaches the view) blew up with `AttributeError: 'HttpResponseBadRequest'
    object has no attribute 'data'` INSIDE the failure message. The test could
    not say what went wrong, which is how a red check sat here being unreadable
    instead of being fixed.
    """
    if hasattr(resp, "data"):
        return resp.data
    return f"{resp.status_code} (no DRF body) {resp.content[:200]!r}"


class Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("occ", "o@e.com", PW)
        membership_for(self.user)
        w = wallet_for(self.user); w.promptz = 5000; w.save()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def ask(self, seen=None, **body):
        seen = seen if seen is not None else []
        fake = type("anthropic", (), {"Anthropic": recording_client(seen)})
        with patch.dict("sys.modules", {"anthropic": fake}):
            return self.client.post(OCC, {"prompt": "hi", **body}, format="json"), seen


class OneMessageHasACeilingTests(Base):
    """Finding 1 — the expensive one.

    Django's default 2.5MB body was the only bound. At Fable's $10 per million
    input tokens that is roughly $6 of tokens for a 15c charge, on the
    platform's own account, repeatable by anyone with a login.
    """

    def test_a_giant_prompt_is_refused_before_the_model_runs(self):
        resp, seen = self.ask(prompt="x" * (OCC_MAX_PROMPT_CHARS + 1))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(seen, [], "the model must not run on a refused message")
        self.assertIn("limits", resp.data)

    # There are TWO ceilings, and only the second one is this app's work:
    #
    #   * the TRANSPORT ceiling — Django refuses a request body over
    #     DATA_UPLOAD_MAX_MEMORY_SIZE (2.5MiB by default) before any view runs.
    #     Pinned in TheTransportCeilingTests below.
    #   * the BUDGET — OCC_MAX_TOTAL_CHARS, the assembled prompt the per-message
    #     price was worked out for. That is what these tests are about.
    #
    # The smuggling payloads below are therefore sized to fit COMFORTABLY inside
    # the transport ceiling while sitting far outside the budget. They used to
    # be 4MB, which never reached the guard at all: Django bounced the request,
    # the test read `.data` off a plain HttpResponseBadRequest, and the guard
    # these tests exist to prove has not actually been exercised since.
    #
    # Sizes come off the caps rather than being round megabytes — the axis that
    # matters here is "how many times over the budget", not "how many MB".

    def test_taught_knowledge_cannot_be_used_as_a_smuggling_route(self):
        # 200 items — ten times the item cap — each five times the per-item cap.
        # ~2MB on the wire, fifty times the assembled budget.
        resp, seen = self.ask(
            knowledge=[{"course": "c", "text": "x" * (OCC_MAX_KNOWLEDGE_CHARS * 5)}
                       for _ in range(OCC_MAX_KNOWLEDGE_ITEMS * 10)])
        self.assertEqual(resp.status_code, 200, why(resp))
        self.assertLessEqual(len(seen[0]["system"]), OCC_MAX_TOTAL_CHARS)

    def test_acronyms_cannot_either(self):
        resp, seen = self.ask(
            acronyms=[{"term": "t" * (OCC_MAX_ACRONYM_CHARS * 40),
                       "means": "m" * (OCC_MAX_ACRONYM_CHARS * 40)}
                      for _ in range(OCC_MAX_ACRONYMS * 4)])
        self.assertEqual(resp.status_code, 200, why(resp))
        self.assertLessEqual(len(seen[0]["system"]), OCC_MAX_TOTAL_CHARS)

    def test_nor_can_history(self):
        # Was 50 turns of 50k — 2.5MB, close enough to the transport ceiling
        # that one more zero anywhere would have made this fail the same
        # unreadable way its neighbour did.
        resp, seen = self.ask(
            history=[{"role": "user", "text": "x" * (OCC_MAX_HISTORY_CHARS * 5)}
                     for _ in range(OCC_MAX_HISTORY_TURNS * 6)])
        self.assertEqual(resp.status_code, 200, why(resp))
        total = len(seen[0]["system"]) + sum(len(m["content"]) for m in seen[0]["messages"])
        self.assertLessEqual(total, OCC_MAX_TOTAL_CHARS * 1.1)

    def test_the_whole_assembled_prompt_stays_inside_the_budget(self):
        # Every route at once — each under its own cap, ruinous together.
        resp, seen = self.ask(
            prompt="p" * (OCC_MAX_PROMPT_CHARS - 1),
            knowledge=[{"course": "c", "text": "k" * 1_999} for _ in range(OCC_MAX_KNOWLEDGE_ITEMS)],
            acronyms=[{"term": "t" * 100, "means": "m" * 100} for _ in range(OCC_MAX_ACRONYMS)],
            history=[{"role": "user", "text": "h" * 3_999} for _ in range(OCC_MAX_HISTORY_TURNS)],
        )
        self.assertEqual(resp.status_code, 200, why(resp))
        kw = seen[0]
        total = len(kw["system"]) + sum(len(m["content"]) for m in kw["messages"])
        self.assertLessEqual(total, OCC_MAX_TOTAL_CHARS * 1.1,
                             "the price assumes ~10k input tokens; this exceeds it")

    def test_dropping_history_is_said_out_loud(self):
        # Silently forgetting the start of a conversation is worse than
        # forgetting it out loud.
        resp, _ = self.ask(
            prompt="p" * (OCC_MAX_PROMPT_CHARS - 1),
            knowledge=[{"course": "c", "text": "k" * 1_999} for _ in range(OCC_MAX_KNOWLEDGE_ITEMS)],
            history=[{"role": "user", "text": "x" * 4_000} for _ in range(OCC_MAX_HISTORY_TURNS)])
        self.assertEqual(resp.status_code, 200, why(resp))
        self.assertGreater(resp.data.get("history_trimmed", 0), 0)

    def test_an_ordinary_message_is_untouched(self):
        resp, seen = self.ask(prompt="how do I mix vocals?",
                              history=[{"role": "user", "text": "hey"}])
        self.assertEqual(resp.status_code, 200, why(resp))
        self.assertNotIn("history_trimmed", resp.data)
        self.assertIn("how do I mix vocals?",
                      [m["content"] for m in seen[0]["messages"]])

    def test_the_caps_are_published_where_the_prices_are(self):
        # A per-message price only means something next to the size it was
        # worked out for.
        limits = self.client.get("/api/economy/ai/models/").data["limits"]
        self.assertEqual(limits["prompt_chars"], OCC_MAX_PROMPT_CHARS)
        self.assertEqual(limits["total_chars"], OCC_MAX_TOTAL_CHARS)


class TheTransportCeilingTests(Base):
    """The other ceiling — the one that isn't OCC's.

    Django refuses a request body over DATA_UPLOAD_MAX_MEMORY_SIZE before any
    view runs, so nothing the audit above pinned can be reached with a payload
    that big. That is worth having written down: the knowledge test was firing
    at this wall and reporting an AttributeError, which reads like a broken app
    rather than a request that was never allowed in — and an unreadable red
    check is how the next real failure gets waved through.

    What it means in practice: OCC's own guard has to survive everything UNDER
    2.5MiB, because that is the largest thing that can ever get to it. The
    tests above are sized on that basis.
    """

    def test_a_body_over_the_transport_ceiling_never_reaches_the_view(self):
        from django.conf import settings

        cap = getattr(settings, "DATA_UPLOAD_MAX_MEMORY_SIZE", 2_621_440)
        resp, seen = self.ask(knowledge=[{"course": "c", "text": "x" * (cap // 2)}
                                         for _ in range(3)])
        self.assertEqual(resp.status_code, 400)
        # The point of the ceiling: the model must not run on a message the
        # server never accepted.
        self.assertEqual(seen, [], "the model must not run on a refused body")

    def test_the_guard_still_holds_at_the_largest_body_that_can_get_through(self):
        """Just inside the transport ceiling is the real worst case."""
        from django.conf import settings

        cap = getattr(settings, "DATA_UPLOAD_MAX_MEMORY_SIZE", 2_621_440)
        # 80% of the ceiling in taught knowledge — the biggest smuggle the
        # transport will actually carry.
        each = int(cap * 0.8) // 20
        resp, seen = self.ask(knowledge=[{"course": "c", "text": "x" * each}
                                         for _ in range(20)])
        self.assertEqual(resp.status_code, 200, why(resp))
        self.assertLessEqual(len(seen[0]["system"]), OCC_MAX_TOTAL_CHARS)


class WhatOccSaysItCanRunTests(Base):
    """Finding 2 — seventeen advertised, twelve runnable."""

    def test_every_language_says_whether_the_sandbox_runs_it(self):
        from apps.economy.occ_spec import languages_with_run_status
        for lang in languages_with_run_status():
            self.assertIn("runs", lang, lang["key"])

    def test_the_run_flag_is_derived_not_typed(self):
        from apps.economy.modal_sandbox import RUNNERS
        from apps.economy.occ_spec import languages_with_run_status
        for lang in languages_with_run_status():
            self.assertEqual(lang["runs"], lang["key"] in RUNNERS, lang["key"])

    def test_the_five_write_only_languages_are_marked_as_such(self):
        from apps.economy.occ_spec import languages_with_run_status
        by_key = {l["key"]: l for l in languages_with_run_status()}
        for key in ("csharp", "gdscript", "swift", "haxe", "gml"):
            self.assertFalse(by_key[key]["runs"],
                             f"{key} has no runner — the pill must not imply one")

    def test_the_run_picker_only_ever_offers_what_runs(self):
        # This was already right and is pinned so it stays right: the picker
        # draws from RUNNERS, so nothing selectable can fail as unsupported.
        from apps.economy.modal_sandbox import RUNNERS
        st = self.client.get("/api/economy/occ/run/").data
        self.assertEqual(set(st["languages"]), set(RUNNERS))


class EveryTabGoesSomewhereTests(Base):
    """Finding 3 — a list you could read and not enter."""

    def tabs(self):
        return self.client.get("/api/economy/occ/spec/").data["tabs"]

    def test_tabs_say_where_they_open(self):
        linked = [t for t in self.tabs() if t.get("open_in")]
        self.assertGreaterEqual(len(linked), 12,
                                "most tabs map to a screen that already exists")

    def test_they_only_point_at_screens_the_client_actually_has(self):
        # An open_in nobody can navigate to is the dead end with extra steps.
        navigable = {"occ", "social", "habitz", "logz", "profilez", "postz",
                     "collabz", "battlez", "messagez", "playlistz", "keyconnectz",
                     "singz", "rapz", "labelz", "groupz", "directz", "mimez",
                     "lessonz", "specz", "membershipz", "adz", "offerz", "bugz",
                     "onboardz"}
        for t in self.tabs():
            if t.get("open_in"):
                self.assertIn(t["open_in"], navigable, t["key"])

    def test_the_four_observationz_tabs_land_on_the_screen_that_serves_them(self):
        # CodeZ, PathZ and MistakeZ are ObservationZ kinds — the HabitZ screen
        # already renders all four. Four tabs, one existing app, no new build.
        by_key = {t["key"]: t for t in self.tabs()}
        for key in ("habitz", "codez", "pathz", "mistakez"):
            self.assertEqual(by_key[key]["open_in"], "habitz", key)

    def test_the_spec_still_says_what_stands_behind_each_tab(self):
        # `builds` was put there on purpose — "a menu that offers twenty tabs
        # and delivers three is worse than a menu that offers three". It must
        # keep shipping; the client not reading it was the bug, not its presence.
        for t in self.tabs():
            self.assertIn("builds", t, t["key"])


class TheVisionImageHasACeilingToo(Base):
    """The field the audit missed, found while testing the fields it didn't.

    Same two holes as everywhere else: an unbounded client-supplied size, and a
    client-supplied media type handed straight to the API — which is exactly
    what made the Boss Take coach refuse every Chrome recording.
    """

    def png(self, b64_len=100, media="image/png"):
        return f"data:{media};base64," + ("A" * b64_len)

    def test_an_ordinary_image_still_goes_through(self):
        resp, seen = self.ask(image=self.png())
        self.assertEqual(resp.status_code, 200, why(resp))
        block = seen[0]["messages"][-1]["content"][0]
        self.assertEqual(block["source"]["media_type"], "image/png")

    def test_an_enormous_image_is_refused_before_the_model_runs(self):
        from apps.economy.catalog import OCC_MAX_IMAGE_B64
        resp, seen = self.ask(image=self.png(OCC_MAX_IMAGE_B64 + 1))
        self.assertEqual(resp.status_code, 413)
        self.assertEqual(seen, [])

    def test_a_media_type_the_model_cannot_read_is_named_not_forwarded(self):
        resp, seen = self.ask(image=self.png(media="image/tiff"))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("tiff", resp.data["detail"])
        self.assertEqual(seen, [], "an unreadable type must never reach the API")

    def test_a_made_up_media_type_cannot_be_smuggled_through(self):
        resp, seen = self.ask(image=self.png(media="anything/goes"))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(seen, [])
