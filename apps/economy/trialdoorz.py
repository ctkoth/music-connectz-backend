"""The doors into the trial — every coach a stranger can reach without an account.

`/try/singz` and `/try/rapz` were the whole front door for the life of this
platform, and they were never the whole product: `INSTRUMENT_APP_KEYS` mounts
`/api/<key>/trial/` for seven instruments, so GuitarZ, BassZ, KeyZ, DrumZ and
ViolinZ each had a working, scored, no-account coach that nothing linked to.
Five doors, built and paid for, that no visitor could find.

That is the reachability gap `test_instrument_routes` already pins one layer
down — a profile in `instruments.py` is not the same as a route — pushed one
layer further out: **a route is not the same as a door.** An endpoint nobody
can navigate to converts nobody, and it is invisible from the funnel, because
a step no visitor can reach never appears as a drop-off.

So the list is published rather than retyped. The frontend holding its own
copy of "which apps have a trial" is the second place a list lives, and the
usual thing then happens: an instrument gets added here, the door does not
follow, and the gap this module exists to close reopens quietly.
"""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.economy.instruments import profile_for_app


def door_keys():
    """Just the keys, for anything validating an `app_key` off the wire.

    The funnel's own meta allowlist was `("singz", "rapz")` typed into
    views.py — so the day a GuitarZ door opened, every event it fired would
    have had its app dropped on the way in and the new door would have read
    as zero traffic rather than as traffic. A closed set is right; a second
    copy of the set is not.
    """
    from music_connectz.urls import INSTRUMENT_APP_KEYS
    return tuple(INSTRUMENT_APP_KEYS)


def doors():
    """Every trial door, in the order the front door should offer them.

    Read from the URL conf, not from a list here: a door is a door because
    the route exists, and anything else is this module's opinion about what
    got mounted.
    """
    from music_connectz.urls import INSTRUMENT_APP_KEYS

    out = []
    for key in INSTRUMENT_APP_KEYS:
        p = profile_for_app(key)
        out.append({
            "app_key": key,
            "label": p["label"],
            # "vocal coach", "drum coach" — the thing on the other side of the
            # door, in the words the coach itself uses.
            "coach": p["coach"],
            "performer": p["performer"],
            # What one take is actually scored on, from the instrument's own
            # profile. A door that says what it measures is a door somebody
            # can tell is meant for them — a drummer reading "pitch, breath,
            # range" correctly concludes this place is not for drummers.
            "scores": list(p["scores"].values()),
        })
    return out


class TrialDoorsView(APIView):
    """GET /api/economy/trialdoorz/ — the coaches open with no account.

    Logged-out, like `rulez` and for the same reason: the screen that needs
    it most is the one nobody is signed in on.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"doors": doors()})
