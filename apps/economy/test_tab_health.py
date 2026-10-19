"""Every tab's own endpoint answers, for a member who has just arrived.

Two 500s were found by opening all 42 tabs with a session — something the
trial doors had been through and the signed-in app never had. Both were the
same shape: a view reaching for a relation that does not exist on a brand-new
account, which is the account every new member has.

That shape has now appeared four times in this codebase (`p.author.membership`,
`p.ratings`, `request.user.profile`, and `reach_median` returning 0), so these
tests do not check a fix — they check the CLASS. A member with a fresh account
and no data is the hardest case every one of these views has, and it is also
the only case a new member is ever in.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Post

User = get_user_model()


class BareAccountTests(TestCase):
    """A member who signed up a second ago, with nothing attached to them."""

    def setUp(self):
        # Deliberately NOT touching profile_for / membership_for first: the
        # rows a lazy getter would create are exactly what these views used to
        # assume already existed.
        self.u = User.objects.create_user("brandnew", "new@mcz.test", "pw12345!")
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def test_the_coach_studio_opens(self):
        """`request.user.profile` is the ACCOUNTS profile — no display_name on
        it at all — so this was wrong twice over and 500'd for everybody."""
        r = self.c.get("/api/economy/coachz/studio/")
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertEqual(r.data["coach"]["name"], "brandnew")

    def test_post_progression_opens(self):
        """The tab every member lands on after signing in, 500ing per card."""
        p = Post.objects.create(author=self.u, title="t", description="d")
        r = self.c.get(f"/api/economy/postz/{p.pk}/progression/")
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertEqual(r.data["battle"]["current"], 0)

    def test_progression_counts_real_ratings(self):
        """`p.ratings` was not a relation, and `item_rating_median(p)` was
        handed the POST where every other caller passes the item key — so the
        collab number was a hard zero for this endpoint's whole life and would
        have looked deliberate if the line above it had not 500'd."""
        from .models import ItemRating
        p = Post.objects.create(author=self.u, title="t", description="d")
        for i, score in enumerate((8, 9, 10)):
            ItemRating.objects.create(user=User.objects.create_user(f"r{i}", f"r{i}@m.test", "pw12345!"),
                                      item_id=f"post:{p.pk}", score=score)
        r = self.c.get(f"/api/economy/postz/{p.pk}/progression/")
        self.assertEqual(r.data["battle"]["current"], 3)
        self.assertGreater(r.data["collab"]["current"], 0,
                           "the collab median is still reading nothing")

    def test_every_tab_endpoint_a_new_member_lands_on_answers(self):
        """The sweep, as a test. Anything a tab calls on open, for an account
        with no history — a 500 here is a tab that greets somebody with an
        error on their first visit."""
        opens = [
            "/api/economy/limits/", "/api/economy/karmaz/", "/api/economy/lilith/",
            "/api/economy/earn/", "/api/economy/ratez/", "/api/economy/logz/",
            "/api/economy/coachz/studio/", "/api/economy/observationz/",
            "/api/economy/questz/", "/api/economy/members/", "/api/economy/offerz/funnel/",
            "/api/singz/progress/", "/api/rapz/progress/",
        ]
        broken = []
        for path in opens:
            try:
                code = self.c.get(path).status_code
            except Exception as e:                      # pragma: no cover
                broken.append(f"{path} raised {type(e).__name__}: {e}")
                continue
            if code >= 500:
                broken.append(f"{path} -> {code}")
        self.assertFalse(broken, "tabs that greet a new member with an error:\n  "
                                 + "\n  ".join(broken))
