"""DupeZ — one person, more than one account, and the one safe way out of it.

The rule is `rulez.one_account`: every member gets one account. This is the
module named as its `enforced_by`, and what it enforces is deliberately narrow,
because **the enforcement is a deletion and a deletion is the most irreversible
thing this app does to a member.**

So nothing here decides anything on its own. Three rules hold the whole file:

* **Nothing is inferred and acted on.** `signals_between` reports the facts two
  accounts SHARE — the same email, the same OAuth email, the same referrer. It
  returns a list of reasons, never a score. A "78% likely duplicate" would be
  exactly the failure the substance rule names: a number nobody can check,
  behind an action nobody can undo. A person reads the reasons and decides.
* **A member may only ever ask about their OWN other account.** Every path
  starts from the signed-in member. There is no "report this person for having
  two accounts" — that door gets used for something else within a week.
* **The owner decides, except where the member can prove it.** Two accounts
  carrying the same email is a member's own business and they may close the
  other one themselves. Anything weaker is a claim, and it waits.

## What a delete may destroy, and what it may not

`AccountDeleteView` has always deleted a wallet holding real money without
mentioning it. That is survivable when it is your own account and your own
decision. It is not survivable here, where the account being deleted is often
not the one pressing the button — so a delete that would destroy **money or
royalties** is refused unless that balance is first swept to the account being
kept.

Money and royalties sweep. **Energy, SpinaZ, PromptZ and XP do not**, and the
line is not arbitrary: cash is the member's, and destroying it is taking it,
but the game resources are exactly what a second account exists to farm.
Sweeping those would turn the tidy-up into the payout — make three accounts,
collect three lots of onboarding, merge them into one. The duplicate's game
balance dies with the duplicate, which is the only answer that does not pay
for the thing the rule forbids.
"""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    AccountClaim,
    JournalEntry,
    Post,
    Upload,
    membership_for,
    notify,
    wallet_for,
)
from .rulez import rule
from .views import is_owner

User = get_user_model()

# A signal is a FACT two accounts share, with how much it is worth trusting.
#
# "strong" means the two accounts carry the same verified-ish identity and it
# would be a real coincidence for them to be different people. "weak" means it
# is worth an owner's eye and nothing more — a shared referrer is two friends
# who joined together at least as often as it is one person twice.
STRONG = "strong"
WEAK = "weak"

SIGNAL_LABELS = {
    "account_email": ("Same account email", STRONG),
    "oauth_email": ("Same email on a linked sign-in", STRONG),
    "oauth_provider_uid": ("Same third-party account linked", STRONG),
    "same_referrer": ("Referred by the same member", WEAK),
    "referral_chain": ("One referred the other", WEAK),
}


def _email(u):
    return (getattr(u, "email", "") or "").strip().lower()


def _oauth_emails(u):
    return {(i.email or "").strip().lower()
            for i in u.oauth_identities.all() if (i.email or "").strip()}


def _oauth_uids(u):
    return {(i.provider, i.provider_uid) for i in u.oauth_identities.all()}


def signals_between(a, b):
    """Every fact these two accounts share, each named and weighted.

    A list, never a score. The owner is deciding whether to delete somebody's
    account; what they need is the reasons, in words they can check against the
    two rows in front of them.
    """
    out = []
    ea, eb = _email(a), _email(b)
    if ea and ea == eb:
        out.append({"key": "account_email", "detail": ea})

    shared_oauth = _oauth_emails(a) & _oauth_emails(b)
    for e in sorted(shared_oauth):
        # The case Corey has: two accounts registered under different emails,
        # both signed in with the same Google or SoundCloud identity. The
        # command that shipped before this could not find these at all — it
        # queried `oauthidentity__email`, and the reverse name is
        # `oauth_identities`, so that branch raised FieldError the moment a
        # real cross-email duplicate existed.
        out.append({"key": "oauth_email", "detail": e})

    for provider, uid in sorted(_oauth_uids(a) & _oauth_uids(b)):
        out.append({"key": "oauth_provider_uid", "detail": provider})

    ra = getattr(a, "referred_by", None)
    rb = getattr(b, "referred_by", None)
    if ra and rb and ra.referrer_id == rb.referrer_id:
        out.append({"key": "same_referrer", "detail": ra.referrer.username})
    if (ra and ra.referrer_id == b.id) or (rb and rb.referrer_id == a.id):
        out.append({"key": "referral_chain", "detail": ""})

    for s in out:
        label, weight = SIGNAL_LABELS.get(s["key"], (s["key"], WEAK))
        s["label"], s["weight"] = label, weight
    return out


def has_strong(signals):
    return any(s.get("weight") == STRONG for s in signals)


def account_card(u):
    """What this account IS, so nothing is ever deleted blind.

    Every number here is something a delete destroys. Showing them beside the
    button is the cost/gain rule applied to the most expensive action in the
    app: the price of pressing it is this whole list.
    """
    w = wallet_for(u)
    m = membership_for(u)
    return {
        "username": u.username,
        "email": u.email or "",
        "joined": u.date_joined.isoformat() if u.date_joined else None,
        "last_login": u.last_login.isoformat() if u.last_login else None,
        "tier": m.tier,
        "is_owner": is_owner(u),
        "posts": Post.objects.filter(author=u).count(),
        "uploads": Upload.objects.filter(user=u).count(),
        "journal_entries": JournalEntry.objects.filter(author=u).count(),
        # Cents, both of them, and named so no client divides one and not the
        # other. These are the two that a delete must never quietly destroy.
        "money_cents": w.money_cents,
        "royalties_cents": w.royalties_cents,
        "energy": w.energy,
        "spinaz": w.spinaz,
        "promptz": w.promptz,
        "sign_ins": sorted({i.provider for i in u.oauth_identities.all()}),
    }


def _candidate_pairs(users):
    """Accounts that share an email or a sign-in, keyed for a cheap pairing.

    Built from indexes rather than by comparing every account with every other
    one: this runs for the owner over the whole platform, and an O(n²) walk of
    the member table is a screen that stops loading the year it starts working.
    """
    by_key = {}
    for u in users:
        keys = set()
        if _email(u):
            keys.add(("account_email", _email(u)))
        for e in _oauth_emails(u):
            keys.add(("oauth_email", e))
        for provider, uid in _oauth_uids(u):
            keys.add(("oauth_uid", provider, uid))
        for k in keys:
            by_key.setdefault(k, []).append(u)
    return [group for group in by_key.values() if len(group) > 1]


def duplicate_groups(users=None):
    """Groups of accounts tied together by at least one strong signal.

    Only strong signals build a group. A shared referrer is worth showing once
    two accounts are already in front of the owner for another reason; it is
    not worth accusing two people who joined on the same invite.
    """
    if users is None:
        users = User.objects.all().prefetch_related("oauth_identities").select_related("referred_by")
    users = list(users)

    # Union-find over the candidate buckets, so an account linked to a second
    # by email and to a third by a sign-in comes out as one group of three
    # rather than two overlapping pairs the owner has to reconcile by eye.
    parent = {u.id: u.id for u in users}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    by_id = {u.id: u for u in users}
    for bucket in _candidate_pairs(users):
        first = bucket[0]
        for other in bucket[1:]:
            if has_strong(signals_between(first, other)):
                union(first.id, other.id)

    clusters = {}
    for u in users:
        clusters.setdefault(find(u.id), []).append(u)

    groups = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda u: (u.date_joined or timezone.now()))
        # The oldest account is SUGGESTED, never chosen. It is usually the one
        # somebody built on, and it is just as often not — which is why this is
        # a default in a form and not a decision this function makes.
        pairs = []
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                sig = signals_between(a, b)
                if sig:
                    pairs.append({"a": a.username, "b": b.username, "signals": sig})
        groups.append({
            "accounts": [account_card(u) for u in members],
            "suggested_keep": members[0].username,
            "pairs": pairs,
        })
    return groups


def _forfeit(card):
    """Cash that a delete would destroy. The one thing that blocks it."""
    return (card["money_cents"] or 0) + (card["royalties_cents"] or 0)


@transaction.atomic
def delete_duplicate(target, keep=None, *, by, reason=""):
    """Delete `target`, sweeping its CASH to `keep` first. Returns a receipt.

    Raises ValueError when the delete would destroy money and there is nowhere
    to put it — the caller turns that into a 400 that says the amount. A member
    finding out afterwards that a balance is gone is not a thing this app gets
    to do twice.
    """
    card = account_card(target)
    owed = _forfeit(card)
    if owed and keep is None:
        raise ValueError(
            f"That account holds {owed / 100:.2f} in money and royalties. "
            f"Name an account to sweep it to — deleting it would destroy it."
        )
    swept = {"money_cents": 0, "royalties_cents": 0}
    if owed and keep is not None:
        src, dst = wallet_for(target), wallet_for(keep)
        swept = {"money_cents": src.money_cents, "royalties_cents": src.royalties_cents}
        dst.money_cents += src.money_cents
        dst.royalties_cents += src.royalties_cents
        dst.save(update_fields=["money_cents", "royalties_cents", "updated_at"])
        src.money_cents = src.royalties_cents = 0
        src.save(update_fields=["money_cents", "royalties_cents", "updated_at"])
        # Cash moved between accounts leaves a line, like every other movement.
        # A balance that appears with no reason behind it is the exact thing
        # LogZ exists to stop.
        from .models import Transaction
        if swept["money_cents"]:
            Transaction.objects.create(
                user=keep, kind=Transaction.KIND_TRANSFER, resource=Transaction.RES_MONEY,
                amount_cents=swept["money_cents"],
                note=f"swept from duplicate account @{target.username}")
    username = target.username
    if keep is not None:
        notify(keep, "system",
               f"@{username} was removed as your duplicate account.", item_id="dupez")
    target.delete()
    return {
        "deleted": username, "kept": keep.username if keep else None,
        "swept": swept, "was": card, "by": by.username, "reason": reason,
    }


# ---- Endpoints -------------------------------------------------------------


class DupeZView(APIView):
    """GET → duplicate groups.

    The owner sees every group on the platform. A member sees only groups they
    are in, and only when a STRONG signal ties them to it — a weak tie would
    mean showing somebody a stranger's handle and email because they happened
    to share a referrer, which is a people-search built by accident.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        me = request.user
        owner = is_owner(me)
        groups = duplicate_groups()
        if not owner:
            mine = []
            for g in groups:
                names = [a["username"] for a in g["accounts"]]
                if me.username not in names:
                    continue
                # Every OTHER account in the group must be strongly tied to me
                # specifically, not merely to somebody else in the group.
                others = [u for u in User.objects.filter(username__in=names)
                          .prefetch_related("oauth_identities").select_related("referred_by")
                          if u.id != me.id]
                if all(has_strong(signals_between(me, u)) for u in others):
                    mine.append(g)
            groups = mine
        return Response({
            "owner": owner,
            "groups": groups,
            # The rule these groups exist to enforce, served with them so the
            # screen never retypes it.
            "rule": rule("one_account"),
        })


class DupeZClaimView(APIView):
    """POST {username, note, confirm} — "that account is also me".

    Two outcomes, and which one you get is decided by whether you can PROVE it:

    * **Same email on both accounts** → you may close the other one yourself,
      with `confirm: "DELETE"`. It is your account and your email; needing an
      owner's permission to tidy up your own mess would be a queue that exists
      to make people wait.
    * **Anything else** → a claim, reviewed by the owner. Different emails
      cannot be told apart from somebody pointing at an account that is not
      theirs, and the difference matters because the answer is a deletion.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = AccountClaim.objects.filter(claimant=request.user).select_related("target")
        return Response({"claims": [_claim_dict(c) for c in rows]})

    def post(self, request):
        d = request.data or {}
        username = str(d.get("username", "")).strip()
        target = User.objects.filter(username__iexact=username).first()
        if not target:
            return Response({"detail": "No account by that name."},
                            status=status.HTTP_404_NOT_FOUND)
        if target.id == request.user.id:
            return Response({"detail": "That is the account you are signed in to."},
                            status=status.HTTP_400_BAD_REQUEST)
        if is_owner(target):
            # Not a special case for its own sake: the owner account is how
            # every one of these gets reviewed, and a claim that can delete the
            # reviewer is a way to take the platform's admin down with a form.
            return Response({"detail": "That account can't be claimed."},
                            status=status.HTTP_400_BAD_REQUEST)

        signals = signals_between(request.user, target)
        note = str(d.get("note", ""))[:2000]
        same_email = any(s["key"] == "account_email" for s in signals)

        if same_email:
            card = account_card(target)
            owed = _forfeit(card)
            if owed:
                # The one thing a member may not do to themselves by accident.
                # It becomes a claim so somebody looks at where the money goes.
                return Response({
                    "claim": _claim_dict(_open_claim(request.user, target, signals, note)),
                    "detail": (f"That account holds {owed / 100:.2f}. It needs a review "
                               f"so the balance moves to this account rather than vanishing."),
                }, status=status.HTTP_202_ACCEPTED)
            if str(d.get("confirm", "")) != "DELETE":
                return Response({
                    "needs_confirm": True,
                    "account": card,
                    "detail": ('Both accounts use the same email, so you can close that one '
                               'yourself. Send {"confirm": "DELETE"} to do it.'),
                }, status=status.HTTP_409_CONFLICT)
            return Response(delete_duplicate(target, request.user, by=request.user,
                                             reason="same email, closed by the member"))

        claim = _open_claim(request.user, target, signals, note)
        return Response({"claim": _claim_dict(claim), "detail": (
            "Filed. The accounts use different emails, so this one is reviewed by "
            "the owner before anything is deleted — you'll be told either way."
        )}, status=status.HTTP_202_ACCEPTED)


def _open_claim(claimant, target, signals, note):
    claim, _ = AccountClaim.objects.update_or_create(
        claimant=claimant, target=target,
        defaults={"note": note, "signals": signals, "status": AccountClaim.OPEN,
                  "resolved_by": None, "resolved_note": "", "resolved_at": None},
    )
    return claim


def _claim_dict(c, with_cards=False):
    out = {
        "id": c.id,
        "claimant": c.claimant.username,
        "target": c.target.username,
        "note": c.note,
        "signals": c.signals,
        "status": c.status,
        "created_at": c.created_at.isoformat(),
        "resolved_note": c.resolved_note,
        "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
    }
    if with_cards:
        out["claimant_account"] = account_card(c.claimant)
        out["target_account"] = account_card(c.target)
    return out


class DupeZReviewView(APIView):
    """The owner's queue. GET open claims; POST {id, action, note} to settle one.

    Private, and that is the reason it is not a BugReport: BugZ's queue is
    public on purpose so nobody files the same bug twice, and a claim names two
    accounts and the evidence tying them together. Filing one there would
    publish which handles belong to the same person, for everybody who ever
    came forward under the rule that asks them to.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not is_owner(request.user):
            return Response({"detail": "owner only"}, status=status.HTTP_403_FORBIDDEN)
        state = (request.query_params.get("status") or AccountClaim.OPEN).lower()
        rows = AccountClaim.objects.select_related("claimant", "target")
        if state != "all":
            rows = rows.filter(status=state)
        return Response({"claims": [_claim_dict(c, with_cards=True) for c in rows[:100]]})

    def post(self, request):
        if not is_owner(request.user):
            return Response({"detail": "owner only"}, status=status.HTTP_403_FORBIDDEN)
        d = request.data or {}
        claim = AccountClaim.objects.filter(id=d.get("id")).select_related("claimant", "target").first()
        if not claim:
            return Response({"detail": "no such claim"}, status=status.HTTP_404_NOT_FOUND)
        action = str(d.get("action", "")).lower()
        note = str(d.get("note", ""))[:2000]
        if action not in ("approve", "refuse"):
            return Response({"detail": "action must be approve or refuse"},
                            status=status.HTTP_400_BAD_REQUEST)

        if action == "refuse":
            claim.status, claim.resolved_by = AccountClaim.REFUSED, request.user
            claim.resolved_note, claim.resolved_at = note, timezone.now()
            claim.save(update_fields=["status", "resolved_by", "resolved_note", "resolved_at"])
            # Refused in writing. A claim that goes quiet is indistinguishable
            # from one nobody read, and the member is left not knowing whether
            # their other account is about to disappear.
            notify(claim.claimant, "system",
                   f"Your claim on @{claim.target.username} wasn't approved."
                   + (f" {note}" if note else ""), item_id="dupez")
            return Response({"claim": _claim_dict(claim)})

        claimant, target = claim.claimant, claim.target
        try:
            receipt = delete_duplicate(target, claimant, by=request.user, reason=note)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        # The claim row goes with the target (FK cascade), so the receipt is
        # what is left of it — which is why the receipt carries the account as
        # it was rather than a pointer to a row that no longer exists.
        notify(claimant, "system",
               f"@{receipt['deleted']} was removed as your duplicate account.",
               item_id="dupez")
        return Response({"resolved": "approved", "receipt": receipt})


class DupeZDeleteView(APIView):
    """The owner override. POST {username, keep, confirm, reason}.

    This is the only door in the app through which one account deletes another
    without the other's consent, so it is deliberately awkward: it names the
    account, it names where anything of value goes, and it will not move
    without the confirmation string. `keep` is optional only when there is no
    cash to lose.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not is_owner(request.user):
            return Response({"detail": "owner only"}, status=status.HTTP_403_FORBIDDEN)
        d = request.data or {}
        target = User.objects.filter(username__iexact=str(d.get("username", "")).strip()).first()
        if not target:
            return Response({"detail": "No account by that name."},
                            status=status.HTTP_404_NOT_FOUND)
        if target.id == request.user.id:
            return Response({"detail": "That is the account you are signed in to. "
                                       "Use account deletion for your own."},
                            status=status.HTTP_400_BAD_REQUEST)
        if is_owner(target):
            # Owner accounts are how everything here is reviewed and how the
            # platform is administered. Removing one takes a database.
            return Response({"detail": "An owner account can't be deleted here."},
                            status=status.HTTP_400_BAD_REQUEST)
        keep = None
        keep_name = str(d.get("keep", "")).strip()
        if keep_name:
            keep = User.objects.filter(username__iexact=keep_name).first()
            if not keep:
                return Response({"detail": f"No account called {keep_name} to keep."},
                                status=status.HTTP_404_NOT_FOUND)
            if keep.id == target.id:
                return Response({"detail": "keep and username are the same account."},
                                status=status.HTTP_400_BAD_REQUEST)
        if str(d.get("confirm", "")) != "DELETE":
            return Response({"needs_confirm": True, "account": account_card(target),
                             "detail": 'Send {"confirm": "DELETE"} to delete this account.'},
                            status=status.HTTP_409_CONFLICT)
        try:
            receipt = delete_duplicate(target, keep, by=request.user,
                                       reason=str(d.get("reason", ""))[:2000])
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(receipt)
