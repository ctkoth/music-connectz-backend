"""Which build of the API is running.

The frontend and the API deploy independently (CLAUDE.md: backend first), so "the
app is up to date" is two facts, and a member or the owner debugging a screen that
calls an endpoint that isn't there yet needs to see both. The frontend shows its
own commit (src/version.js); this serves the API's.

The commit comes from the host: Render sets RENDER_GIT_COMMIT, other hosts use
GIT_COMMIT or GITHUB_SHA. With none of them set (a dev box) the answer says so
rather than inventing a number. Open to everyone, and nothing in it is secret: a
commit id and a date identify a public repository's state, not a member.
"""
import os

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

_ENV = ("RENDER_GIT_COMMIT", "GIT_COMMIT", "GITHUB_SHA", "SOURCE_VERSION")


def build_info():
    sha = next((os.environ[k] for k in _ENV if os.environ.get(k)), "")
    return {
        "commit": sha[:7] if sha else "dev",
        "service": os.environ.get("RENDER_SERVICE_NAME", ""),
    }


class AppVersionView(APIView):
    """GET → {commit, service}. 'dev' means the host didn't say."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        resp = Response(build_info())
        resp["Cache-Control"] = "no-store"
        return resp
