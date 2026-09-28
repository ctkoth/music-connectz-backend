"""Tests for Path 4: BeatZ beat/stem licensing."""
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status

from apps.economy.models import BeatZ, BeatPurchase, BeatUsage, Wallet, Membership, TIER_FREE

User = get_user_model()


class BeatListTests(APITestCase):
    """Test beat listing and creation."""

    def setUp(self):
        self.client = APIClient()
        self.producer1 = User.objects.create_user(
            username="producer1",
            email="producer1@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.producer1, tier=TIER_FREE)
        Wallet.objects.create(user=self.producer1, spinaz=5000)
        self.producer2 = User.objects.create_user(
            username="producer2",
            email="producer2@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.producer2, tier=TIER_FREE)
        Wallet.objects.create(user=self.producer2, spinaz=5000)
        self.buyer = User.objects.create_user(
            username="buyer",
            email="buyer@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.buyer, tier=TIER_FREE)
        Wallet.objects.create(user=self.buyer, spinaz=10000)

        self.beat1 = BeatZ.objects.create(
            producer=self.producer1,
            title="Test Beat 1",
            description="A test beat",
            genre="hip-hop",
            tempo_bpm=90,
            price_cents=500,
            license_type=BeatZ.LICENSE_NONEXCLUSIVE,
        )

        self.beat2 = BeatZ.objects.create(
            producer=self.producer2,
            title="Test Beat 2",
            description="Another beat",
            genre="trap",
            tempo_bpm=140,
            price_cents=800,
            license_type=BeatZ.LICENSE_EXCLUSIVE,
            quantity_available=1
        )

    def test_list_beats(self):
        """Get list of all beats."""
        self.client.force_authenticate(user=self.buyer)
        response = self.client.get("/api/economy/beatz/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["beats"]), 2)
        self.assertTrue(response.data["beats"][0]["owned_by_me"] is False)

    def test_filter_beats_by_genre(self):
        """Filter beats by genre."""
        self.client.force_authenticate(user=self.buyer)
        response = self.client.get("/api/economy/beatz/?genre=hip-hop")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["beats"]), 1)
        self.assertEqual(response.data["beats"][0]["genre"], "hip-hop")

    def test_filter_beats_by_producer(self):
        """Filter beats by producer."""
        self.client.force_authenticate(user=self.buyer)
        response = self.client.get(f"/api/economy/beatz/?producer_id={self.producer1.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["beats"]), 1)
        self.assertEqual(response.data["beats"][0]["producer_id"], self.producer1.id)

    def test_create_beat(self):
        """Producer creates a new beat."""
        self.client.force_authenticate(user=self.producer1)
        data = {
            "title": "New Beat",
            "description": "A new beat",
            "genre": "electronic",
            "tempo_bpm": 120,
            "price_cents": 600,
            "license_type": BeatZ.LICENSE_NONEXCLUSIVE,
        }
        response = self.client.post("/api/economy/beatz/", data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "New Beat")
        self.assertEqual(response.data["producer_id"], self.producer1.id)

    def test_create_beat_missing_title(self):
        """Create beat without title should fail."""
        self.client.force_authenticate(user=self.producer1)
        data = {
            "genre": "electronic",
            "tempo_bpm": 120,
            "price_cents": 600,
        }
        response = self.client.post("/api/economy/beatz/", data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_beat_missing_price(self):
        """Create beat without price should fail."""
        self.client.force_authenticate(user=self.producer1)
        data = {
            "title": "New Beat",
            "genre": "electronic",
            "tempo_bpm": 120,
        }
        response = self.client.post("/api/economy/beatz/", data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_exclusive_beat(self):
        """Create exclusive beat sets quantity_available to 1."""
        self.client.force_authenticate(user=self.producer1)
        data = {
            "title": "Exclusive Beat",
            "genre": "funk",
            "tempo_bpm": 110,
            "price_cents": 2000,
            "license_type": BeatZ.LICENSE_EXCLUSIVE,
        }
        response = self.client.post("/api/economy/beatz/", data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["license_type"], BeatZ.LICENSE_EXCLUSIVE)
        self.assertEqual(response.data["quantity_available"], 1)


class BeatDetailTests(APITestCase):
    """Test beat details and updates."""

    def setUp(self):
        self.client = APIClient()
        self.producer = User.objects.create_user(
            username="producer",
            email="producer@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.producer, tier=TIER_FREE)
        Wallet.objects.create(user=self.producer, spinaz=5000)
        self.other_user = User.objects.create_user(
            username="other",
            email="other@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.other_user, tier=TIER_FREE)
        Wallet.objects.create(user=self.other_user, spinaz=5000)

        self.beat = BeatZ.objects.create(
            producer=self.producer,
            title="Test Beat",
            description="A test beat",
            genre="hip-hop",
            tempo_bpm=90,
            price_cents=500,
            license_type=BeatZ.LICENSE_NONEXCLUSIVE,
        )

    def test_get_beat_details(self):
        """Get details of a specific beat."""
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(f"/api/economy/beatz/{self.beat.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Test Beat")
        self.assertEqual(response.data["id"], self.beat.id)

    def test_get_nonexistent_beat(self):
        """Get nonexistent beat should 404."""
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get("/api/economy/beatz/9999/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_beat_as_producer(self):
        """Producer can update their own beat."""
        self.client.force_authenticate(user=self.producer)
        data = {
            "title": "Updated Beat",
            "tempo_bpm": 95,
        }
        response = self.client.patch(f"/api/economy/beatz/{self.beat.id}/", data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Updated Beat")
        self.assertEqual(int(response.data["tempo_bpm"]), 95)

    def test_update_beat_as_non_producer(self):
        """Non-producer cannot update beat."""
        self.client.force_authenticate(user=self.other_user)
        data = {"title": "Hacked Title"}
        response = self.client.patch(f"/api/economy/beatz/{self.beat.id}/", data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_update_price(self):
        """Producer can update beat price."""
        self.client.force_authenticate(user=self.producer)
        data = {"price_cents": 750}
        response = self.client.patch(f"/api/economy/beatz/{self.beat.id}/", data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["price_cents"], 750)


class BeatPurchaseTests(APITestCase):
    """Test beat purchase functionality."""

    def setUp(self):
        self.client = APIClient()
        self.producer = User.objects.create_user(
            username="producer",
            email="producer@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.producer, tier=TIER_FREE)
        Wallet.objects.create(user=self.producer, spinaz=1000)
        self.buyer1 = User.objects.create_user(
            username="buyer1",
            email="buyer1@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.buyer1, tier=TIER_FREE)
        Wallet.objects.create(user=self.buyer1, spinaz=10000)
        self.buyer2 = User.objects.create_user(
            username="buyer2",
            email="buyer2@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.buyer2, tier=TIER_FREE)
        Wallet.objects.create(user=self.buyer2, spinaz=10000)

        self.nonexclusive_beat = BeatZ.objects.create(
            producer=self.producer,
            title="Non-Exclusive Beat",
            description="Multiple buyers allowed",
            genre="hip-hop",
            tempo_bpm=90,
            price_cents=500,
            license_type=BeatZ.LICENSE_NONEXCLUSIVE,
        )

        self.exclusive_beat = BeatZ.objects.create(
            producer=self.producer,
            title="Exclusive Beat",
            description="One buyer only",
            genre="trap",
            tempo_bpm=140,
            price_cents=2000,
            license_type=BeatZ.LICENSE_EXCLUSIVE,
            quantity_available=1
        )

    def test_purchase_nonexclusive_beat(self):
        """Buyer can purchase a non-exclusive beat."""
        self.client.force_authenticate(user=self.buyer1)
        response = self.client.post(
            f"/api/economy/beatz/{self.nonexclusive_beat.id}/purchase/",
            {}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["beat_id"], self.nonexclusive_beat.id)
        self.assertEqual(response.data["license_type"], BeatZ.LICENSE_NONEXCLUSIVE)

        purchase = BeatPurchase.objects.get(id=response.data["id"])
        self.assertEqual(purchase.buyer, self.buyer1)
        self.assertGreater(purchase.producer_payout_cents, 0)

    def test_purchase_exclusive_beat(self):
        """First buyer purchases exclusive beat, second cannot."""
        self.client.force_authenticate(user=self.buyer1)
        response1 = self.client.post(
            f"/api/economy/beatz/{self.exclusive_beat.id}/purchase/",
            {}
        )
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)

        self.client.force_authenticate(user=self.buyer2)
        response2 = self.client.post(
            f"/api/economy/beatz/{self.exclusive_beat.id}/purchase/",
            {}
        )
        self.assertEqual(response2.status_code, status.HTTP_400_BAD_REQUEST)

    def test_multiple_buyers_nonexclusive(self):
        """Multiple buyers can purchase the same non-exclusive beat."""
        self.client.force_authenticate(user=self.buyer1)
        response1 = self.client.post(
            f"/api/economy/beatz/{self.nonexclusive_beat.id}/purchase/",
            {}
        )
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)

        self.client.force_authenticate(user=self.buyer2)
        response2 = self.client.post(
            f"/api/economy/beatz/{self.nonexclusive_beat.id}/purchase/",
            {}
        )
        self.assertEqual(response2.status_code, status.HTTP_201_CREATED)

    def test_cannot_purchase_own_beat(self):
        """Producer cannot purchase their own beat."""
        self.client.force_authenticate(user=self.producer)
        response = self.client.post(
            f"/api/economy/beatz/{self.nonexclusive_beat.id}/purchase/",
            {}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_purchase_twice(self):
        """Buyer cannot purchase the same beat twice."""
        self.client.force_authenticate(user=self.buyer1)
        response1 = self.client.post(
            f"/api/economy/beatz/{self.nonexclusive_beat.id}/purchase/",
            {}
        )
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)

        response2 = self.client.post(
            f"/api/economy/beatz/{self.nonexclusive_beat.id}/purchase/",
            {}
        )
        self.assertEqual(response2.status_code, status.HTTP_400_BAD_REQUEST)

    def test_insufficient_funds(self):
        """Buyer without enough SpinaZ cannot purchase."""
        self.client.force_authenticate(user=self.buyer1)
        self.buyer1.wallet.spinaz = 100
        self.buyer1.wallet.save()

        response = self.client.post(
            f"/api/economy/beatz/{self.nonexclusive_beat.id}/purchase/",
            {}
        )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)

    def test_producer_receives_payout(self):
        """Producer receives payout minus developer cut."""
        initial_spinaz = self.producer.wallet.spinaz

        self.client.force_authenticate(user=self.buyer1)
        response = self.client.post(
            f"/api/economy/beatz/{self.nonexclusive_beat.id}/purchase/",
            {}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.producer.wallet.refresh_from_db()
        self.assertGreater(self.producer.wallet.spinaz, initial_spinaz)


class BeatUsageReportTests(APITestCase):
    """Test beat usage reporting."""

    def setUp(self):
        self.client = APIClient()
        self.producer = User.objects.create_user(
            username="producer",
            email="producer@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.producer, tier=TIER_FREE)
        Wallet.objects.create(user=self.producer, spinaz=5000)
        self.buyer = User.objects.create_user(
            username="buyer",
            email="buyer@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.buyer, tier=TIER_FREE)
        Wallet.objects.create(user=self.buyer, spinaz=10000)

        self.beat = BeatZ.objects.create(
            producer=self.producer,
            title="Test Beat",
            genre="hip-hop",
            tempo_bpm=90,
            price_cents=500,
        )

        self.purchase = BeatPurchase.objects.create(
            buyer=self.buyer,
            beat=self.beat,
            license_type=BeatZ.LICENSE_NONEXCLUSIVE,
            price_cents=500,
            developer_cut_cents=50,
            producer_payout_cents=450,
        )

    def test_report_usage(self):
        """Buyer can report usage of purchased beat."""
        self.client.force_authenticate(user=self.buyer)
        data = {
            "usage_kind": BeatUsage.USAGE_YOUTUBE,
            "details": "Music video for my new track",
        }
        response = self.client.post(
            f"/api/economy/beatz/purchases/{self.purchase.id}/report-usage/",
            data
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["usage_kind"], BeatUsage.USAGE_YOUTUBE)

    def test_report_different_usage_kinds(self):
        """Test reporting different usage kinds."""
        self.client.force_authenticate(user=self.buyer)

        for usage_kind in [BeatUsage.USAGE_PERSONAL, BeatUsage.USAGE_STREAMING,
                          BeatUsage.USAGE_COMMERCIAL]:
            data = {"usage_kind": usage_kind}
            response = self.client.post(
                f"/api/economy/beatz/purchases/{self.purchase.id}/report-usage/",
                data
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_invalid_usage_kind(self):
        """Invalid usage kind should fail."""
        self.client.force_authenticate(user=self.buyer)
        data = {"usage_kind": "invalid"}
        response = self.client.post(
            f"/api/economy/beatz/purchases/{self.purchase.id}/report-usage/",
            data
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_report_for_others(self):
        """Buyer cannot report usage for other buyer's purchase."""
        other_buyer = User.objects.create_user(
            username="other",
            email="other@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=other_buyer, tier=TIER_FREE)
        Wallet.objects.create(user=other_buyer, spinaz=5000)
        self.client.force_authenticate(user=other_buyer)
        data = {"usage_kind": BeatUsage.USAGE_YOUTUBE}
        response = self.client.post(
            f"/api/economy/beatz/purchases/{self.purchase.id}/report-usage/",
            data
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class BeatEarningsTests(APITestCase):
    """Test beat earnings tracking."""

    def setUp(self):
        self.client = APIClient()
        self.producer = User.objects.create_user(
            username="producer",
            email="producer@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.producer, tier=TIER_FREE)
        Wallet.objects.create(user=self.producer, spinaz=5000)
        self.buyer1 = User.objects.create_user(
            username="buyer1",
            email="buyer1@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.buyer1, tier=TIER_FREE)
        Wallet.objects.create(user=self.buyer1, spinaz=10000)
        self.buyer2 = User.objects.create_user(
            username="buyer2",
            email="buyer2@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.buyer2, tier=TIER_FREE)
        Wallet.objects.create(user=self.buyer2, spinaz=10000)

        self.beat1 = BeatZ.objects.create(
            producer=self.producer,
            title="Beat 1",
            genre="hip-hop",
            tempo_bpm=90,
            price_cents=500,
        )

        self.beat2 = BeatZ.objects.create(
            producer=self.producer,
            title="Beat 2",
            genre="trap",
            tempo_bpm=140,
            price_cents=1000,
        )

        BeatPurchase.objects.create(
            buyer=self.buyer1,
            beat=self.beat1,
            license_type=BeatZ.LICENSE_NONEXCLUSIVE,
            price_cents=500,
            developer_cut_cents=50,
            producer_payout_cents=450,
        )

        BeatPurchase.objects.create(
            buyer=self.buyer2,
            beat=self.beat1,
            license_type=BeatZ.LICENSE_NONEXCLUSIVE,
            price_cents=500,
            developer_cut_cents=50,
            producer_payout_cents=450,
        )

        BeatPurchase.objects.create(
            buyer=self.buyer1,
            beat=self.beat2,
            license_type=BeatZ.LICENSE_NONEXCLUSIVE,
            price_cents=1000,
            developer_cut_cents=100,
            producer_payout_cents=900,
        )

    def test_get_earnings(self):
        """Producer can view their earnings."""
        self.client.force_authenticate(user=self.producer)
        response = self.client.get("/api/economy/beatz/earnings/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.data["total_sales"], 3)
        self.assertEqual(response.data["total_earnings_cents"], 450 + 450 + 900)
        self.assertEqual(len(response.data["by_beat"]), 2)

    def test_earnings_breakdown(self):
        """Earnings are broken down by beat."""
        self.client.force_authenticate(user=self.producer)
        response = self.client.get("/api/economy/beatz/earnings/")

        by_beat = {b["beat_id"]: b for b in response.data["by_beat"]}
        self.assertEqual(by_beat[self.beat1.id]["sales"], 2)
        self.assertEqual(by_beat[self.beat1.id]["earnings_cents"], 900)

        self.assertEqual(by_beat[self.beat2.id]["sales"], 1)
        self.assertEqual(by_beat[self.beat2.id]["earnings_cents"], 900)

    def test_zero_earnings(self):
        """Producer with no sales has zero earnings."""
        new_producer = User.objects.create_user(
            username="new_producer",
            email="new@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=new_producer, tier=TIER_FREE)
        Wallet.objects.create(user=new_producer, spinaz=5000)
        self.client.force_authenticate(user=new_producer)
        response = self.client.get("/api/economy/beatz/earnings/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_earnings_cents"], 0)
        self.assertEqual(response.data["total_sales"], 0)


class ProducerBeatsTests(APITestCase):
    """Test producer beat listing."""

    def setUp(self):
        self.client = APIClient()
        self.producer = User.objects.create_user(
            username="producer",
            email="producer@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.producer, tier=TIER_FREE)
        Wallet.objects.create(user=self.producer, spinaz=5000)
        self.other_producer = User.objects.create_user(
            username="other",
            email="other@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.other_producer, tier=TIER_FREE)
        Wallet.objects.create(user=self.other_producer, spinaz=5000)
        self.buyer = User.objects.create_user(
            username="buyer",
            email="buyer@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.buyer, tier=TIER_FREE)
        Wallet.objects.create(user=self.buyer, spinaz=10000)

        self.beat1 = BeatZ.objects.create(
            producer=self.producer,
            title="Beat 1",
            genre="hip-hop",
            tempo_bpm=90,
            price_cents=500,
        )

        self.beat2 = BeatZ.objects.create(
            producer=self.producer,
            title="Beat 2",
            genre="trap",
            tempo_bpm=140,
            price_cents=1000,
        )

        self.other_beat = BeatZ.objects.create(
            producer=self.other_producer,
            title="Other Beat",
            genre="electronic",
            tempo_bpm=128,
            price_cents=750,
        )

        BeatPurchase.objects.create(
            buyer=self.buyer,
            beat=self.beat1,
            license_type=BeatZ.LICENSE_NONEXCLUSIVE,
            price_cents=500,
            developer_cut_cents=50,
            producer_payout_cents=450,
        )

    def test_get_my_beats(self):
        """Producer can view their own beats with sales counts."""
        self.client.force_authenticate(user=self.producer)
        response = self.client.get("/api/economy/beatz/my-beats/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(response.data["beats"]), 2)

        beats_by_id = {b["id"]: b for b in response.data["beats"]}
        self.assertEqual(beats_by_id[self.beat1.id]["sales"], 1)
        self.assertEqual(beats_by_id[self.beat2.id]["sales"], 0)

    def test_other_producer_sees_own_beats(self):
        """Other producer sees only their own beats."""
        self.client.force_authenticate(user=self.other_producer)
        response = self.client.get("/api/economy/beatz/my-beats/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(response.data["beats"]), 1)
        self.assertEqual(response.data["beats"][0]["title"], "Other Beat")

    def test_buyer_cannot_view_my_beats(self):
        """Non-producers can view /my-beats/ but see their own zero beats."""
        self.client.force_authenticate(user=self.buyer)
        response = self.client.get("/api/economy/beatz/my-beats/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["beats"]), 0)
