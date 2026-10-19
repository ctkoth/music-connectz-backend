"""Tests for Habit and UserPreferences models and endpoints."""
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status

from .models import Habit, UserPreferences


class HabitCreateViewTests(TestCase):
    """Test HabitCreateView endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.client.force_authenticate(user=self.user)

    def test_create_habit_minimal(self):
        """Test creating a habit with minimal data."""
        response = self.client.post("/api/economy/habits/", {
            "title": "Daily practice",
            "app_key": "singz",
            "frequency": "daily",
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "Daily practice")
        self.assertEqual(response.data["frequency"], "daily")
        self.assertTrue(Habit.objects.filter(title="Daily practice").exists())

    def test_create_habit_with_preferences(self):
        """Test creating a habit and saving preferences together."""
        response = self.client.post("/api/economy/habits/", {
            "title": "Daily vocal",
            "app_key": "singz",
            "frequency": "daily",
            "notifications_enabled": False,
            "language": "es",
            "sound_enabled": True,
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify preferences were saved
        prefs = UserPreferences.objects.get(user=self.user)
        self.assertFalse(prefs.notifications_enabled)
        self.assertEqual(prefs.language, "es")
        self.assertTrue(prefs.sound_enabled)

    def test_create_habit_empty_title_fails(self):
        """Test that empty title is rejected."""
        response = self.client.post("/api/economy/habits/", {
            "title": "",
            "app_key": "singz",
            "frequency": "daily",
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_habit_requires_auth(self):
        """Test that unauthenticated users cannot create habits."""
        client = APIClient()
        response = client.post("/api/economy/habits/", {
            "title": "Daily practice",
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_frequency_defaults_to_daily(self):
        """Test that frequency defaults to 'daily'."""
        response = self.client.post("/api/economy/habits/", {
            "title": "Practice",
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["frequency"], "daily")

    def test_invalid_frequency_defaults_to_daily(self):
        """Test that invalid frequency is reset to 'daily'."""
        response = self.client.post("/api/economy/habits/", {
            "title": "Practice",
            "frequency": "monthly",
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["frequency"], "daily")

    def test_preferences_update_on_second_habit(self):
        """Test that creating a second habit updates preferences."""
        # Create first habit with preferences
        self.client.post("/api/economy/habits/", {
            "title": "First",
            "notifications_enabled": True,
            "language": "en",
        })

        # Create second habit with different preferences
        self.client.post("/api/economy/habits/", {
            "title": "Second",
            "notifications_enabled": False,
            "language": "fr",
        })

        # Should have one preferences record, updated
        prefs = UserPreferences.objects.get(user=self.user)
        self.assertFalse(prefs.notifications_enabled)
        self.assertEqual(prefs.language, "fr")


class UserPreferencesModelTests(TestCase):
    """Test UserPreferences model."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")

    def test_create_preferences(self):
        """Test creating preferences."""
        prefs = UserPreferences.objects.create(
            user=self.user,
            notifications_enabled=False,
            language="ja",
            sound_enabled=False,
        )
        self.assertEqual(prefs.language, "ja")
        self.assertFalse(prefs.notifications_enabled)

    def test_preferences_defaults(self):
        """Test default values."""
        prefs = UserPreferences.objects.create(user=self.user)
        self.assertTrue(prefs.notifications_enabled)
        self.assertEqual(prefs.language, "en")
        self.assertTrue(prefs.sound_enabled)

    def test_language_choices(self):
        """Test that all language choices are valid."""
        for lang_code in ["en", "es", "fr", "de", "pt", "ja"]:
            prefs = UserPreferences.objects.create(
                user=User.objects.create_user(f"user_{lang_code}"),
                language=lang_code,
            )
            self.assertEqual(prefs.language, lang_code)

    def test_one_to_one_relationship(self):
        """Test OneToOne relationship enforces one record per user."""
        UserPreferences.objects.create(user=self.user)
        with self.assertRaises(Exception):
            UserPreferences.objects.create(user=self.user)


class HabitModelTests(TestCase):
    """Test Habit model."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")

    def test_create_habit(self):
        """Test creating a habit."""
        habit = Habit.objects.create(
            user=self.user,
            title="Daily warmup",
            app_key="singz",
            frequency="daily",
        )
        self.assertEqual(habit.title, "Daily warmup")
        self.assertEqual(habit.app_key, "singz")

    def test_habit_defaults(self):
        """Test default values."""
        habit = Habit.objects.create(user=self.user, title="Practice")
        self.assertEqual(habit.app_key, "singz")
        self.assertEqual(habit.frequency, "daily")
        self.assertIsNone(habit.last_completed)

    def test_habit_frequency_choices(self):
        """Test valid frequency choices."""
        for freq in ["daily", "weekly"]:
            habit = Habit.objects.create(
                user=User.objects.create_user(f"user_{freq}"),
                title="Practice",
                frequency=freq,
            )
            self.assertEqual(habit.frequency, freq)

    def test_user_can_have_multiple_habits(self):
        """Test user can create multiple habits."""
        Habit.objects.create(user=self.user, title="Vocal practice")
        Habit.objects.create(user=self.user, title="Theory")
        self.assertEqual(self.user.habits.count(), 2)
