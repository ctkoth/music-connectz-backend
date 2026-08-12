"""DirectZ's composer vocabulary — the prompt the screen never had.

`DirectZWork` has carried `fmt`, `video_type` and `genre` since it was written,
and nothing has ever filled the last two, because `src/apps/DirectZ.jsx` is
twenty-six lines of header and never calls the endpoint. Same shape as BugZ's
404'ing bounty and GameZ's empty tab: the backend was finished and the screen
didn't use it.

These tests cover the half that has to be right before a composer can exist —
that the vocabulary is SERVED rather than typed into the client, and that the
length bands a member reads while choosing are the same numbers the server
enforces afterwards.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.directz_app import (
    DIRECTZ_GENRES,
    DIRECTZ_VIDEO_TYPES,
    VALID_FMT,
    directz_formats,
)
from apps.economy.models import (
    DIRECTZ_BANDS,
    DirectZWork,
    directz_band_for,
    membership_for,
)

User = get_user_model()
PW = "hunter2hunter2"
URL = "/api/economy/directz/"


class Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("director", "d@e.com", PW)
        membership_for(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def post(self, **body):
        return self.client.post(URL, {"title": "Take One", **body}, format="json")


class TheVocabularyIsServed(Base):
    def test_the_feed_carries_the_formats_genres_and_types(self):
        d = self.client.get(URL).json()
        self.assertEqual({f["key"] for f in d["formats"]}, VALID_FMT)
        self.assertEqual(d["genres"], DIRECTZ_GENRES)
        self.assertEqual(d["video_types"], DIRECTZ_VIDEO_TYPES)

    def test_each_format_states_its_length_band_in_the_option(self):
        # So the constraint is readable while choosing, not after uploading.
        for fmt in self.client.get(URL).json()["formats"]:
            with self.subTest(fmt=fmt["key"]):
                self.assertTrue(fmt["length"])
                self.assertGreater(fmt["max_sec"], fmt["min_sec"])

    def test_the_labels_come_from_the_same_numbers_the_server_enforces(self):
        # A picker that advertises a band the validator disagrees with is the
        # "17 languages, 12 runners" failure in a different app.
        for fmt in directz_formats():
            lo, hi = DIRECTZ_BANDS[fmt["key"]]
            self.assertEqual((fmt["min_sec"], fmt["max_sec"]), (lo, hi))

    def test_the_bands_are_readable_rather_than_raw_seconds(self):
        by_key = {f["key"]: f["length"] for f in directz_formats()}
        self.assertEqual(by_key["reelz"], "30s–30min")
        self.assertEqual(by_key["moviez"], "1h–3h")

    def test_anonymous_callers_are_turned_away(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)


class TheChoicesAreMatchedNotTrusted(Base):
    def test_a_served_genre_is_stored(self):
        resp = self.post(fmt="reelz", genre="Music Video", duration_sec=60)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["genre"], "Music Video")

    def test_a_genre_is_matched_case_insensitively(self):
        # A client sending "music video" means the same thing, and storing two
        # spellings would mean the feed cannot group by it.
        resp = self.post(fmt="reelz", genre="music video", duration_sec=60)
        self.assertEqual(resp.json()["genre"], "Music Video")

    def test_an_unknown_genre_is_dropped_rather_than_refused(self):
        # Same rule as gamez.clean_genre: a video with no genre is fine, a 400
        # because somebody typed one we don't list is not.
        resp = self.post(fmt="reelz", genre="Interpretive Yodelling", duration_sec=60)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["genre"], "")

    def test_video_type_follows_the_same_rule(self):
        self.assertEqual(
            self.post(fmt="reelz", video_type="promotional", duration_sec=60)
                .json()["video_type"], "Promotional")
        self.assertEqual(
            self.post(fmt="reelz", video_type="nonsense", duration_sec=60)
                .json()["video_type"], "")

    def test_every_served_genre_actually_survives_a_round_trip(self):
        # A list that offers something the validator then drops is a menu that
        # lies — the exact failure this app keeps finding.
        for genre in DIRECTZ_GENRES:
            with self.subTest(genre=genre):
                self.assertEqual(
                    self.post(fmt="reelz", genre=genre, duration_sec=60).json()["genre"],
                    genre)

    def test_every_served_video_type_survives_too(self):
        for vtype in DIRECTZ_VIDEO_TYPES:
            with self.subTest(video_type=vtype):
                self.assertEqual(
                    self.post(fmt="reelz", video_type=vtype, duration_sec=60)
                        .json()["video_type"], vtype)


class TheLengthBandsStillBite(Base):
    def test_a_video_outside_the_chosen_band_is_refused(self):
        resp = self.post(fmt="moviez", duration_sec=45)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], "duration_out_of_band")

    def test_the_refusal_names_the_format_it_would_fit(self):
        # This is the answer the composer shows BEFORE the upload. It has to be
        # the same one, or the screen and the server tell different stories.
        resp = self.post(fmt="moviez", duration_sec=45)
        self.assertEqual(resp.json()["fits"], "reelz")
        self.assertEqual(directz_band_for(45), "reelz")

    def test_a_video_inside_the_band_is_accepted(self):
        self.assertEqual(self.post(fmt="reelz", duration_sec=45).status_code, 201)

    def test_an_unstated_duration_is_not_second_guessed(self):
        # 0 means "we don't know yet", not "zero seconds long".
        self.assertEqual(self.post(fmt="moviez", duration_sec=0).status_code, 201)

    def test_a_bad_format_is_still_refused_outright(self):
        # Unlike genre, format decides which band applies — there is no sensible
        # empty value to fall back to.
        self.assertEqual(self.post(fmt="tiktokz", duration_sec=60).status_code, 400)

    def test_the_work_is_stored_with_everything_the_composer_asked_for(self):
        self.post(fmt="episodez", genre="Documentary", video_type="Bio",
                  duration_sec=2400, description="Part one.")
        w = DirectZWork.objects.get(owner=self.user)
        self.assertEqual((w.fmt, w.genre, w.video_type), ("episodez", "Documentary", "Bio"))
