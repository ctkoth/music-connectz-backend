"""Building a game into something playable, and serving it safely.

Two halves, and the second is the one with teeth.

## Building

Most small web games have no build step at all — an `index.html`, a `main.js`
and some sprites ARE the game. That case never touches a container: the files
are zipped straight out of the database, which is instant, free, and has no
failure modes worth the name. A sandbox for a job with no compiler in it would
be infrastructure theatre.

A game that DOES declare a `build_command` gets a real `SandboxSession` — which
means the StatZ tier the sandbox already gates on, and Energy by the second, on
exactly the terms `occ_run.py` already charges. Source goes in, the command
runs, the output comes back. Binary assets are merged into the bundle
afterwards rather than pushed through the container, because they are static
files the game references by URL and a heredoc is a poor way to move a PNG.

`block_network=True` throughout, so a build cannot fetch dependencies. They have
to be committed to the project. That is a real constraint and the endpoint says
so up front rather than letting a member discover it when `npm install` hangs.

## Serving — the part that matters

A game is member-authored JavaScript. Served from the app's own origin it can
read another member's session: cookies, tokens, `localStorage`. So every
response carries `Content-Security-Policy: sandbox allow-scripts`, which puts
the document in an opaque origin — scripts run, but same-origin access to
anything of ours is gone.

Deliberately on the RESPONSE rather than only as an iframe attribute: a
`sandbox` attribute protects the frame our app renders, and does nothing at all
when somebody opens the bundle URL directly in a tab. The header survives that.

`allow-same-origin` is never sent. Paired with `allow-scripts` it lets a
document remove its own sandbox, which would undo the entire exercise.

The cost of doing this properly: a sandboxed game has **no `localStorage`**.
Save data has to go through the API. That is a real limitation and it is stated
in the endpoint rather than discovered by a member whose high scores vanish.
"""
import io
import mimetypes
import zipfile

from django.core.files.base import ContentFile
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import limits_for
from .models import MB, Game, OccFile, normalize_occ_path, wallet_for, membership_for
from .modal_sandbox import ENERGY_PER_SECOND, NEEDS_TIER, price_for
from .modal_sandbox import configured as sandbox_configured
from .modal_sandbox import unavailable_reason
from .modal_session import SandboxSession
from .occ_spec import tier_at_least

# Where a build is expected to leave its output. Checked in order; the first one
# that exists wins, and a project with none of them is treated as already built.
BUILD_OUTPUT_DIRS = ("dist", "build", "public", "out")

# The whole bundle, zipped. A cap so one runaway build can't fill the disk;
# generous enough for a real 2D game with audio.
MAX_BUNDLE_MB = 200

# What a game is allowed to do inside its sandbox. `allow-same-origin` is
# absent on purpose — with `allow-scripts` it lets the document drop its own
# sandbox, which would make the header decorative.
CSP_SANDBOX = "sandbox allow-scripts allow-pointer-lock"


def bundle_csp():
    """The policy every served game file carries.

    Deliberately just the sandbox and a framing rule. An earlier version of this
    added `default-src 'none'` with a hand-written allowlist, which would have
    blocked essentially every real game: a game's own `<script src="main.js">`
    is a subresource of a document the sandbox has already put in an OPAQUE
    origin, so `'self'` is not a source expression that can be relied on to
    match it. The result would have been a strict-looking header and a blank
    screen.

    The isolation that matters does not come from the resource directives
    anyway — it comes from `sandbox`. An opaque origin cannot read our cookies,
    our `localStorage`, or the parent document, and requests it makes to our own
    API are cross-origin without credentials. A game can still talk to the
    internet, which is the member's own code doing the member's own business;
    what it cannot do is reach another member's session, and that is the line
    this is drawn on.
    """
    return f"{CSP_SANDBOX}; frame-ancestors 'self'"


def _safe_members(names):
    """Zip entries that are safe to serve, keyed by their normalised path.

    A bundle is built from member-supplied paths, so it can contain `..`
    entries. Nothing here ever extracts to disk — entries are read by name — but
    a traversal that reaches the namelist is still a traversal waiting for the
    day somebody adds an extract, so it is filtered at the door.
    """
    safe = {}
    for name in names:
        if name.endswith("/"):
            continue
        clean = normalize_occ_path(name)
        if clean:
            safe.setdefault(clean, name)
    return safe


def build_game(game):
    """Build `game` and store its bundle. Returns a result dict, never raises.

    Charges Energy only when a sandbox actually ran, and only for the seconds it
    was open — the rule `occ_run.py` bills on.
    """
    user = game.user
    files = list(OccFile.objects.filter(user=user, project=game.project)
                 .values_list("path", "content"))
    assets = list(game.assets.select_related("upload"))
    if not files and not assets:
        return {"ok": False,
                "detail": f"There's nothing in the '{game.project}' project to "
                          "build. Write the game in OCC first."}

    game.status = Game.STATUS_BUILDING
    game.save(update_fields=["status", "updated_at"])

    charged, detail = 0, ""
    built = {path: content.encode("utf-8") for path, content in files}

    if game.build_command:
        outcome = _run_build(game, files)
        if not outcome["ok"]:
            game.status = Game.STATUS_FAILED
            game.build_detail = outcome["detail"][:4000]
            game.save(update_fields=["status", "build_detail", "updated_at"])
            return outcome
        built = outcome["files"]
        charged = outcome["charged"]
        detail = outcome["detail"]

    # Assets land after the build. They are static files the game references by
    # URL, so pushing a PNG through a shell heredoc would buy nothing.
    for entry in assets:
        path = normalize_occ_path(entry.path)
        if not path:
            continue
        try:
            entry.upload.file.open("rb")
            built[path] = entry.upload.file.read()
        finally:
            entry.upload.file.close()

    entry_point = _find_entry(built)
    if not entry_point:
        game.status = Game.STATUS_FAILED
        game.build_detail = ("No index.html anywhere in the build. A web game "
                             "needs one — it's the page the browser opens.")
        game.save(update_fields=["status", "build_detail", "updated_at"])
        return {"ok": False, "detail": game.build_detail, "charged": charged}

    blob = io.BytesIO()
    with zipfile.ZipFile(blob, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, data in sorted(built.items()):
            zf.writestr(path, data)
    size = blob.tell()
    if size > MAX_BUNDLE_MB * MB:
        game.status = Game.STATUS_FAILED
        game.build_detail = (f"That build is {size / MB:.1f}MB — the limit is "
                             f"{MAX_BUNDLE_MB}MB.")
        game.save(update_fields=["status", "build_detail", "updated_at"])
        return {"ok": False, "detail": game.build_detail, "charged": charged}

    if game.bundle:
        game.bundle.delete(save=False)      # replace, don't accumulate
    game.bundle.save(f"bundle-{int(timezone.now().timestamp())}.zip",
                     ContentFile(blob.getvalue()), save=False)
    game.bundle_bytes = size
    game.entry = entry_point
    game.status = Game.STATUS_PLAYABLE
    game.built_at = timezone.now()
    game.build_detail = detail or f"{len(built)} file(s), {size / MB:.2f}MB"
    game.save()
    return {"ok": True, "charged": charged, "files": len(built),
            "entry": entry_point, "bytes": size, "detail": game.build_detail}


def _find_entry(built):
    """The page the browser opens. Shallowest index.html wins."""
    candidates = [p for p in built if p.rsplit("/", 1)[-1] == "index.html"]
    return min(candidates, key=lambda p: (p.count("/"), len(p))) if candidates else ""


def _run_build(game, files):
    """Run the declared build command in a live sandbox and collect its output."""
    session = SandboxSession()
    try:
        session.open()
    except Exception as exc:
        # Nothing came up, so nothing is charged.
        return {"ok": False, "detail": str(exc)[:500], "charged": 0}

    try:
        session.materialise(files)
        result = session.exec(
            f"cd {session.workdir} && {game.build_command}", timeout=300)
        if not result.get("ok") or result.get("exit_code") != 0:
            tail = (result.get("stderr") or result.get("stdout") or "")[-2000:]
            return {"ok": False, "charged": _charge(game.user, session),
                    "detail": f"The build failed.\n\n{tail}"}

        # Where did it put its output? First match wins; a project that builds
        # in place is treated as already built.
        listing = session.exec(
            f"cd {session.workdir} && ls -d {' '.join(BUILD_OUTPUT_DIRS)} 2>/dev/null")
        found = [d for d in (listing.get("stdout") or "").split()
                 if d in BUILD_OUTPUT_DIRS]
        root = f"{session.workdir}/{found[0]}" if found else session.workdir

        # base64 so binary output survives the trip back out.
        dump = session.exec(
            f"cd {root} && find . -type f -print0 | while IFS= read -r -d '' f; do "
            f"printf '%s\\t' \"${{f#./}}\"; base64 -w0 \"$f\"; printf '\\n'; done",
            timeout=120)
        built = {}
        for line in (dump.get("stdout") or "").splitlines():
            if "\t" not in line:
                continue
            name, _, b64 = line.partition("\t")
            path = normalize_occ_path(name)
            if not path:
                continue
            import base64
            try:
                built[path] = base64.b64decode(b64)
            except Exception:
                continue
        if not built:
            return {"ok": False, "charged": _charge(game.user, session),
                    "detail": "The build ran but produced no files."}
        return {"ok": True, "files": built, "charged": _charge(game.user, session),
                "detail": f"Built with `{game.build_command}` — {len(built)} file(s)."}
    finally:
        session.close()


def _charge(user, session):
    """Energy for the seconds the sandbox was actually open."""
    session.close()                      # settle the clock before pricing it
    cost = price_for(session.elapsed_seconds)
    w = wallet_for(user)
    cost = min(cost, max(0, w.energy))
    if cost:
        w.energy -= cost
        w.save(update_fields=["energy", "updated_at"])
    return cost


class GameBuildView(APIView):
    """GET what a build would cost; POST to run one."""

    permission_classes = [IsAuthenticated]

    def _get(self, request, pk):
        return Game.objects.filter(user=request.user, pk=pk).first()

    def get(self, request, pk):
        game = self._get(request, pk)
        if game is None:
            return Response({"detail": "No such game."},
                            status=status.HTTP_404_NOT_FOUND)
        tier = membership_for(request.user).tier
        needs_sandbox = bool(game.build_command)
        allowed = (not needs_sandbox) or (
            tier_at_least(tier, NEEDS_TIER) and sandbox_configured())
        return Response({
            "build_command": game.build_command,
            "needs_sandbox": needs_sandbox,
            "allowed": allowed,
            "reason": "" if allowed else (
                unavailable_reason() or
                "Running a build command needs StatZ — it's a container per "
                "build, and that's what the tier pays for."),
            # The price, before the button. A no-command build is genuinely free.
            "cost": ({"resource": "energy", "per_second": ENERGY_PER_SECOND}
                     if needs_sandbox else None),
            "energy": wallet_for(request.user).energy,
            "max_bundle_mb": MAX_BUNDLE_MB,
            "billing_note": (
                "Charged by the second for the sandbox this build runs in. A "
                "build that never starts costs nothing."
                if needs_sandbox else
                "This project has no build command, so its files are the game. "
                "Packaging them is free."),
            "network_note": (
                "Builds run with no network, so dependencies have to be committed "
                "to the project — `npm install` can't reach out during a build."),
        })

    def post(self, request, pk):
        game = self._get(request, pk)
        if game is None:
            return Response({"detail": "No such game."},
                            status=status.HTTP_404_NOT_FOUND)
        if "build_command" in (request.data or {}):
            game.build_command = str(request.data["build_command"] or "").strip()[:200]
            game.save(update_fields=["build_command", "updated_at"])

        if game.build_command:
            tier = membership_for(request.user).tier
            if not sandbox_configured():
                return Response({"detail": unavailable_reason()},
                                status=status.HTTP_503_SERVICE_UNAVAILABLE)
            if not tier_at_least(tier, NEEDS_TIER):
                return Response(
                    {"detail": "Running a build command needs StatZ — it's a "
                               "container per build, and that's what the tier "
                               "pays for.",
                     "required_tier": NEEDS_TIER},
                    status=status.HTTP_403_FORBIDDEN)

        from .gamez import game_dict
        result = build_game(game)
        game.refresh_from_db()
        payload = {**result, "game": game_dict(game, request)}
        return Response(
            payload,
            status=status.HTTP_201_CREATED if result.get("ok")
            else status.HTTP_400_BAD_REQUEST)


class GamePlayView(APIView):
    """Serve one file out of a built bundle, sandboxed.

    Authenticated like everything else, and scoped to the owner until a game is
    shared — a bundle URL is not a capability to hand out.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk, path=""):
        game = Game.objects.filter(pk=pk).first()
        if game is None or not game.playable:
            return Response({"detail": "That game isn't playable yet."},
                            status=status.HTTP_404_NOT_FOUND)
        # Yours, or shared. Anything else is somebody's unreleased work.
        if game.user_id != request.user.id and not game.shared_post_id:
            return Response({"detail": "That game isn't playable yet."},
                            status=status.HTTP_404_NOT_FOUND)

        # An unusable path is treated as no path at all, so a traversal lands on
        # the entry page rather than anywhere interesting.
        requested = normalize_occ_path(path)
        wanted = requested or game.entry
        try:
            with zipfile.ZipFile(game.bundle) as zf:
                safe = _safe_members(zf.namelist())
                member = safe.get(wanted)
                if member is None:
                    # Deliberately NOT falling back to the entry page: a missing
                    # sprite.png answered with index.html is a 200 carrying the
                    # wrong content type, which is a far more confusing thing for
                    # a game to receive than a plain 404.
                    return Response({"detail": "No such file in this game."},
                                    status=status.HTTP_404_NOT_FOUND)
                data = zf.read(member)
        except (zipfile.BadZipFile, FileNotFoundError, OSError):
            return Response({"detail": "That game's bundle can't be read. Rebuild it."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if wanted == game.entry or member == game.entry:
            Game.objects.filter(pk=game.pk).update(plays=game.plays + 1)

        content_type = mimetypes.guess_type(member)[0] or "application/octet-stream"
        response = HttpResponse(data, content_type=content_type)
        # The whole point. See the module docstring: on the response, not just
        # on an iframe attribute, so it survives being opened directly.
        response["Content-Security-Policy"] = bundle_csp()
        response["X-Content-Type-Options"] = "nosniff"
        # `private`, because a member's game is not something a shared proxy
        # should hold. `no-cache` because the play URL does NOT change between
        # builds — it has no bundle name or version in it — so a max-age here
        # would serve a member their old game for that long after they rebuilt,
        # with nothing on screen to explain why. Revalidating every time is the
        # cost of a stable URL, and the ETag below makes that cheap.
        response["Cache-Control"] = "private, no-cache"
        if game.built_at:
            response["ETag"] = f'"{int(game.built_at.timestamp())}-{wanted}"'
        return response
