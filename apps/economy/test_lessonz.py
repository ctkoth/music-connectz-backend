"""Tests for LessonZ — Lesson Marketplace (Path 3 monetization)."""
from datetime import timedelta
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from .models import CoachProfile, CoachReview, Call, TIER_FREE, TIER_PREMIUM, Membership, Wallet

User = get_user_model()


class CoachProfileTests(TestCase):
    """Test coach profile creation and management."""

    def setUp(self):
        self.coach = User.objects.create_user(
            username="coach", email="coach@test.com", password="pw"
        )
        Membership.objects.create(user=self.coach, tier=TIER_FREE)
        Wallet.objects.create(user=self.coach)

        self.student = User.objects.create_user(
            username="student", email="student@test.com", password="pw"
        )
        Membership.objects.create(user=self.student, tier=TIER_FREE)
        Wallet.objects.create(user=self.student)

        self.client = APIClient()

    def test_coach_profile_auto_create(self):
        """Test that coach profile is auto-created on first access."""
        self.client.force_authenticate(user=self.coach)
        response = self.client.patch("/api/economy/lessonz/profile/", {
            "lesson_rate_cents_per_min": 100,
            "bio": "Voice coach with 10 years experience"
        }, format='json')
        if response.status_code != status.HTTP_200_OK:
            print(f"Response: {response.data}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(CoachProfile.objects.filter(user=self.coach).exists())

    def test_update_lesson_rate(self):
        """Test updating lesson rate."""
        CoachProfile.objects.create(user=self.coach, lesson_rate_cents_per_min=100)

        self.client.force_authenticate(user=self.coach)
        response = self.client.patch("/api/economy/lessonz/profile/", {
            "lesson_rate_cents_per_min": 200
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["lesson_rate_cents_per_min"], 200)

        profile = CoachProfile.objects.get(user=self.coach)
        self.assertEqual(profile.lesson_rate_cents_per_min, 200)

    def test_invalid_lesson_rate(self):
        """Test that invalid rates are rejected."""
        CoachProfile.objects.create(user=self.coach)

        self.client.force_authenticate(user=self.coach)
        response = self.client.patch("/api/economy/lessonz/profile/", {
            "lesson_rate_cents_per_min": -100  # negative rate invalid
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_bio(self):
        """Test updating coach bio."""
        CoachProfile.objects.create(user=self.coach, bio="")

        self.client.force_authenticate(user=self.coach)
        bio_text = "Expert vocal coach specializing in R&B and soul"
        response = self.client.patch("/api/economy/lessonz/profile/", {
            "bio": bio_text
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        profile = CoachProfile.objects.get(user=self.coach)
        self.assertEqual(profile.bio, bio_text)

    def test_bio_max_length(self):
        """Test that bio is capped at 500 characters."""
        CoachProfile.objects.create(user=self.coach)

        self.client.force_authenticate(user=self.coach)
        bio_text = "x" * 600
        response = self.client.patch("/api/economy/lessonz/profile/", {
            "bio": bio_text
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        profile = CoachProfile.objects.get(user=self.coach)
        self.assertEqual(len(profile.bio), 500)

    def test_get_coach_profile(self):
        """Test retrieving coach profile."""
        profile = CoachProfile.objects.create(
            user=self.coach,
            lesson_rate_cents_per_min=150,
            bio="Professional coach",
            verified_lesson_count=5
        )

        self.client.force_authenticate(user=self.coach)
        response = self.client.get("/api/economy/lessonz/profile/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["lesson_rate_cents_per_min"], 150)
        self.assertEqual(response.data["bio"], "Professional coach")
        self.assertEqual(response.data["verified_lesson_count"], 5)

    def test_get_nonexistent_coach_profile(self):
        """Test that non-coaches get 404."""
        self.client.force_authenticate(user=self.student)
        response = self.client.get("/api/economy/lessonz/profile/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class CoachReviewTests(TestCase):
    """Test coach reviews from students."""

    def setUp(self):
        self.coach = User.objects.create_user(
            username="coach", email="coach@test.com", password="pw"
        )
        Membership.objects.create(user=self.coach, tier=TIER_FREE)
        Wallet.objects.create(user=self.coach)
        CoachProfile.objects.create(user=self.coach)

        self.student1 = User.objects.create_user(
            username="student1", email="student1@test.com", password="pw"
        )
        Membership.objects.create(user=self.student1, tier=TIER_FREE)
        Wallet.objects.create(user=self.student1)

        self.student2 = User.objects.create_user(
            username="student2", email="student2@test.com", password="pw"
        )
        Membership.objects.create(user=self.student2, tier=TIER_FREE)
        Wallet.objects.create(user=self.student2)

        self.client = APIClient()

    def test_create_review_after_lesson(self):
        """Test student can review coach after completed lesson."""
        # Create a completed call
        lesson = Call.objects.create(
            caller=self.student1,
            callee=self.coach,
            status=Call.STATUS_ENDED,
            rate_cents_per_min=100,
            billed_seconds=600
        )

        self.client.force_authenticate(user=self.student1)
        response = self.client.post("/api/economy/lessonz/review/", {
            "coach_id": self.coach.id,
            "rating": 5,
            "text": "Great coach, very helpful!"
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        review = CoachReview.objects.get(coach=self.coach, student=self.student1)
        self.assertEqual(review.rating, 5)
        self.assertEqual(review.text, "Great coach, very helpful!")

    def test_cannot_review_without_lesson(self):
        """Test that students can't review coaches they haven't had a lesson with."""
        self.client.force_authenticate(user=self.student1)
        response = self.client.post("/api/economy/lessonz/review/", {
            "coach_id": self.coach.id,
            "rating": 5,
            "text": "Great coach"
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_update_review(self):
        """Test that re-reviewing replaces the old review."""
        Call.objects.create(
            caller=self.student1,
            callee=self.coach,
            status=Call.STATUS_ENDED,
            rate_cents_per_min=100
        )

        self.client.force_authenticate(user=self.student1)

        # First review
        response1 = self.client.post("/api/economy/lessonz/review/", {
            "coach_id": self.coach.id,
            "rating": 3,
            "text": "Good"
        }, format="json")
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)

        # Update review
        response2 = self.client.post("/api/economy/lessonz/review/", {
            "coach_id": self.coach.id,
            "rating": 5,
            "text": "Excellent!"
        }, format="json")
        self.assertEqual(response2.status_code, status.HTTP_200_OK)

        # Should only have one review
        reviews = CoachReview.objects.filter(coach=self.coach, student=self.student1)
        self.assertEqual(reviews.count(), 1)
        self.assertEqual(reviews.first().rating, 5)

    def test_invalid_rating(self):
        """Test that invalid ratings are rejected."""
        Call.objects.create(
            caller=self.student1,
            callee=self.coach,
            status=Call.STATUS_ENDED
        )

        self.client.force_authenticate(user=self.student1)

        # Rating too high
        response = self.client.post("/api/economy/lessonz/review/", {
            "coach_id": self.coach.id,
            "rating": 10
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Rating too low
        response = self.client.post("/api/economy/lessonz/review/", {
            "coach_id": self.coach.id,
            "rating": 0
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_get_coach_reviews(self):
        """Test retrieving all reviews for a coach."""
        # Create lessons and reviews from both students
        for student in [self.student1, self.student2]:
            Call.objects.create(
                caller=student,
                callee=self.coach,
                status=Call.STATUS_ENDED
            )
            CoachReview.objects.create(
                coach=self.coach,
                student=student,
                rating=5,
                text=f"Review from {student.username}"
            )

        response = self.client.get(f"/api/economy/lessonz/coach/{self.coach.id}/reviews/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["review_count"], 2)
        self.assertEqual(response.data["average_rating"], 5.0)

    def test_average_rating_calculation(self):
        """Test that average rating is calculated correctly."""
        Call.objects.create(
            caller=self.student1,
            callee=self.coach,
            status=Call.STATUS_ENDED
        )
        Call.objects.create(
            caller=self.student2,
            callee=self.coach,
            status=Call.STATUS_ENDED
        )

        CoachReview.objects.create(
            coach=self.coach, student=self.student1, rating=4
        )
        CoachReview.objects.create(
            coach=self.coach, student=self.student2, rating=5
        )

        response = self.client.get(f"/api/economy/lessonz/coach/{self.coach.id}/reviews/")
        self.assertEqual(response.data["average_rating"], 4.5)


class CoachListingTests(TestCase):
    """Test listing coaches."""

    def setUp(self):
        self.coach1 = User.objects.create_user(
            username="coach1", email="coach1@test.com", password="pw"
        )
        Membership.objects.create(user=self.coach1, tier=TIER_FREE)
        Wallet.objects.create(user=self.coach1)
        self.profile1 = CoachProfile.objects.create(
            user=self.coach1,
            lesson_rate_cents_per_min=100,
            verified_lesson_count=3
        )

        self.coach2 = User.objects.create_user(
            username="coach2", email="coach2@test.com", password="pw"
        )
        Membership.objects.create(user=self.coach2, tier=TIER_PREMIUM)
        Wallet.objects.create(user=self.coach2)
        self.profile2 = CoachProfile.objects.create(
            user=self.coach2,
            lesson_rate_cents_per_min=200,
            verified_lesson_count=5
        )

        self.unverified_coach = User.objects.create_user(
            username="unverified", email="unverified@test.com", password="pw"
        )
        Membership.objects.create(user=self.unverified_coach, tier=TIER_FREE)
        Wallet.objects.create(user=self.unverified_coach)
        CoachProfile.objects.create(
            user=self.unverified_coach,
            verified_lesson_count=0  # No lessons
        )

        self.client = APIClient()

    def test_list_coaches_excludes_unverified(self):
        """Test that coaches with no lessons don't appear in listing."""
        response = self.client.get("/api/economy/lessonz/coaches/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        coach_ids = [c["coach_id"] for c in response.data["coaches"]]
        self.assertIn(self.coach1.id, coach_ids)
        self.assertIn(self.coach2.id, coach_ids)
        self.assertNotIn(self.unverified_coach.id, coach_ids)

    def test_sort_by_lessons(self):
        """Test sorting coaches by verified lesson count."""
        response = self.client.get("/api/economy/lessonz/coaches/?sort=lessons")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        coaches = response.data["coaches"]
        # coach2 (5 lessons) should come before coach1 (3 lessons)
        self.assertEqual(coaches[0]["coach_id"], self.coach2.id)
        self.assertEqual(coaches[1]["coach_id"], self.coach1.id)

    def test_featured_coaches(self):
        """Test filtering for featured coaches only."""
        # Mark coach1 as featured
        self.profile1.featured_until = timezone.now() + timedelta(days=7)
        self.profile1.save()

        response = self.client.get("/api/economy/lessonz/coaches/?featured=true")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        coach_ids = [c["coach_id"] for c in response.data["coaches"]]
        self.assertIn(self.coach1.id, coach_ids)
        self.assertNotIn(self.coach2.id, coach_ids)

    def test_featured_coaches_expired(self):
        """Test that expired featured placements are not shown."""
        # Mark coach2 as featured but expired
        self.profile2.featured_until = timezone.now() - timedelta(days=1)
        self.profile2.save()

        response = self.client.get("/api/economy/lessonz/coaches/?featured=true")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        coach_ids = [c["coach_id"] for c in response.data["coaches"]]
        self.assertNotIn(self.coach2.id, coach_ids)

    def test_coach_profile_in_listing(self):
        """Test that coach profile data is included in listing."""
        response = self.client.get("/api/economy/lessonz/coaches/")

        coach_data = next(c for c in response.data["coaches"] if c["coach_id"] == self.coach1.id)
        self.assertEqual(coach_data["lesson_rate_cents_per_min"], 100)
        self.assertEqual(coach_data["verified_lesson_count"], 3)


class CoachAverageRatingTests(TestCase):
    """Test coach average rating computation."""

    def setUp(self):
        self.coach = User.objects.create_user(
            username="coach", email="coach@test.com", password="pw"
        )
        Membership.objects.create(user=self.coach, tier=TIER_FREE)
        Wallet.objects.create(user=self.coach)
        self.profile = CoachProfile.objects.create(user=self.coach)

    def test_average_rating_none_without_reviews(self):
        """Test that average rating is None when no reviews exist."""
        self.assertIsNone(self.profile.average_rating)

    def test_average_rating_single_review(self):
        """Test average rating with one review."""
        student = User.objects.create_user(username="student", password="pw")
        CoachReview.objects.create(coach=self.coach, student=student, rating=4)

        self.assertEqual(self.profile.average_rating, 4.0)

    def test_average_rating_multiple_reviews(self):
        """Test average rating with multiple reviews."""
        for i in range(3):
            student = User.objects.create_user(username=f"student{i}", password="pw")
            CoachReview.objects.create(
                coach=self.coach, student=student, rating=3 + i  # 3, 4, 5
            )

        self.assertEqual(self.profile.average_rating, 4.0)

    def test_average_rating_all_five_stars(self):
        """Test average rating when all reviews are 5 stars."""
        for i in range(5):
            student = User.objects.create_user(username=f"student{i}", password="pw")
            CoachReview.objects.create(
                coach=self.coach, student=student, rating=5
            )

        self.assertEqual(self.profile.average_rating, 5.0)
