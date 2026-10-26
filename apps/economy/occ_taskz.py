"""OCC TaskZ, GitZ, SuggestionZ, AutomationZ — one list of what OCC is doing.

The spec's own priority: «prioritize git integration synchronous with taskz
because git integration becomes a task». So a git action is not a side channel
with its own screen — it is a TaskZ row, with the same status, the same live
progress, and the same undo window as an edit. One list, one truth.

Two toggles decide how a SUGGESTED task starts:

* **SuggestionZ** (Premium) proposes tasks and must explain WHAT, WHY and HOW
  before anything runs. All three or it isn't a suggestion, it's an assertion.
* **AutomationZ** (StatZ) performs the suggestions that are safe to take without
  asking, and NOTIFIES you as it happens. Off by default — a setting that acts
  on your code unasked is not one to inherit silently.

**A task a member types in is a to-do, and nothing runs it.** It used to be
created `queued`, flagged `automated` when AutomationZ was on, and announced with
"🤖 OCC ran '…' automatically" — while no worker, no job and no loop anywhere
picked a queued row up. A notification claiming work that never happened is the
worst thing this module could send, so it sends nothing: what OCC really runs
(the sandbox, the agent loop, the suggestions in `occ_suggest`) writes its own
task rows as it goes, and those are the only ones that say "ran".

A task is only undoable if OCC can actually put it back. "Undo" that can't
reverse anything is a button that lies, so `undoable` is computed from whether a
REVERSER exists for the recorded action (`occ_suggest.REVERSIBLE`), never from
whether a payload merely exists — a payload is a record of what was done, and the
undo endpoint used to flip a status label and report a reversal nothing performed.
"""
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .occ_guard import repo_attempt
from .models import (
    OccTask,
    notify,
    membership_for,
    occ_settings_for,
    occ_undo_window,
)
from .occ_suggest import can_reverse, reverse
from .occ_spec import (
    EXPORT_ROUTES,
    GAME_GENRES,
    OCC_IMAGE_EXPORTS,
    OCC_TOGGLES,
    languages_for,
    tabs_for,
    tier_at_least,
)


def task_dict(t, tier):
    return {
        "id": t.id,
        "title": t.title,
        "kind": t.kind,
        "status": t.status,
        "what": t.what,
        "why": t.why,
        "how": t.how,
        "progress": t.progress,
        "eta_seconds": t.eta_seconds,
        "detail": t.detail,
        # "OCC did this without being asked" — said only when OCC recorded what it
        # did. Rows written before this was fixed carry the flag from a POST that
        # ran nothing, and they must not start claiming work if a member later
        # ticks them off by hand.
        "automated": bool(t.automated and t.status in (OccTask.STATUS_DONE, OccTask.STATUS_UNDONE)
                          and t.undo_payload),
        "run_seconds": t.run_seconds,
        "git": ({"repo": t.git_repo, "branch": t.git_branch, "ref": t.git_ref}
                if t.kind == OccTask.KIND_GIT else None),
        # Computed, never assumed — see the module docstring.
        "undoable": bool(t.can_undo(tier) and can_reverse(t.undo_payload)),
        "undo_deadline": (t.undo_deadline(tier).isoformat()
                          if t.status == OccTask.STATUS_DONE and can_reverse(t.undo_payload)
                          else None),
        "undo_window_seconds": occ_undo_window(tier),
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "finished_at": t.finished_at.isoformat() if t.finished_at else None,
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
    }


class OccSpecView(APIView):
    """GET /api/economy/occ/spec/ — the tabs, toggles, languages and taxonomy.

    Served rather than hardcoded on the client so a tab's gate can't differ
    between the menu that offers it and the endpoint that refuses it. Locked
    tabs are RETURNED marked locked, not filtered out: a menu that silently
    shrinks teaches a member nothing about what the tier above them has.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Imported here: occ_run imports occ_workz, which imports postz — a
        # module-level import would make that a cycle.
        from .modal_sandbox import NEEDS_TIER as SANDBOX_TIER
        from .modal_sandbox import configured as sandbox_configured
        from .modal_sandbox import unavailable_reason
        from .occ_run import run_status

        tier = membership_for(request.user).tier
        sandbox_ready = sandbox_configured() and not unavailable_reason()
        sandbox_why = unavailable_reason()
        allowed_langs, locked_langs = languages_for(tier)
        return Response({
            "tier": tier,
            "tabs": tabs_for(tier),
            "toggles": [{**t, "allowed": tier_at_least(tier, t["needs"])}
                        for t in OCC_TOGGLES],
            "languages": allowed_langs,
            "languages_locked": locked_langs,
            "game_genres": [{"key": k, "name": n, "emoji": e, "subgenres": subs}
                            for k, n, e, subs in GAME_GENRES],
            "image_exports": OCC_IMAGE_EXPORTS,
            "export_routes": EXPORT_ROUTES,
            "undo_window_seconds": occ_undo_window(tier),
            # Answered from the configuration, never asserted. When the sandbox
            # tokens are set this flips to True by itself; until then it stays
            # False and `execute_note` says exactly why, because a Run button
            # that does nothing is worse than no Run button.
            "can_execute": bool(sandbox_ready and tier_at_least(tier, SANDBOX_TIER)),
            "execute_note": (
                sandbox_why or
                ("OCC runs your code in a sandbox — a fresh container per run, no "
                 "network, charged by the second."
                 if tier_at_least(tier, SANDBOX_TIER) else
                 "Running code is a StatZ feature — it's a container per run, and "
                 "that's what the tier pays for.")
            ),
            "execute": run_status(request.user),
        })


class OccSettingsView(APIView):
    """GET / PATCH the two toggles and the Pick ConnectZ pins."""

    permission_classes = [IsAuthenticated]

    def _payload(self, request):
        s = occ_settings_for(request.user)
        tier = membership_for(request.user).tier
        return {
            "automation": s.automation,
            "suggestionz": s.suggestionz,
            "pinned_tabs": s.pinned_tabs or [],
            "automation_allowed": tier_at_least(tier, "statz"),
            "suggestionz_allowed": tier_at_least(tier, "premium"),
            # Free pins 2 and the rest is filled in; paid tiers pin what they like.
            "pin_limit": None if tier_at_least(tier, "premium") else 2,
            "tier": tier,
        }

    def get(self, request):
        return Response(self._payload(request))

    def patch(self, request):
        s = occ_settings_for(request.user)
        tier = membership_for(request.user).tier
        d = request.data or {}
        changed = []

        if "automation" in d:
            if bool(d["automation"]) and not tier_at_least(tier, "statz"):
                return Response(
                    {"detail": "AutomationZ is a StatZ feature — it runs tasks on your code "
                               "without asking, so it's the top tier's call.",
                     "required_tier": "statz"},
                    status=status.HTTP_403_FORBIDDEN,
                )
            s.automation = bool(d["automation"])
            changed.append("automation")

        if "suggestionz" in d:
            if bool(d["suggestionz"]) and not tier_at_least(tier, "premium"):
                return Response(
                    {"detail": "SuggestionZ is a Premium feature.", "required_tier": "premium"},
                    status=status.HTTP_403_FORBIDDEN,
                )
            s.suggestionz = bool(d["suggestionz"])
            changed.append("suggestionz")

        if isinstance(d.get("pinned_tabs"), list):
            pins = [str(x)[:32] for x in d["pinned_tabs"]][:40]
            limit = self._payload(request)["pin_limit"]
            if limit is not None and len(pins) > limit:
                return Response(
                    {"detail": f"Free pins {limit} — the rest of the footer is filled in for you. "
                               "Premium and StatZ pin as many as they like.",
                     "pin_limit": limit},
                    status=status.HTTP_403_FORBIDDEN,
                )
            s.pinned_tabs = pins
            changed.append("pinned_tabs")

        if changed:
            s.save(update_fields=changed + ["updated_at"])
        return Response(self._payload(request))


class OccTasksView(APIView):
    """GET the task list; POST adds one.

    A task added here is a to-do: it starts QUEUED (the stored word for "on the
    list") and waits for the member to tick it off. Nothing picks it up — see the
    module docstring. A SuggestionZ task starts SUGGESTED and waits to be read.
    The AutomationZ/SuggestionZ difference lives in `occ_suggest`, where
    something actually runs.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tier = membership_for(request.user).tier
        qs = OccTask.objects.filter(user=request.user)
        kind = request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        state = request.query_params.get("status")
        if state:
            qs = qs.filter(status=state)
        tasks = [task_dict(t, tier) for t in qs[:200]]
        return Response({
            "tasks": tasks,
            "open": sum(1 for t in tasks if t["status"] in
                        (OccTask.STATUS_SUGGESTED, OccTask.STATUS_QUEUED, OccTask.STATUS_RUNNING)),
            "undo_window_seconds": occ_undo_window(tier),
        })

    def post(self, request):
        d = request.data or {}
        title = str(d.get("title", "")).strip()
        if not title:
            return Response({"detail": "Give the task a title."},
                            status=status.HTTP_400_BAD_REQUEST)
        kind = str(d.get("kind", "")).lower()
        if kind not in dict(OccTask.KIND_CHOICES):
            kind = OccTask.KIND_OTHER

        tier = membership_for(request.user).tier
        suggested = bool(d.get("suggested"))

        what = str(d.get("what", "") or "")
        why = str(d.get("why", "") or "")
        how = str(d.get("how", "") or "")
        if suggested and not (what and why and how):
            # The spec is explicit: what, why and how must be explained. All
            # three or it isn't a suggestion, it's an assertion.
            return Response(
                {"detail": "A suggestion has to say what it will do, why, and how. "
                           "All three.",
                 "missing": [k for k, v in (("what", what), ("why", why), ("how", how)) if not v]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if kind == OccTask.KIND_GIT and not tier_at_least(tier, "statz"):
            return Response(
                {"detail": "GitZ is a StatZ feature — upgrade in MembershipZ.",
                 "required_tier": "statz"},
                status=status.HTTP_403_FORBIDDEN,
            )

        refused = repo_attempt(request.user, " ".join(str(d.get(k, "") or "") for k in
                                                      ("git_repo", "title", "what", "how", "detail")), "taskz")
        if refused:
            return Response({"detail": refused, "flagged": True}, status=status.HTTP_403_FORBIDDEN)
        task = OccTask.objects.create(
            user=request.user, title=title[:200], kind=kind,
            status=(OccTask.STATUS_SUGGESTED if suggested else OccTask.STATUS_QUEUED),
            what=what, why=why, how=how,
            eta_seconds=max(0, int(d.get("eta_seconds") or 0)),
            detail=str(d.get("detail", "") or ""),
            git_repo=str(d.get("git_repo", "") or "")[:200],
            git_branch=str(d.get("git_branch", "") or "")[:120],
            git_ref=str(d.get("git_ref", "") or "")[:80],
            # No `undo_payload` and no `automated` from the client: both are
            # records of something OCC DID, written by the code that did it. A
            # payload sent from outside could only ever be a reversal OCC has no
            # reverser for, and a flag sent from outside is the claim "OCC ran
            # this" with nothing behind it.
        )
        return Response(task_dict(task, tier), status=status.HTTP_201_CREATED)


class OccTaskDetailView(APIView):
    """PATCH advances a task; DELETE cancels one that hasn't run."""

    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        t = OccTask.objects.filter(pk=pk, user=request.user).first()
        if not t:
            return Response({"detail": "task not found"}, status=status.HTTP_404_NOT_FOUND)
        tier = membership_for(request.user).tier
        d = request.data or {}
        changed = []

        new_status = str(d.get("status", "")).lower()
        if new_status in dict(OccTask.STATUS_CHOICES):
            if new_status == OccTask.STATUS_RUNNING and not t.started_at:
                t.started_at = timezone.now()
                changed.append("started_at")
            if new_status in (OccTask.STATUS_DONE, OccTask.STATUS_FAILED):
                t.finished_at = timezone.now()
                changed.append("finished_at")
            t.status = new_status
            changed.append("status")

        if "progress" in d:
            try:
                t.progress = max(0, min(100, int(d["progress"])))
                changed.append("progress")
            except (TypeError, ValueError):
                pass
        for field, cap in (("eta_seconds", None), ("detail", None)):
            if field in d:
                setattr(t, field, max(0, int(d[field])) if field == "eta_seconds"
                        else str(d[field]))
                changed.append(field)
        # `undo_payload` is deliberately not patchable — see OccTasksView.post.

        if changed:
            t.save(update_fields=list(dict.fromkeys(changed + ["updated_at"])))
        return Response(task_dict(t, tier))

    def delete(self, request, pk):
        t = OccTask.objects.filter(pk=pk, user=request.user).first()
        if not t:
            return Response({"detail": "task not found"}, status=status.HTTP_404_NOT_FOUND)
        if t.status in (OccTask.STATUS_DONE, OccTask.STATUS_UNDONE):
            return Response({"detail": "That one already ran — undo it instead."},
                            status=status.HTTP_409_CONFLICT)
        t.status = OccTask.STATUS_CANCELLED
        t.save(update_fields=["status", "updated_at"])
        return Response(task_dict(t, membership_for(request.user).tier))


class OccTaskUndoView(APIView):
    """POST /api/economy/occ/taskz/<pk>/undo/ — inside the tier's window.

    Puts the change back, then says so. The order is the point: this used to set
    the status to "undone" and notify "↩️ OCC undid '…'" without reading the
    payload at all, so the member was told a reversal had happened that nothing
    had performed. Now the reverser runs first, inside one transaction with the
    status change, and a task OCC cannot reverse is refused rather than relabelled.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        t = OccTask.objects.filter(pk=pk, user=request.user).first()
        if not t:
            return Response({"detail": "task not found"}, status=status.HTTP_404_NOT_FOUND)
        tier = membership_for(request.user).tier
        if t.status != OccTask.STATUS_DONE:
            return Response({"detail": f"You can only undo a finished task — that one is {t.status}."},
                            status=status.HTTP_409_CONFLICT)
        if not t.undo_payload or not can_reverse(t.undo_payload):
            # Better to refuse than to claim a reversal nothing can perform.
            return Response({"detail": "OCC has no way to put that one back, so it can't be undone."},
                            status=status.HTTP_409_CONFLICT)
        if not t.can_undo(tier):
            return Response(
                {"detail": f"The undo window has passed — it's {occ_undo_window(tier) // 60} minutes on your tier.",
                 "undo_window_seconds": occ_undo_window(tier),
                 "undo_deadline": t.undo_deadline(tier).isoformat()},
                status=status.HTTP_403_FORBIDDEN,
            )
        with transaction.atomic():
            # Locked and re-read: two taps on Undo must reverse once, not twice.
            t = OccTask.objects.select_for_update().get(pk=t.pk)
            if t.status != OccTask.STATUS_DONE:
                return Response({"detail": f"You can only undo a finished task — that one is {t.status}."},
                                status=status.HTTP_409_CONFLICT)
            said = reverse(request.user, t.undo_payload)
            t.status = OccTask.STATUS_UNDONE
            t.detail = said
            t.save(update_fields=["status", "detail", "updated_at"])
        notify(request.user, "occ", f"↩️ OCC undid '{t.title}' — {said}.")
        return Response(task_dict(t, tier))
