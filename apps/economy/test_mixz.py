"""Mix ConnectZ: a ladder that says how MUCH, a record of what was kept, and a
delete that gives the storage back.

The mastering runs on the member's device and costs the platform nothing, so
there is no price to test — what is tested is that this stays true (nothing is
charged or logged), that the tier ladder is the server's, and that a saved
master is a record the member can trust: their own file, cleaned JSON, a link
that does not expire, and a delete that frees what it held.
"""
import json
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy import catalog, mixz
from apps.economy.models import (MB, MasterWork, Transaction, Upload, membership_for,
                                 storage_used_bytes)

User = get_user_model()
URL = "/api/economy/mixz/"
PW = "pw12345!"


def make_upload(user, name="master.wav", size=2048, content_type="audio/wav"):
    return Upload.objects.create(
        user=user, name=name, size_bytes=size, content_type=content_type,
        file=SimpleUploadedFile(name, b"0" * size, content_type=content_type))


def set_tier(user, tier):
    m = membership_for(user)
    m.tier = tier
    m.save()


class LadderTests(TestCase):
    """Corey: compression for Premium, the heaviest for StatZ. A tier says how
    MUCH, never whether, so Free still gets automatic compression."""

    def test_free_has_compression_but_not_the_heaviest(self):
        free = catalog.mastering_for("free")
        self.assertEqual(free["intensities"], ["low", "medium"])
        self.assertNotIn("max", free["intensities"])
        self.assertFalse(free["manual_glue"])
        self.assertGreater(free["glue_db_max"], 0, "Free is not locked out of compression")

    def test_premium_has_manual_glue_and_statz_has_the_heaviest(self):
        premium = catalog.mastering_for("premium")
        statz = catalog.mastering_for("statz")
        self.assertTrue(premium["manual_glue"])
        self.assertIn("high", premium["intensities"])
        self.assertNotIn("max", premium["intensities"])
        self.assertIn("max", statz["intensities"])
        self.assertTrue(statz["manual_glue"])

    def test_every_rung_holds_everything_the_one_below_has(self):
        order = [catalog.mastering_for(t) for t in ("free", "premium", "statz")]
        for lower, upper in zip(order, order[1:]):
            self.assertTrue(set(lower["intensities"]) <= set(upper["intensities"]))
            self.assertLess(lower["glue_db_max"], upper["glue_db_max"])

    def test_the_ladder_is_the_numbers_the_spec_gave(self):
        self.assertEqual(catalog.mastering_for("free")["glue_db_max"], 2)
        self.assertEqual(catalog.mastering_for("premium")["glue_db_max"], 4)
        self.assertEqual(catalog.mastering_for("statz")["glue_db_max"], 8)

    def test_every_intensity_on_the_ladder_has_a_label_and_heaviest_is_max(self):
        for row in catalog.MASTERING.values():
            for i in row["intensities"]:
                self.assertIn(i, catalog.MASTERING_INTENSITY_LABELS)
        self.assertEqual(catalog.MASTERING_INTENSITY_LABELS["max"], "Heaviest")

    def test_a_caller_editing_the_answer_cannot_move_the_ladder(self):
        row = catalog.mastering_for("free")
        row["intensities"].append("max")
        row["glue_db_max"] = 99
        self.assertEqual(catalog.mastering_for("free")["intensities"], ["low", "medium"])
        self.assertEqual(catalog.mastering_for("free")["glue_db_max"], 2)

    def test_an_unknown_tier_gets_free_rather_than_a_crash(self):
        self.assertEqual(catalog.mastering_for("nonsense"), catalog.mastering_for("free"))

    def test_the_owners_debug_tier_is_not_published_in_the_ladder(self):
        self.assertEqual([r["tier"] for r in catalog.mastering_ladder()], ["free", "premium", "statz"])


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ReadTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("maker", "m@e.com", PW)
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def test_it_needs_a_sign_in(self):
        self.assertIn(APIClient().get(URL).status_code, (401, 403))

    def test_the_shape(self):
        d = self.c.get(URL).json()
        self.assertEqual(set(d), {"tier", "allowed", "ladder", "intensity_labels", "cost",
                                  "storage", "masters"})
        self.assertEqual(d["tier"], "free")
        self.assertEqual(set(d["allowed"]), {"intensities", "manual_glue", "glue_db_max"})
        self.assertEqual([r["tier"] for r in d["ladder"]], ["free", "premium", "statz"])
        self.assertEqual([r["label"] for r in d["ladder"]], ["Free", "Premium", "StatZ"])
        for r in d["ladder"]:
            self.assertEqual(set(r), {"tier", "label", "intensities", "manual_glue", "glue_db_max"})
        self.assertEqual(d["cost"], {"free": True, "line": mixz.COST_LINE})
        self.assertIn("Nothing is uploaded unless you save it", d["cost"]["line"])
        self.assertEqual(set(d["storage"]), {"used_mb", "storage_mb", "upload_mb", "free_mb"})
        self.assertEqual(d["masters"], [])
        self.assertEqual(d["intensity_labels"]["max"], "Heaviest")

    def test_a_brand_new_account_with_no_rows_attached_still_opens(self):
        fresh = User.objects.create_user("fresh", "f@e.com", PW)
        c = APIClient()
        c.force_authenticate(fresh)
        self.assertEqual(c.get(URL).status_code, 200)

    def test_allowed_follows_the_members_tier(self):
        free = self.c.get(URL).json()["allowed"]
        self.assertNotIn("max", free["intensities"])
        set_tier(self.me, "premium")
        premium = self.c.get(URL).json()
        self.assertEqual(premium["tier"], "premium")
        self.assertTrue(premium["allowed"]["manual_glue"])
        self.assertNotIn("max", premium["allowed"]["intensities"])
        set_tier(self.me, "statz")
        self.assertIn("max", self.c.get(URL).json()["allowed"]["intensities"])

    def test_the_whole_ladder_is_published_whatever_tier_you_are(self):
        # So a Free member is told what a tier up would add.
        ladder = {r["tier"]: r for r in self.c.get(URL).json()["ladder"]}
        self.assertIn("max", ladder["statz"]["intensities"])

    def test_storage_is_the_tiers_numbers_rounded_to_one_decimal(self):
        make_upload(self.me, size=int(1.234 * MB))
        s = self.c.get(URL).json()["storage"]
        lim = catalog.limits_for("free")
        self.assertEqual(s["storage_mb"], lim["storage_mb"])
        self.assertEqual(s["upload_mb"], lim["upload_mb"])
        self.assertEqual(s["used_mb"], 1.2)
        self.assertEqual(s["free_mb"], round(lim["storage_mb"] - 1.234, 1))

    def test_masters_are_newest_first_and_capped_at_twenty(self):
        up = make_upload(self.me)
        for i in range(23):
            MasterWork.objects.create(user=self.me, title=f"m{i}", upload=up)
        masters = self.c.get(URL).json()["masters"]
        self.assertEqual(len(masters), 20)
        self.assertEqual(masters[0]["title"], "m22")

    def test_you_only_see_your_own(self):
        other = User.objects.create_user("other", "o@e.com", PW)
        MasterWork.objects.create(user=other, title="theirs", upload=make_upload(other))
        self.assertEqual(self.c.get(URL).json()["masters"], [])

    def test_the_list_costs_the_same_number_of_queries_at_any_length(self):
        def count():
            with CaptureQueriesContext(connection) as q:
                self.assertEqual(self.c.get(URL).status_code, 200)
            return len(q)
        up = make_upload(self.me)
        MasterWork.objects.create(user=self.me, title="one", upload=up, source_upload=up)
        self.c.get(URL)                        # first touch makes the membership row
        one = count()
        for i in range(19):
            MasterWork.objects.create(user=self.me, title=f"m{i}", upload=make_upload(self.me),
                                      source_upload=make_upload(self.me))
        self.assertEqual(count(), one)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SaveTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("maker", "m@e.com", PW)
        self.other = User.objects.create_user("other", "o@e.com", PW)
        self.c = APIClient()
        self.c.force_authenticate(self.me)
        self.up = make_upload(self.me)

    def post(self, **body):
        body.setdefault("upload_id", self.up.id)
        return self.c.post(URL, body, format="json")

    def test_it_keeps_a_master_and_answers_with_the_record(self):
        src = make_upload(self.me, name="mix.wav")
        r = self.post(title="Night drive", source_upload_id=src.id,
                      settings={"style": "warm", "intensity": "high", "target": "streaming"},
                      before={"lufs": -18.2}, after={"lufs": -14.0, "truePeakDb": -1.0})
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertEqual(set(d), {"id", "title", "created_at", "settings", "before", "after", "url",
                                  "size_mb", "content_type", "missing", "source_url"})
        self.assertEqual(d["title"], "Night drive")
        self.assertEqual(d["settings"]["intensity"], "high")
        self.assertEqual(d["after"]["lufs"], -14.0)
        self.assertEqual(d["content_type"], "audio/wav")
        self.assertFalse(d["missing"])
        self.assertTrue(d["source_url"])
        m = MasterWork.objects.get(pk=d["id"])
        self.assertEqual((m.user, m.upload, m.source_upload), (self.me, self.up, src))

    def test_saving_is_free_and_writes_no_ledger_row(self):
        before = Transaction.objects.count()
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(Transaction.objects.count(), before)

    def test_it_refuses_somebody_elses_upload(self):
        theirs = make_upload(self.other)
        r = self.post(upload_id=theirs.id)
        self.assertEqual(r.status_code, 400)
        self.assertIn("isn't one of your uploads", r.json()["detail"])
        self.assertFalse(MasterWork.objects.exists())

    def test_it_refuses_an_upload_that_does_not_exist_or_is_not_a_number(self):
        for bad in (999999, "abc", None, ""):
            r = self.c.post(URL, {"upload_id": bad}, format="json")
            self.assertEqual(r.status_code, 400, bad)
        self.assertFalse(MasterWork.objects.exists())

    def test_it_refuses_anything_that_is_not_audio(self):
        img = make_upload(self.me, name="cover.png", content_type="image/png")
        r = self.post(upload_id=img.id)
        self.assertEqual(r.status_code, 400)
        self.assertIn("audio", r.json()["detail"])
        blank = make_upload(self.me, name="x.bin", content_type="")
        self.assertEqual(self.post(upload_id=blank.id).status_code, 400)
        self.assertFalse(MasterWork.objects.exists())

    def test_it_refuses_a_file_already_known_to_be_gone(self):
        Upload.objects.filter(pk=self.up.pk).update(missing_since=timezone.now())
        self.assertEqual(self.post().status_code, 400)

    def test_the_original_must_be_yours_too(self):
        theirs = make_upload(self.other)
        r = self.post(source_upload_id=theirs.id)
        self.assertEqual(r.status_code, 400)
        self.assertIn("original", r.json()["detail"])
        self.assertFalse(MasterWork.objects.exists())

    def test_the_original_is_optional(self):
        r = self.post()
        self.assertEqual(r.status_code, 201)
        self.assertIsNone(r.json()["source_url"])

    def test_the_master_cannot_also_be_its_own_original(self):
        # Deleting the master would then delete the original with it.
        self.assertEqual(self.post(source_upload_id=self.up.id).status_code, 400)

    def test_one_file_is_one_master(self):
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post().status_code, 409)
        self.assertEqual(MasterWork.objects.count(), 1)

    def test_a_mastering_chosen_above_the_tier_is_still_recorded(self):
        # It ran on their device and cost nobody anything. A member who edits
        # the client to reach Heaviest has taken nothing from anyone, and
        # refusing to record what they already made would only lose them their
        # own settings. The ladder is enforced where the choice is offered.
        r = self.post(settings={"intensity": "max", "glueDb": 8})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["settings"]["intensity"], "max")

    def test_junk_in_the_json_is_cleaned_not_stored(self):
        raw = json.dumps({
            "upload_id": self.up.id,
            "title": "  " + "x" * 400 + "  ",
            "settings": {
                "style": "Warm", "intensity": "ludicrous", "target": "streaming", "width": "130",
                "monoBass": "sometimes", "eq": "yes", "trims": {"low": 99, "mid": "-2.5", "high": "bad", "x": 1},
                "glueDb": 500, "bitDepth": 20, "dither": 1, "reference": True,
                "__proto__": {"polluted": True}, "script": "<script>alert(1)</script>",
            },
            "before": {"lufs": "NaN", "lra": "__INF__", "truePeakDb": "-1.5", "plr": True,
                       "correlation": 5, "sampleRate": 44100.0, "channels": "2", "evil": 7,
                       "bands": [{"f": 100, "db": -20}, {"f": "x", "db": 1}, "junk", {"f": 200, "db": None}]},
            "after": {"seconds": -5, "clippedSamples": 3, "samplePeakDb": None, "lufs": None, "html": "<b>"},
        })
        # 1e999 is valid JSON that Python parses to infinity — a literal NaN or
        # Infinity is refused by DRF's strict parser, this is the way one arrives.
        raw = raw.replace('"__INF__"', "1e999")
        r = self.c.post(URL, raw, content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertEqual(len(d["title"]), 120)
        self.assertEqual(d["title"], "x" * 120)
        s = d["settings"]
        self.assertEqual(s["style"], "warm")
        self.assertNotIn("intensity", s)
        self.assertEqual(s["width"], 130.0)
        self.assertNotIn("monoBass", s)
        self.assertNotIn("eq", s, "a string is not a boolean")
        self.assertEqual(s["trims"], {"low": 12.0, "mid": -2.5, "high": 0.0})
        self.assertEqual(s["glueDb"], float(mixz.GLUE_DB_CEILING))
        self.assertNotIn("bitDepth", s)
        self.assertNotIn("dither", s)
        self.assertIs(s["reference"], True)
        self.assertNotIn("__proto__", s)
        self.assertNotIn("script", s)
        b = d["before"]
        self.assertNotIn("lufs", b, "NaN is no reading")
        self.assertNotIn("lra", b, "infinity is no reading")
        self.assertEqual(b["truePeakDb"], -1.5)
        self.assertNotIn("plr", b, "a boolean is not a number")
        self.assertEqual(b["correlation"], 1.0)
        self.assertEqual(b["sampleRate"], 44100)
        self.assertIsInstance(b["sampleRate"], int)
        self.assertEqual(b["channels"], 2)
        self.assertNotIn("evil", b)
        self.assertEqual(b["bands"], [{"f": 100.0, "db": -20.0}, {"f": 200.0, "db": None}])
        a = d["after"]
        self.assertEqual(a["seconds"], 0.0)
        self.assertEqual(a["clippedSamples"], 3)
        self.assertNotIn("html", a)

    def test_the_cleaners_drop_nan_and_infinity_directly(self):
        # DRF's strict parser rejects a bare NaN literal before it gets here,
        # but the cleaner must not depend on that.
        out = mixz.clean_measures({"lufs": float("nan"), "lra": float("inf"),
                                   "plr": float("-inf"), "seconds": 12.5})
        self.assertEqual(out, {"seconds": 12.5})

    def test_a_non_object_for_any_json_field_is_an_empty_record_not_an_error(self):
        r = self.post(settings="loud", before=[1, 2], after=None)
        self.assertEqual(r.status_code, 201)
        d = r.json()
        self.assertEqual((d["settings"], d["before"], d["after"]), ({}, {}, {}))

    def test_bands_are_capped(self):
        bands = [{"f": 20 + i, "db": -30.0} for i in range(100)]
        d = self.post(before={"bands": bands}).json()
        self.assertEqual(len(d["before"]["bands"]), mixz.BANDS_MAX)

    def test_the_title_defaults_and_collapses_whitespace(self):
        self.assertEqual(self.post().json()["title"], "Master")
        up2 = make_upload(self.me, name="b.wav")
        self.assertEqual(self.post(upload_id=up2.id, title="  My \n  song ").json()["title"], "My song")
        up3 = make_upload(self.me, name="c.wav")
        self.assertEqual(self.post(upload_id=up3.id, title="   ").json()["title"], "Master")

    def test_every_stored_title_fits_the_column(self):
        field = MasterWork._meta.get_field("title")
        self.assertEqual(field.max_length, mixz.TITLE_MAX)
        self.assertLessEqual(len(mixz.clean_title("é" * 1000)), field.max_length)

    def test_the_url_is_the_stable_media_route_never_the_storage_address(self):
        url = self.post().json()["url"]
        self.assertIn(f"/api/economy/media/{self.up.id}/", url)
        self.assertNotIn("/media/uploads/", url)
        self.assertTrue(url.endswith(self.up.file.name.rsplit("/", 1)[-1]), "the filename is last")
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_a_master_whose_file_was_lost_says_so_and_offers_no_player(self):
        self.post()
        Upload.objects.filter(pk=self.up.pk).update(missing_since=timezone.now())
        m = self.c.get(URL).json()["masters"][0]
        self.assertTrue(m["missing"])
        self.assertIsNone(m["url"])

    def test_deleting_the_file_from_the_uploads_screen_leaves_the_record_saying_it_is_gone(self):
        self.post(title="kept")
        self.assertEqual(self.c.delete(f"/api/economy/uploads/{self.up.id}/").status_code, 200)
        m = self.c.get(URL).json()["masters"][0]
        self.assertEqual(m["title"], "kept")
        self.assertTrue(m["missing"])
        self.assertIsNone(m["url"])
        self.assertEqual(m["size_mb"], 0)

    def test_the_weird_methods_are_not_there(self):
        self.assertEqual(self.c.put(URL, {}, format="json").status_code, 405)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class DeleteTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("maker", "m@e.com", PW)
        self.other = User.objects.create_user("other", "o@e.com", PW)
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def keep(self, user=None, size=3 * MB // 2, with_source=False):
        user = user or self.me
        up = make_upload(user, size=size)
        src = make_upload(user, name="orig.wav", size=1024) if with_source else None
        return MasterWork.objects.create(user=user, title="m", upload=up, source_upload=src)

    def test_it_deletes_the_record_and_its_file_and_gives_the_storage_back(self):
        m = self.keep()
        name = m.upload.file.name
        used = storage_used_bytes(self.me)
        self.assertGreater(used, 0)
        r = self.c.delete(f"{URL}{m.id}/")
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertIs(d["deleted"], True)
        self.assertEqual(d["freed_mb"], 1.5)
        self.assertFalse(MasterWork.objects.filter(pk=m.pk).exists())
        self.assertFalse(Upload.objects.filter(pk=m.upload_id).exists())
        self.assertFalse(default_storage.exists(name), "the bytes go, not only the row")
        self.assertEqual(storage_used_bytes(self.me), 0)
        self.assertEqual(d["storage"]["used_mb"], 0.0)

    def test_the_original_is_never_deleted_by_this(self):
        m = self.keep(with_source=True)
        src, src_name = m.source_upload, m.source_upload.file.name
        self.assertEqual(self.c.delete(f"{URL}{m.id}/").status_code, 200)
        self.assertTrue(Upload.objects.filter(pk=src.pk).exists())
        self.assertTrue(default_storage.exists(src_name))

    def test_it_refuses_somebody_elses_master_with_a_404_and_touches_nothing(self):
        theirs = self.keep(user=self.other)
        name = theirs.upload.file.name
        self.assertEqual(self.c.delete(f"{URL}{theirs.id}/").status_code, 404)
        self.assertTrue(MasterWork.objects.filter(pk=theirs.pk).exists())
        self.assertTrue(Upload.objects.filter(pk=theirs.upload_id).exists())
        self.assertTrue(default_storage.exists(name))

    def test_a_record_that_does_not_exist_is_a_404(self):
        self.assertEqual(self.c.delete(f"{URL}999999/").status_code, 404)

    def test_it_needs_a_sign_in(self):
        m = self.keep()
        self.assertIn(APIClient().delete(f"{URL}{m.id}/").status_code, (401, 403))
        self.assertTrue(MasterWork.objects.filter(pk=m.pk).exists())

    def test_a_record_whose_file_is_already_gone_deletes_and_frees_nothing(self):
        m = self.keep()
        Upload.objects.filter(pk=m.upload_id).update(missing_since=timezone.now())
        r = self.c.delete(f"{URL}{m.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["freed_mb"], 0)
        self.assertFalse(MasterWork.objects.filter(pk=m.pk).exists())

    def test_a_record_whose_upload_was_already_deleted_still_deletes(self):
        m = self.keep()
        self.c.delete(f"/api/economy/uploads/{m.upload_id}/")
        r = self.c.delete(f"{URL}{m.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["freed_mb"], 0)
        self.assertFalse(MasterWork.objects.filter(pk=m.pk).exists())


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class AccountDeletionTests(TestCase):
    """The model is SET_NULL on its files and CASCADE on the member, and
    erasure finds files by exactly that shape — so a master must not stand in
    the way of deleting an account, nor leave its WAV behind."""

    def test_deleting_a_member_with_a_master_succeeds_and_takes_the_file(self):
        from apps.accounts.erasure import collect_files, delete_user
        u = User.objects.create_user("leaver", "l@e.com", PW)
        up = make_upload(u)
        src = make_upload(u, name="orig.wav")
        MasterWork.objects.create(user=u, title="gone soon", upload=up, source_upload=src)
        names = {up.file.name, src.file.name}
        self.assertTrue(names <= {n for _, n in collect_files(u)})
        with self.captureOnCommitCallbacks(execute=True):
            delete_user(u, billing_stopped=True)
        self.assertFalse(User.objects.filter(username="leaver").exists())
        self.assertFalse(MasterWork.objects.exists())
        for n in names:
            self.assertFalse(default_storage.exists(n), n)
