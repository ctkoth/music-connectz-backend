"""CoverZ / RemixeZ: the original's cut of a derivative's royalties.

Corey left the percent to us. **20%** of what the cover or remix earns goes to the author of the
post it was made from, and the rest splits among the derivative's own credited people as before.

Why a cut and not a payout, and why this number (a recommendation, Corey's to move — one constant):

* **It is a split of money the derivative already earned, never new money.** Nobody mints anything
  by covering a song, so there is nothing to farm: a member who "covers" their own track from a
  second account is moving cash from one pocket to another, which is worth nothing — the
  PartnerZ test ("would this be worth anything to somebody faking it?") answers no.
* **It follows the derivative's rating.** The cut comes off the pot AFTER the post's own
  (median − 5) × 10% factor, so a poorly rated cover pays the original less too, and the original is
  never paid for plays the cover did not earn.
* **20% is the smaller half of the work.** The original is the song or the art; the derivative is
  the performance or the rework. Under a fifth reads as a credit with a coin attached; over a third
  starts to make covering somebody unprofitable, and a cover nobody posts pays the original nothing.
* **Said before it is posted**, on the composer, from `GET /api/economy/derivedz/` — a split
  discovered in a statement is a bill, not a price.

A deleted original still has its credit snapshot, and its author still gets the cut while the
account exists. It never goes to the poster, and never to nobody: if the author is gone the whole
pot stays with the derivative.
"""
from django.contrib.auth import get_user_model

DERIVED_ROYALTY_PCT = 20


def terms():
    return {"pct": DERIVED_ROYALTY_PCT,
            "text": (f"{DERIVED_ROYALTY_PCT}% of what this earns goes to the original's author. "
                     "It comes out of your royalties, never on top of them, and a poorly rated "
                     "cover pays the original less too.")}


def original_cut(post, cents, users=None):
    """(original_author | None, cut_cents). `users` is an optional {username: user} cache so one
    accrual run does not look the same author up per post."""
    d = post.derived if isinstance(getattr(post, "derived", None), dict) else {}
    name = d.get("author")
    cents = int(cents or 0)
    if not name or cents <= 0:
        return None, 0
    if users is not None and name in users:
        who = users[name]
    else:
        who = get_user_model().objects.filter(username=name).first()
        if users is not None:
            users[name] = who
    if not who or who.id == post.author_id:
        return None, 0
    cut = (cents * DERIVED_ROYALTY_PCT) // 100
    return (who, cut) if cut >= 1 else (None, 0)


from rest_framework.permissions import IsAuthenticated  # noqa: E402
from rest_framework.response import Response  # noqa: E402
from rest_framework.views import APIView  # noqa: E402


class DerivedTermsView(APIView):
    """GET /api/economy/derivedz/ — the split, stated before a cover or remix is posted."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(terms())
