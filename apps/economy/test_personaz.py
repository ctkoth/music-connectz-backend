"""The persona shape, and the recovery for rows that lost it.

A member's profile rendered `{'name': 'Independent Artist', 'emoji': '🎤',
'skills': []}` as the name of a persona. That string is what Python's `str()`
makes of a dict, 58 characters long — which fits under the 60-character cap the
persona name is truncated to, so it was stored whole and served back verbatim.

The writer that did it is long fixed. Fixing a writer does not repair what it
already wrote, and nothing in this codebase was repairing it: every consumer
guards with `isinstance(persona, dict)` and skips what fails, so a member in
this state saw no error at all — just a persona rendered as machine noise, and
their priced skills quietly missing from everything that counts them.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import profile_for
from apps.economy.personaz import (clean_link, clean_persona, links_of,
                                   needs_repair, personas_of)
from apps.economy.social import profile_max_experience, profile_skill_rate

User = get_user_model()
PW = "hunter2hunter2"

# Exactly what was on the screen, produced the way it was produced.
MANGLED = str({"name": "Independent Artist", "emoji": "🎤", "skills": []})
MANGLED_WITH_SKILLS = str({
    "key": "indieartist", "name": "Independent Artist",
    "skills": [{"name": "Violin", "start": "2000-01-01", "rate_cents": 4500}],
})


class TheShapeItselfTests(TestCase):
    def test_the_string_form_still_means_a_key(self):
        self.assertEqual(clean_persona("ghostwriter"),
                         {"key": "ghostwriter", "name": "ghostwriter", "skills": []})

    def test_the_dict_form_is_untouched(self):
        raw = {"key": "k", "name": "N",
               "skills": [{"name": "Violin", "start": "2000-01-01", "rate_cents": 4500}]}
        self.assertEqual(clean_persona(raw), raw)

    def test_a_printed_dict_becomes_the_dict_again(self):
        self.assertEqual(clean_persona(MANGLED)["name"], "Independent Artist")

    def test_the_skills_come_back_with_it(self):
        # The part that actually costs somebody money: skill rates feed post
        # pricing, and stints feed the experience metric.
        out = clean_persona(MANGLED_WITH_SKILLS)
        self.assertEqual(out["key"], "indieartist")
        self.assertEqual(out["skills"], [{"name": "Violin", "start": "2000-01-01",
                                          "rate_cents": 4500}])

    def test_the_javascript_spelling_is_recovered_too(self):
        # str() in Python gives single quotes; the same mistake made in JS
        # gives JSON. A repair that only handles the language that caused it
        # once is a repair that runs out.
        self.assertEqual(clean_persona('{"name": "Producer", "skills": []}')["name"],
                         "Producer")

    def test_a_name_that_merely_looks_like_a_dict_is_left_alone(self):
        # Recovery must not eat a member's actual text. literal_eval refuses
        # this, and the fallback keeps what they typed.
        self.assertEqual(clean_persona("{not a dict}")["name"], "{not a dict}")

    def test_recovery_cannot_execute_what_a_member_typed(self):
        # ast.literal_eval evaluates literals only. If this ever became eval,
        # a persona name would be remote code execution on the profile save.
        out = clean_persona("{'name': __import__('os').system('true')}")
        self.assertEqual(out["name"], "{'name': __import__('os').system('true')}")

    def test_a_clean_row_needs_no_repair(self):
        self.assertFalse(needs_repair([{"key": "k", "name": "k", "skills": []}]))
        self.assertTrue(needs_repair([MANGLED]))


class TheReadPathRepairsTests(TestCase):
    """Nobody stays broken until they happen to save their profile again."""

    def setUp(self):
        self.user = User.objects.create_user("k-oth", "k@e.com", PW)
        p = profile_for(self.user)
        p.personas = [MANGLED_WITH_SKILLS, "ghostwriter"]
        p.save(update_fields=["personas"])
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_personas_of_repairs_without_saving(self):
        out = personas_of(profile_for(self.user))
        self.assertEqual([x["name"] for x in out], ["Independent Artist", "ghostwriter"])
        # Untouched on disk — the read path repairs, it does not write.
        self.assertEqual(profile_for(self.user).personas[0], MANGLED_WITH_SKILLS)

    def test_the_member_sees_their_own_persona_not_a_printed_dict(self):
        d = self.client.get("/api/auth/me/").data
        self.assertEqual([x["name"] for x in d["personas"]],
                         ["Independent Artist", "ghostwriter"])

    def test_a_stranger_sees_the_persona_at_all(self):
        # publicz skipped every non-dict, so the public card — the thing a
        # member shares as proof they are worth hiring — was one persona short
        # and never said so.
        d = self.client.get("/api/economy/public/members/k-oth/").data
        self.assertIn("Independent Artist", [x["name"] for x in d["personas"]])
        self.assertEqual(d["personas"][0]["skills"][0]["name"], "Violin")

    def test_the_priced_skill_counts_again(self):
        # profile_skill_rate is the price gate. A mangled persona answered None
        # here, so a member with a rate looked like a member with no rate.
        self.assertEqual(profile_skill_rate(profile_for(self.user)), 4500)

    def test_the_dated_skill_counts_again(self):
        # And the experience metric, which is summed stints across skills.
        self.assertIsNotNone(profile_max_experience(profile_for(self.user)))


class TheSweepTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("s", "s@e.com", PW)
        p = profile_for(self.user)
        p.personas = [MANGLED_WITH_SKILLS]
        p.save(update_fields=["personas"])

    def run_cmd(self, *args):
        from io import StringIO

        from django.core.management import call_command
        out = StringIO()
        call_command("repair_profiles", *args, stdout=out)
        return out.getvalue()

    def test_a_dry_run_changes_nothing(self):
        out = self.run_cmd()
        self.assertIn("Would repair 1", out)
        self.assertEqual(profile_for(self.user).personas, [MANGLED_WITH_SKILLS])

    def test_write_rewrites_the_row(self):
        self.run_cmd("--write")
        stored = profile_for(self.user).personas
        self.assertEqual(stored[0]["name"], "Independent Artist")
        self.assertEqual(stored[0]["skills"][0]["rate_cents"], 4500)

    def test_running_it_twice_is_a_no_op(self):
        self.run_cmd("--write")
        self.assertIn("Would repair 0", self.run_cmd())


class TheWritePathTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("w", "w@e.com", PW)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_saving_a_profile_does_not_re_cement_the_bad_shape(self):
        # ProfileZ reads personas back and posts them again on save. Before the
        # recovery, that round trip stored the printed dict a second time and
        # truncated it further each pass.
        r = self.client.patch("/api/auth/me/", {"personas": [MANGLED]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(profile_for(self.user).personas[0]["name"], "Independent Artist")


class TheOtherWriterTests(TestCase):
    """`POST /api/economy/profile/` wrote PROFILE_FIELDS straight off the body.

    This is the door the mangled persona came through: `/api/auth/me/`
    normalized a persona and this endpoint did not, so a profile column kept
    whatever the client happened to be holding. Three other things rode in
    through the same gap.
    """

    URL = "/api/economy/profile/"

    def setUp(self):
        self.user = User.objects.create_user("p", "p@e.com", PW)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_this_door_normalizes_a_persona_too(self):
        r = self.client.post(self.URL, {"personas": [MANGLED_WITH_SKILLS]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        stored = profile_for(self.user).personas
        self.assertEqual(stored[0]["name"], "Independent Artist")
        self.assertEqual(stored[0]["skills"][0]["rate_cents"], 4500)

    def test_a_javascript_link_never_reaches_the_column(self):
        # Rendered as <a href> on the member card and on the LOGGED-OUT public
        # profile. React warns about a javascript: href and puts it in the DOM
        # anyway, so the refusal has to happen here.
        self.client.post(self.URL, {"links": [
            {"label": "x", "url": "javascript:alert(document.cookie)"},
            {"label": "d", "url": "data:text/html,<script>x</script>"},
            {"label": "ok", "url": "https://musicconnectz.net"},
        ]}, format="json")
        stored = profile_for(self.user).links
        self.assertEqual([l["url"] for l in stored], ["https://musicconnectz.net"])

    def test_a_scheme_nobody_has_thought_of_yet_is_refused(self):
        # The allowlist is the point: a denylist needs editing every time
        # somebody finds a new way to spell it.
        self.client.post(self.URL, {"links": [{"url": "vbscript:msgbox(1)"}]}, format="json")
        self.assertEqual(profile_for(self.user).links, [])

    def test_what_people_actually_type_still_works(self):
        self.client.post(self.URL, {"links": [{"label": "IG", "url": "instagram.com/koth"}]},
                         format="json")
        self.assertEqual(profile_for(self.user).links[0]["url"], "https://instagram.com/koth")

    def test_a_profile_row_cannot_be_made_arbitrarily_large(self):
        # This row is serialized into every member card and every search
        # result, so an uncapped list is everyone else's problem too.
        self.client.post(self.URL, {"nationalities": ["x" * 500] * 500}, format="json")
        stored = profile_for(self.user).nationalities
        self.assertLessEqual(len(stored), 30)
        self.assertTrue(all(len(n) <= 60 for n in stored))

    def test_a_birthday_saved_here_carries_its_sign(self):
        self.client.post(self.URL, {"birthday": "1990-01-20"}, format="json")
        self.assertTrue(profile_for(self.user).sign)

    def test_a_birthday_saved_here_revokes_an_unearned_explicit_voice(self):
        # /api/auth/me/ has always done this. A second writer that forgets it
        # leaves a stored True standing on a birthday that no longer earns it.
        import datetime
        adult = (datetime.date.today() - datetime.timedelta(days=365 * 30)).isoformat()
        self.client.patch("/api/auth/me/", {"birthday": adult}, format="json")
        self.client.patch("/api/auth/me/", {"voice": {"explicit": True}}, format="json")
        self.assertTrue(profile_for(self.user).voice_explicit)

        teen = (datetime.date.today() - datetime.timedelta(days=365 * 14)).isoformat()
        self.client.post(self.URL, {"birthday": teen}, format="json")
        self.assertFalse(profile_for(self.user).voice_explicit)


class TheLinkRepairTests(TestCase):
    """A refused link is not one an un-run command may keep serving."""

    def setUp(self):
        self.user = User.objects.create_user("l", "l@e.com", PW)
        p = profile_for(self.user)
        # Written by the old raw setter, before the writer validated anything.
        p.links = [{"label": "bad", "url": "javascript:alert(1)"},
                   {"label": "ok", "url": "https://musicconnectz.net"}]
        p.save(update_fields=["links"])
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_the_read_path_drops_it_before_the_sweep_runs(self):
        self.assertEqual([l["url"] for l in links_of(profile_for(self.user))],
                         ["https://musicconnectz.net"])

    def test_a_stranger_is_never_served_an_executable_href(self):
        # The logged-out share page is the one that matters most here.
        d = self.client.get("/api/economy/public/members/l/").data
        self.assertEqual([l["url"] for l in d["links"]], ["https://musicconnectz.net"])

    def test_a_member_card_does_not_carry_it_either(self):
        d = self.client.get("/api/economy/profile/").data
        self.assertTrue(all("javascript" not in l["url"] for l in d["links"]))

    def test_the_sweep_says_which_link_it_refused(self):
        from io import StringIO

        from django.core.management import call_command
        out = StringIO()
        call_command("repair_profiles", "--write", stdout=out)
        self.assertIn("link REFUSED", out.getvalue())
        self.assertEqual([l["url"] for l in profile_for(self.user).links],
                         ["https://musicconnectz.net"])

    def test_mailto_is_a_link_people_really_use(self):
        self.assertIsNotNone(clean_link({"url": "mailto:booking@example.com"}))
