"""Link previews — the growth loop's last inch.

Every social crawler reads static HTML and none of them run JavaScript, so
`index.html`'s single fixed `og:title` meant every link ever shared out of this
platform previewed as "Music ConnectZ — Connect Through Music" with the house
card. Share a member's profile: the house card. Share a scored take: the house
card. The thing being shared was the one thing the preview did not mention.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.economy.models import Post, profile_for

User = get_user_model()
PW = "hunter2hunter2"


class ProfileCardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("k-oth", "k@e.com", PW)
        p = profile_for(self.user)
        p.display_name = "K-Oth"
        p.bio = "I make things."
        p.personas = [{"key": "producer", "name": "Producer",
                       "skills": [{"name": "Violin"}, {"name": "Mixing"}]}]
        p.save()

    def test_the_card_names_the_member_not_the_site(self):
        r = self.client.get("/api/economy/share/u/k-oth")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('<title>K-Oth — Music ConnectZ</title>', body)
        self.assertIn('property="og:title" content="K-Oth — Music ConnectZ"', body)

    def test_their_skills_are_the_description(self):
        # The reason a stranger would care, rather than the site tagline
        # repeated under somebody's name.
        body = self.client.get("/api/economy/share/u/k-oth").content.decode()
        self.assertIn("Violin", body)
        self.assertIn("Mixing", body)

    def test_the_canonical_url_is_the_page_a_person_opens(self):
        body = self.client.get("/api/economy/share/u/k-oth").content.decode()
        self.assertIn('rel="canonical" href="https://musicconnectz.net/u/k-oth"', body)

    def test_a_reader_is_sent_to_the_app(self):
        # Same content to both, which is what keeps this the opposite of
        # cloaking: the crawler reads the head and stops, a browser redirects.
        body = self.client.get("/api/economy/share/u/k-oth").content.decode()
        self.assertIn('location.replace("/u/k-oth")', body)

    def test_a_member_with_no_bio_still_gets_a_sentence(self):
        p = profile_for(self.user)
        p.bio = ""
        p.personas = []
        p.save()
        body = self.client.get("/api/economy/share/u/k-oth").content.decode()
        self.assertIn("makes music on Music ConnectZ", body)

    def test_an_unknown_member_is_404_not_a_blank_card(self):
        self.assertEqual(self.client.get("/api/economy/share/u/ghost").status_code, 404)

    def test_the_member_s_avatar_is_not_published_by_this(self):
        # It would make the card far more clickable and nothing public serves
        # it today, so shipping it here would publish somebody's face as a side
        # effect of an SEO change.
        body = self.client.get("/api/economy/share/u/k-oth").content.decode()
        self.assertIn("og-card.png", body)
        self.assertNotIn("avatars/", body)


class PostCardTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user("author", "a@e.com", PW)

    def make(self, **kw):
        return Post.objects.create(author=self.author, title="Night Drive",
                                   description="A first take.", **kw)

    def test_the_card_names_the_track_and_the_artist(self):
        p = self.make(visibility="public")
        body = self.client.get(f"/api/economy/share/p/{p.pk}").content.decode()
        self.assertIn("Night Drive — author on Music ConnectZ", body)

    def test_the_score_is_in_the_description_because_it_is_the_shareable_part(self):
        p = self.make(visibility="public", score={"score": 8})
        body = self.client.get(f"/api/economy/share/p/{p.pk}").content.decode()
        self.assertIn("Scored 8/10 by the coach", body)

    def test_a_private_post_does_not_leak_its_title_through_a_preview(self):
        # A real disclosure dressed as a nicety.
        p = self.make(visibility="private")
        self.assertEqual(self.client.get(f"/api/economy/share/p/{p.pk}").status_code, 404)

    def test_a_restricted_post_is_not_previewable_either(self):
        p = self.make(visibility="restricted")
        self.assertEqual(self.client.get(f"/api/economy/share/p/{p.pk}").status_code, 404)

    def test_a_missing_post_is_404(self):
        self.assertEqual(self.client.get("/api/economy/share/p/999999").status_code, 404)

    def test_no_login_is_needed_to_read_a_public_card(self):
        # A crawler has no session. If this ever needs auth the whole feature
        # silently stops working and nothing fails loudly.
        p = self.make(visibility="public")
        self.assertEqual(self.client.get(f"/api/economy/share/p/{p.pk}").status_code, 200)
