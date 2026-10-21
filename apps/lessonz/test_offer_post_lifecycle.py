"""LessonZ: offers and posts can finally be fixed instead of only published,
and three integration points that were always dead are real now.

`_Gate` was `from apps.common.gates import AdultVerifiedOnly`, falling back
to `apps.common.tiergate`, both inside bare `except Exception: pass` — and
`apps.common` has never existed in this codebase, so `_Gate` was plain
`IsAuthenticated` the entire time. `get_user_tier` had the same shape and
always returned "free". `BookingActionView`'s "complete" hooked into
`apps.common.wallet.charge`, equally absent, so a completed lesson never
actually charged the student or paid the teacher. None of the three ever
raised — the except swallowed every one of them.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import TIER_FREE, TIER_STATZ, membership_for, profile_for, wallet_for

from .models import (
    STATUS_ACCEPTED, LessonBooking, LessonOffer, LessonPost, TeacherSkillRating,
    get_user_tier,
)

User = get_user_model()
PW = "hunter2hunter2"


def verified_adult(username, rating_skill=None, rating=8, tier=None):
    u = User.objects.create_user(username, f"{username}@x.test", PW)
    p = profile_for(u)
    p.verified_18plus = True
    p.save(update_fields=["verified_18plus"])
    if rating_skill:
        TeacherSkillRating.objects.create(user=u, skill=rating_skill, rating=rating)
    if tier:
        m = membership_for(u)
        m.tier = tier
        m.save(update_fields=["tier"])
    return u


class AdultVerificationGateTests(TestCase):
    """The claim in models.py's own docstring — "adult-verified only" — is
    finally true. An authenticated-but-unverified member, minor or adult,
    is refused; a verified adult with a qualifying rating is not."""

    def test_an_unverified_member_cannot_publish_an_offer(self):
        u = User.objects.create_user("unverified1", "u1@x.test", PW)
        TeacherSkillRating.objects.create(user=u, skill="singz", rating=9)
        c = APIClient(); c.force_authenticate(u)
        r = c.post("/api/lessonz/offers/", {"skill": "singz", "title": "Voice 101", "price": "20.00"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(LessonOffer.objects.count(), 0)

    def test_an_unverified_member_cannot_even_browse(self):
        u = User.objects.create_user("unverified2", "u2@x.test", PW)
        c = APIClient(); c.force_authenticate(u)
        self.assertEqual(c.get("/api/lessonz/offers/").status_code, 403)

    def test_a_verified_adult_with_a_qualifying_rating_can_publish(self):
        u = verified_adult("teach1", rating_skill="singz")
        c = APIClient(); c.force_authenticate(u)
        r = c.post("/api/lessonz/offers/", {"skill": "singz", "title": "Voice 101", "price": "20.00"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)


class TierDetectionTests(TestCase):
    """get_user_tier used to always answer "free", which meant a StatZ
    member asking for a CallZ lesson was told CallZ is StatZ-exclusive, and
    a Premium/StatZ-only LessonPost was invisible to everyone, paying
    members included."""

    def test_get_user_tier_reads_the_real_membership(self):
        free_u = verified_adult("tierfree")
        statz_u = verified_adult("tierstatz", tier=TIER_STATZ)
        self.assertEqual(get_user_tier(free_u), TIER_FREE)
        self.assertEqual(get_user_tier(statz_u), TIER_STATZ)

    def test_a_real_statz_member_can_book_a_callz_lesson(self):
        teacher = verified_adult("callzteacher", rating_skill="rapz")
        student = verified_adult("callzstudent", tier=TIER_STATZ)
        offer = LessonOffer.objects.create(teacher=teacher, skill="rapz", title="Flow",
                                           price=Decimal("10.00"), callz_ok=True, rating_snapshot=8)
        c = APIClient(); c.force_authenticate(student)
        r = c.post("/api/lessonz/bookings/", {"offer": offer.id, "method": "callz", "hours": "1", "pricing_mode": "per_hour"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_a_free_member_is_still_refused_callz(self):
        teacher = verified_adult("callzteacher2", rating_skill="rapz")
        student = verified_adult("callzstudent2")
        offer = LessonOffer.objects.create(teacher=teacher, skill="rapz", title="Flow",
                                           price=Decimal("10.00"), callz_ok=True, rating_snapshot=8)
        c = APIClient(); c.force_authenticate(student)
        r = c.post("/api/lessonz/bookings/", {"offer": offer.id, "method": "callz", "hours": "1", "pricing_mode": "per_hour"}, format="json")
        self.assertEqual(r.status_code, 403)


class OfferEditTests(TestCase):
    def setUp(self):
        self.teacher = verified_adult("offerteacher", rating_skill="singz")
        self.offer = LessonOffer.objects.create(
            teacher=self.teacher, skill="singz", title="Voice 101",
            description="orig", price=Decimal("20.00"), rating_snapshot=8,
        )
        self.c = APIClient(); self.c.force_authenticate(self.teacher)

    def test_the_teacher_can_fix_a_typo(self):
        r = self.c.patch(f"/api/lessonz/offers/{self.offer.id}/",
                         {"title": "Voice 101: Fixed", "price": "25.00"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.title, "Voice 101: Fixed")
        self.assertEqual(self.offer.price, Decimal("25.00"))

    def test_skill_cannot_be_changed(self):
        r = self.c.patch(f"/api/lessonz/offers/{self.offer.id}/", {"skill": "rapz"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.skill, "singz")

    def test_someone_elses_offer_is_not_found(self):
        stranger = verified_adult("offerstranger")
        c2 = APIClient(); c2.force_authenticate(stranger)
        r = c2.patch(f"/api/lessonz/offers/{self.offer.id}/", {"title": "stolen"}, format="json")
        self.assertEqual(r.status_code, 404)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.title, "Voice 101")

    def test_callz_ok_requires_statz(self):
        r = self.c.patch(f"/api/lessonz/offers/{self.offer.id}/", {"callz_ok": True}, format="json")
        self.assertEqual(r.status_code, 403)
        statz_teacher = verified_adult("offerteacherstatz", rating_skill="singz", tier=TIER_STATZ)
        offer2 = LessonOffer.objects.create(teacher=statz_teacher, skill="singz", title="x",
                                            price=Decimal("5.00"), rating_snapshot=8)
        c2 = APIClient(); c2.force_authenticate(statz_teacher)
        r2 = c2.patch(f"/api/lessonz/offers/{offer2.id}/", {"callz_ok": True}, format="json")
        self.assertEqual(r2.status_code, 200, r2.data)

    def test_cannot_turn_off_both_remote_and_in_person(self):
        r = self.c.patch(f"/api/lessonz/offers/{self.offer.id}/",
                         {"remote_ok": False, "in_person_ok": False}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_patching_nothing_recognised_says_so(self):
        r = self.c.patch(f"/api/lessonz/offers/{self.offer.id}/", {}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_an_existing_bookings_total_is_untouched_by_a_later_price_edit(self):
        student = verified_adult("offerstudent")
        sc = APIClient(); sc.force_authenticate(student)
        b = sc.post("/api/lessonz/bookings/",
                    {"offer": self.offer.id, "hours": "1", "method": "remote", "pricing_mode": "per_hour"}, format="json").data
        self.assertEqual(Decimal(b["agreed_total"]), Decimal("20.00"))
        self.c.patch(f"/api/lessonz/offers/{self.offer.id}/", {"price": "999.00"}, format="json")
        booking = LessonBooking.objects.get(pk=b["id"])
        self.assertEqual(booking.agreed_total, Decimal("20.00"))


class OfferUnpublishTests(TestCase):
    def setUp(self):
        self.teacher = verified_adult("unpubteacher", rating_skill="singz")
        self.offer = LessonOffer.objects.create(teacher=self.teacher, skill="singz", title="x",
                                                price=Decimal("5.00"), rating_snapshot=8)
        self.c = APIClient(); self.c.force_authenticate(self.teacher)

    def test_delete_unpublishes_rather_than_destroying(self):
        r = self.c.delete(f"/api/lessonz/offers/{self.offer.id}/")
        self.assertEqual(r.status_code, 200, r.data)
        self.offer.refresh_from_db()
        self.assertFalse(self.offer.is_active)
        self.assertTrue(LessonOffer.objects.filter(pk=self.offer.id).exists())

    def test_double_unpublish_is_refused(self):
        self.c.delete(f"/api/lessonz/offers/{self.offer.id}/")
        r = self.c.delete(f"/api/lessonz/offers/{self.offer.id}/")
        self.assertEqual(r.status_code, 400)

    def test_mine_shows_an_unpublished_offer_the_public_list_does_not(self):
        self.c.delete(f"/api/lessonz/offers/{self.offer.id}/")
        mine = self.c.get("/api/lessonz/offers/?mine=1").data
        self.assertEqual([o["id"] for o in mine], [self.offer.id])
        public = self.c.get("/api/lessonz/offers/").data
        self.assertEqual(public, [])

    def test_republishing_turns_is_active_back_on(self):
        self.c.delete(f"/api/lessonz/offers/{self.offer.id}/")
        r = self.c.patch(f"/api/lessonz/offers/{self.offer.id}/", {"is_active": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.offer.refresh_from_db()
        self.assertTrue(self.offer.is_active)


class PostEditAndUnpublishTests(TestCase):
    def setUp(self):
        self.teacher = verified_adult("postteacher", rating_skill="singz")
        self.post = LessonPost.objects.create(
            teacher=self.teacher, skill="singz", title="Recorded lesson",
            media_ref="upload:1", price=Decimal("5.00"), rating_snapshot=8,
        )
        self.c = APIClient(); self.c.force_authenticate(self.teacher)

    def test_the_teacher_can_fix_the_title_and_price(self):
        r = self.c.patch(f"/api/lessonz/posts/{self.post.id}/",
                         {"title": "Fixed", "price": "9.00"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.post.refresh_from_db()
        self.assertEqual((self.post.title, self.post.price), ("Fixed", Decimal("9.00")))

    def test_skill_is_locked(self):
        r = self.c.patch(f"/api/lessonz/posts/{self.post.id}/", {"skill": "rapz"}, format="json")
        self.assertEqual(r.status_code, 409)

    def test_someone_elses_post_is_not_found(self):
        stranger = verified_adult("poststranger")
        c2 = APIClient(); c2.force_authenticate(stranger)
        r = c2.patch(f"/api/lessonz/posts/{self.post.id}/", {"title": "stolen"}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_delete_unpublishes_and_mine_still_sees_it(self):
        r = self.c.delete(f"/api/lessonz/posts/{self.post.id}/")
        self.assertEqual(r.status_code, 200, r.data)
        self.post.refresh_from_db()
        self.assertFalse(self.post.is_active)
        mine = self.c.get("/api/lessonz/posts/?mine=1").data
        self.assertEqual([p["id"] for p in mine], [self.post.id])
        public = self.c.get("/api/lessonz/posts/").data
        self.assertEqual(public, [])


class PaymentWiringTests(TestCase):
    """`apps.common.wallet.charge` never existed, so completing a booking
    created a `LessonPayment` row and moved no money at all — it LOOKED
    like it worked."""

    def setUp(self):
        self.teacher = verified_adult("payteacher", rating_skill="singz")
        self.student = verified_adult("paystudent")
        w = wallet_for(self.student)
        w.money_cents = 5000
        w.save(update_fields=["money_cents"])
        self.offer = LessonOffer.objects.create(teacher=self.teacher, skill="singz", title="x",
                                                price=Decimal("20.00"), rating_snapshot=8)
        sc = APIClient(); sc.force_authenticate(self.student)
        b = sc.post("/api/lessonz/bookings/",
                   {"offer": self.offer.id, "hours": "1", "method": "remote", "pricing_mode": "per_hour"}, format="json").data
        self.booking = LessonBooking.objects.get(pk=b["id"])
        tc = APIClient(); tc.force_authenticate(self.teacher)
        tc.post(f"/api/lessonz/bookings/{self.booking.id}/accept/", {}, format="json")
        self.tc = tc

    def test_completing_actually_moves_the_money(self):
        r = self.tc.post(f"/api/lessonz/bookings/{self.booking.id}/complete/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.booking.refresh_from_db()
        payment = self.booking.payment
        self.assertTrue(payment.settled)
        self.assertEqual(wallet_for(self.student).money_cents, 3000)
        self.assertGreater(wallet_for(self.teacher).money_cents, 0)

    def test_completing_with_insufficient_balance_still_completes_unsettled(self):
        w = wallet_for(self.student)
        w.money_cents = 0
        w.save(update_fields=["money_cents"])
        r = self.tc.post(f"/api/lessonz/bookings/{self.booking.id}/complete/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "completed")
        self.assertFalse(self.booking.payment.settled)
