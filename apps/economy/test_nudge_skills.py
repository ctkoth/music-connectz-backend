import datetime
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.economy.management.commands.nudge_skills import NUDGE_KEY, legacy_skills
from apps.economy.models import Notification, profile_for

User = get_user_model()
TODAY = datetime.date.today()


def yrs_ago(n):
    try:
        return TODAY.replace(year=TODAY.year - n).isoformat()
    except ValueError:          # 29 Feb
        return TODAY.replace(year=TODAY.year - n, day=28).isoformat()


def run(*args):
    out, err = StringIO(), StringIO()
    call_command("nudge_skills", *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def member(name, skills):
    u = User.objects.create_user(name, f"{name}@e.com", "pw12345678")
    p = profile_for(u)
    p.personas = [{"key": "indieartist", "name": "Indie Artist", "skills": skills}]
    p.save()
    return u


class LegacySkillDetectionTests(TestCase):
    def test_a_bare_start_is_legacy(self):
        p = profile_for(member("a", [{"name": "Violin", "start": yrs_ago(26)}]))
        self.assertEqual(len(legacy_skills(p)), 1)

    def test_a_stinted_skill_is_not(self):
        p = profile_for(member("b", [{"name": "Violin", "periods": [{"start": yrs_ago(26), "end": yrs_ago(12)}]}]))
        self.assertEqual(legacy_skills(p), [])

    def test_an_undated_skill_is_not(self):
        # Nothing to overstate.
        p = profile_for(member("c", [{"name": "Violin"}]))
        self.assertEqual(legacy_skills(p), [])

    def test_a_bare_string_persona_does_not_crash(self):
        u = User.objects.create_user("d", "d@e.com", "pw12345678")
        p = profile_for(u)
        p.personas = ["producer"]
        p.save()
        self.assertEqual(legacy_skills(p), [])


class NudgeTests(TestCase):
    def test_it_notifies_a_member_who_would_benefit(self):
        u = member("steve515", [{"name": "Violin 🎻", "start": yrs_ago(26)}])
        run()
        n = Notification.objects.get(user=u)
        self.assertEqual(n.item_id, NUDGE_KEY)
        self.assertIn("Violin", n.text)

    def test_the_message_names_their_number_not_a_generic_ask(self):
        u = member("steve515", [{"name": "Violin", "start": yrs_ago(26)}])
        run()
        text = Notification.objects.get(user=u).text
        self.assertIn("26 yrs", text)
        self.assertIn(str(TODAY.year - 26), text)   # the year it counts from
        self.assertIn("ProfileZ", text)

    def test_it_names_the_worst_offender_when_there_are_several(self):
        u = member("multi", [
            {"name": "Piano", "start": yrs_ago(4)},
            {"name": "Violin", "start": yrs_ago(26)},
        ])
        run()
        self.assertIn("Violin", Notification.objects.get(user=u).text)

    def test_nobody_clean_is_bothered(self):
        member("stinted", [{"name": "V", "periods": [{"start": yrs_ago(9)}]}])
        member("undated", [{"name": "V"}])
        run()
        self.assertEqual(Notification.objects.count(), 0)

    def test_running_twice_does_not_spam(self):
        member("steve515", [{"name": "Violin", "start": yrs_ago(26)}])
        run()
        out, _ = run()
        self.assertIn("already nudged", out)
        self.assertEqual(Notification.objects.count(), 1)

    def test_again_resends_deliberately(self):
        member("steve515", [{"name": "Violin", "start": yrs_ago(26)}])
        run()
        run("--again")
        self.assertEqual(Notification.objects.count(), 2)

    def test_dry_run_sends_nothing_but_shows_the_text(self):
        member("steve515", [{"name": "Violin", "start": yrs_ago(26)}])
        out, _ = run("--dry-run")
        self.assertIn("steve515", out)
        self.assertIn("Nothing was sent", out)
        self.assertEqual(Notification.objects.count(), 0)

    def test_one_member_can_be_targeted(self):
        member("steve515", [{"name": "Violin", "start": yrs_ago(26)}])
        member("someone_else", [{"name": "Piano", "start": yrs_ago(9)}])
        run("steve515")
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(Notification.objects.get().user.username, "steve515")

    def test_targeting_by_email_works(self):
        member("steve515", [{"name": "Violin", "start": yrs_ago(26)}])
        run("steve515@e.com")
        self.assertEqual(Notification.objects.count(), 1)

    def test_an_unknown_member_is_named_not_silently_ignored(self):
        _, err = run("nobody")
        self.assertIn("No member matches 'nobody'", err)

    def test_the_text_fits_the_column(self):
        # Notification.text is CharField(280) and notify() truncates — a message
        # cut mid-sentence would read like a bug to the member.
        u = member("longname", [{"name": "Mezzo-Soprano with a very long label 🌊", "start": yrs_ago(26)}])
        run()
        self.assertLess(len(Notification.objects.get(user=u).text), 280)
