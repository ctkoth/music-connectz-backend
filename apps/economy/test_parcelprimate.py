from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import Wallet
from .parcelprimate import (
    MailCampaign, MailContact, MailList, send_cost, sendgrid_available,
    unsub_token,
)

User = get_user_model()


class ParcelPrimateTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="corey", password="pw12345!", email="c@example.com")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_status_reports_unconfigured_when_no_key(self):
        with override_settings(SENDGRID_API_KEY=""):
            r = self.client.get("/api/economy/parcelprimate/status/")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["sending_available"])
        self.assertTrue(r.data["unavailable_reason"])

    def test_status_reports_configured_when_key_set(self):
        with override_settings(SENDGRID_API_KEY="fake-key"):
            self.assertTrue(sendgrid_available())
            r = self.client.get("/api/economy/parcelprimate/status/")
        self.assertTrue(r.data["sending_available"])
        self.assertIsNone(r.data["unavailable_reason"])

    def test_build_list_and_add_contact_needs_no_key(self):
        with override_settings(SENDGRID_API_KEY=""):
            r = self.client.post("/api/economy/parcelprimate/lists/", {"name": "My Fans"})
            self.assertEqual(r.status_code, 201)
            list_id = r.data["id"]
            r = self.client.post(f"/api/economy/parcelprimate/lists/{list_id}/contacts/",
                                  {"email": "fan@example.com", "name": "Fan"})
            self.assertEqual(r.status_code, 201)

    def test_send_refused_with_no_key(self):
        l = MailList.objects.create(owner=self.user, name="L")
        MailContact.objects.create(mail_list=l, email="a@example.com")
        c = MailCampaign.objects.create(owner=self.user, mail_list=l, subject="Hi", body="Body")
        with override_settings(SENDGRID_API_KEY=""):
            r = self.client.post(f"/api/economy/parcelprimate/campaigns/{c.id}/send/")
        self.assertEqual(r.status_code, 503)
        c.refresh_from_db()
        self.assertEqual(c.status, MailCampaign.STATUS_DRAFT)

    def test_send_succeeds_and_bills_only_past_free_floor(self):
        l = MailList.objects.create(owner=self.user, name="L")
        for i in range(3):
            MailContact.objects.create(mail_list=l, email=f"a{i}@example.com")
        c = MailCampaign.objects.create(owner=self.user, mail_list=l, subject="Hi", body="Body")
        self.assertEqual(send_cost(self.user, 3), 0)  # under the free floor

        class FakeResp:
            status_code = 202
            text = ""
        with override_settings(SENDGRID_API_KEY="fake"), \
             __import__("unittest").mock.patch("requests.post", return_value=FakeResp()):
            r = self.client.post(f"/api/economy/parcelprimate/campaigns/{c.id}/send/")
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.status, MailCampaign.STATUS_SENT)
        self.assertEqual(c.sent_count, 3)

    def test_unsubscribe_flips_the_flag_with_no_auth(self):
        l = MailList.objects.create(owner=self.user, name="L")
        contact = MailContact.objects.create(mail_list=l, email="a@example.com")
        anon = APIClient()
        r = anon.get(f"/api/economy/parcelprimate/unsubscribe/{contact.id}/{unsub_token(contact.id)}/")
        self.assertEqual(r.status_code, 200)
        contact.refresh_from_db()
        self.assertFalse(contact.subscribed)

    def test_unsubscribe_refuses_a_bad_token(self):
        l = MailList.objects.create(owner=self.user, name="L")
        contact = MailContact.objects.create(mail_list=l, email="a@example.com")
        anon = APIClient()
        r = anon.get(f"/api/economy/parcelprimate/unsubscribe/{contact.id}/notarealtoken/")
        self.assertEqual(r.status_code, 400)
        contact.refresh_from_db()
        self.assertTrue(contact.subscribed)

    def test_send_refuses_over_daily_cap(self):
        from .parcelprimate import PARCEL_MAX_SENDS_DAILY, _record_sends
        l = MailList.objects.create(owner=self.user, name="L")
        MailContact.objects.create(mail_list=l, email="a@example.com")
        c = MailCampaign.objects.create(owner=self.user, mail_list=l, subject="Hi", body="Body")
        _record_sends(self.user, PARCEL_MAX_SENDS_DAILY)  # already at the ceiling
        with override_settings(SENDGRID_API_KEY="fake"):
            r = self.client.post(f"/api/economy/parcelprimate/campaigns/{c.id}/send/")
        self.assertEqual(r.status_code, 429)
