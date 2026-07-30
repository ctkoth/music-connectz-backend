from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.catalog import chars_unlimited, limits_for
from apps.economy.models import (TIER_FREE, TIER_PREMIUM, TIER_STATZ,
                                 Message, membership_for)

User = get_user_model()


class CharLimitTests(TestCase):
    def test_free_and_premium_keep_their_caps(self):
        self.assertEqual(limits_for(TIER_FREE)["char_limit"], 400)
        self.assertEqual(limits_for(TIER_PREMIUM)["char_limit"], 1500)
        self.assertFalse(chars_unlimited(TIER_FREE))
        self.assertFalse(chars_unlimited(TIER_PREMIUM))

    def test_statz_is_unlimited(self):
        self.assertTrue(chars_unlimited(TIER_STATZ))


class MessageCapTests(TestCase):
    """The cap is enforced on send, so this is where unlimited has to hold."""

    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("me", "me@e.com", "pw12345678")
        self.peer = User.objects.create_user("peer", "peer@e.com", "pw12345678")
        self.client.force_authenticate(self.me)

    def _tier(self, tier):
        m = membership_for(self.me)
        m.tier = tier
        m.save(update_fields=["tier", "updated_at"])

    def test_free_still_refused_past_400(self):
        self._tier(TIER_FREE)
        resp = self.client.post("/api/economy/messages/",
                                {"to": "peer", "body": "x" * 401}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("400-character limit", resp.data["detail"])

    def test_statz_sends_far_past_the_old_5000_cap(self):
        self._tier(TIER_STATZ)
        body = "x" * 50_000
        resp = self.client.post("/api/economy/messages/",
                                {"to": "peer", "body": body}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        # and it is stored whole, not silently truncated
        self.assertEqual(len(Message.objects.get(sender=self.me).body), 50_000)

    def test_limits_endpoint_flags_unlimited_for_the_client(self):
        self._tier(TIER_STATZ)
        data = self.client.get("/api/economy/limits/").data
        self.assertTrue(data["char_limit_unlimited"])
        self._tier(TIER_PREMIUM)
        data = self.client.get("/api/economy/limits/").data
        self.assertFalse(data["char_limit_unlimited"])
        self.assertEqual(data["char_limit"], 1500)


class DailyPromptTests(TestCase):
    """The free allowance, and the bug where OCC chat never applied it."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("m", "m@e.com", "pw12345678")
        self.client.force_authenticate(self.user)

    def _tier(self, tier):
        m = membership_for(self.user)
        m.tier = tier
        m.save(update_fields=["tier", "updated_at"])

    def test_the_allowance_by_tier(self):
        from apps.economy.models import PROMPT_ALLOWANCE, daily_prompt_state

        self.assertEqual(PROMPT_ALLOWANCE[TIER_FREE], 3)
        self.assertEqual(PROMPT_ALLOWANCE[TIER_PREMIUM], 10)
        self.assertEqual(PROMPT_ALLOWANCE[TIER_STATZ], 20)
        self._tier(TIER_FREE)
        self.assertEqual(daily_prompt_state(self.user)[0], 3)
        self._tier(TIER_PREMIUM)
        self.assertEqual(daily_prompt_state(self.user)[0], 10)

    def test_a_broke_member_can_still_afford_a_run_from_the_daily_allowance(self):
        """The check and the charge have to agree about what counts. They didn't:
        can_afford_ai ignored the allowance, so a free member with three free
        prompts and no balance was turned away from a free run."""
        from apps.economy.models import can_afford_ai, wallet_for

        self._tier(TIER_FREE)
        w = wallet_for(self.user)
        w.money_cents = 0
        w.promptz = 0
        w.save()
        self.assertFalse(can_afford_ai(self.user, 1))                     # cash only
        self.assertTrue(can_afford_ai(self.user, 1, count_daily=True))    # with today's

    def test_the_allowance_runs_out_and_then_cash_is_required(self):
        from apps.economy.models import (can_afford_ai, charge_ai_usage,
                                         daily_prompt_state, wallet_for)

        self._tier(TIER_FREE)
        w = wallet_for(self.user)
        w.money_cents = 0
        w.promptz = 0
        w.save()
        for _ in range(3):
            charge_ai_usage(self.user, 1, note="test", count_daily=True)
        self.assertEqual(daily_prompt_state(self.user)[2], 0)
        self.assertFalse(can_afford_ai(self.user, 1, count_daily=True))

    def test_a_free_prompt_costs_no_cash(self):
        from apps.economy.models import charge_ai_usage, wallet_for

        self._tier(TIER_FREE)
        w = wallet_for(self.user)
        w.money_cents = 500
        w.save()
        charge_ai_usage(self.user, 1, note="test", count_daily=True)
        self.assertEqual(wallet_for(self.user).money_cents, 500)

    def test_occ_chat_spends_a_daily_prompt_rather_than_cash(self):
        from unittest.mock import patch

        from apps.economy.models import daily_prompt_state, wallet_for

        self._tier(TIER_FREE)
        w = wallet_for(self.user)
        w.money_cents = 0
        w.promptz = 0
        w.save()

        class _B:
            type, text = "text", "🔥 here you go"

        class _R:
            content = [_B()]

        with patch("apps.economy.occ._create_with_fallback", return_value=_R()), \
                patch("anthropic.Anthropic"):
            resp = self.client.post("/api/economy/ai/occ/", {"prompt": "hi"},
                                    format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["charged_cents"], 0)
        self.assertEqual(resp.data["daily_prompts"]["remaining"], 2)
        self.assertEqual(daily_prompt_state(self.user)[1], 1)

    def test_the_owner_is_not_credited_for_a_run_nobody_paid_for(self):
        """Crediting the owner for a free daily prompt would mint revenue."""
        from unittest.mock import patch

        from apps.economy.models import wallet_for
        from apps.economy.views import platform_owner

        self._tier(TIER_FREE)
        owner = User.objects.create_user("K-Oth", "ctkoth@gmail.com", "pw12345678")
        owner.is_superuser = True
        owner.save()
        before = wallet_for(owner).money_cents

        class _B:
            type, text = "text", "hey"

        class _R:
            content = [_B()]

        with patch("apps.economy.occ._create_with_fallback", return_value=_R()), \
                patch("anthropic.Anthropic"):
            self.client.post("/api/economy/ai/occ/", {"prompt": "hi"}, format="json")
        self.assertEqual(wallet_for(owner).money_cents, before)
