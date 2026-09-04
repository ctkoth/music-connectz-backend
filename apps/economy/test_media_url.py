"""A stored link must not be one that expires.

The app writes the URL it hands out into `Post.media_url`, into the post's
`items`, into collab deals and battle entries — and leaves it there for the
life of the post. While uploads sit on a local disk, `Upload.file.url` is a
plain path and that is harmless.

It stops being harmless at exactly the moment somebody fixes the real problem.
Moving uploads to a bucket is what makes them survive a deploy, and a bucket
hands out SIGNED urls that expire in an hour (S3_QUERYSTRING_AUTH defaults on).
Freezing one into a post means every track goes silent sixty minutes after it
is posted — the same "this recording won't load" the missing-file bug produced,
with no missing file. The fix for losing everyone's music would have shipped as
a new way to lose it.

So these pin the property that makes the switch safe: nothing stores a storage
address, and the tail lookups that find a take on a post still work.
"""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.crosspost import upload_behind
from apps.economy.media import stable_media_url
from apps.economy.models import Upload

User = get_user_model()
PW = "pw12345!"


class TheStoredLinkNeverExpiresTests(TestCase):

    def setUp(self):
        self.me = User.objects.create_user(username="maker", password=PW)
        self.c = APIClient()
        self.c.force_authenticate(self.me)
        self.up = Upload.objects.create(
            user=self.me, name="take.webm", size_bytes=900,
            content_type="audio/webm",
            file=SimpleUploadedFile("take.webm", b"0" * 900, content_type="audio/webm"))

    def test_the_url_handed_out_is_the_route_not_the_storage_address(self):
        url = self.c.get("/api/economy/uploads/").json()["uploads"][0]["url"]
        self.assertIn(f"/api/economy/media/{self.up.id}/", url)
        # And specifically NOT the bucket/disk address, which is the thing that
        # carries a signature and a clock.
        self.assertNotIn("/media/uploads/", url)

    def test_it_resolves_to_wherever_the_bytes_are_now(self):
        r = self.client.get(stable_media_url(self.up))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], self.up.file.url)

    def test_it_is_readable_without_signing_in(self):
        """`<audio src>` sends no Authorization header. A link that needs one
        is a player that shows 0:00 and says nothing."""
        self.assertEqual(self.client.get(stable_media_url(self.up)).status_code, 302)

    def test_the_id_and_the_name_have_to_agree(self):
        """The id alone would let anybody walk the range and collect every
        filename on the platform."""
        r = self.client.get(f"/api/economy/media/{self.up.id}/somebody-elses.webm")
        self.assertEqual(r.status_code, 404)

    def test_a_missing_upload_is_a_404_not_a_500(self):
        self.assertEqual(self.client.get("/api/economy/media/99999/x.webm").status_code, 404)

    def test_the_coach_still_finds_the_take_behind_this_url(self):
        """The one that would have broken everything quietly.

        `upload_behind()` and `take_bytes_for()` match a post's media URL by its
        TAIL, because MEDIA_URL differs between disk, Render and a CDN. Ending
        this route with the stored basename is what keeps "coach this post"
        working — and a trailing slash would have made every one of those
        lookups miss, with no error anywhere.
        """
        url = stable_media_url(self.up)
        self.assertFalse(url.endswith("/"))
        self.assertEqual(upload_behind(url, [self.me.id]), self.up)

    def test_an_upload_with_no_file_has_no_url_rather_than_a_broken_one(self):
        empty = Upload.objects.create(user=self.me, name="nothing", size_bytes=0)
        self.assertEqual(stable_media_url(empty), "")
