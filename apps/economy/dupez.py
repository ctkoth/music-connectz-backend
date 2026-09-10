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
import os
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    AccountClaim,
    AccountIP,
    DupeFlag,
    JournalEntry,
    Post,
    SharedAddress,
    Upload,
    membership_for,
    notify,
    wallet_for,
)
from .rulez import rule
from .views import is_owner, is_owner_candidate

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
    # Weak, and it is the most important weak one to keep weak. See the note
    # above `AccountIP` for why a shared address proves nothing in a music app:
    # a studio, a college, a carrier's NAT and the app's own referral loop all
    # produce it, and every one of those is a room of different people.
    "same_address": ("Signed up from the same address", WEAK),
}

# How many accounts an address may accumulate before it is obviously a shared
# one rather than one person. Past this, flagging every new signup is noise
# that makes the owner stop reading the queue — which is worse than not
# flagging at all. Env-tunable so it can be dialled without a deploy, the way
# `TRIAL_MAX_MB` is.
ADDRESS_CROWD = int(os.environ.get("DUPEZ_ADDRESS_CROWD", "8"))

# How many addresses to remember per account, and for how long. An address log
# that grows without limit is a tracking database nobody asked for; these two
# numbers are what keep it a duplicate check.
ADDRESS_KEEP_PER_USER = 12
ADDRESS_KEEP_DAYS = 180


def _email(u):
    return (getattr(u, "email", "") or "").strip().lower()


def _oauth_emails(u):
    return {(i.email or "").strip().lower()
            for i in u.oauth_identities.all() if (i.email or "").strip()}


def _oauth_uids(u):
    return {(i.provider, i.provider_uid) for i in u.oauth_identities.all()}


def _ips(u):
    """Addresses this account SIGNED UP from. Not every address it has visited.

    A sighting is where somebody happened to be; a signup address is where the
    account came from, which is the only one that says anything about how it
    came to exist. Comparing every sighting would put two members who once used
    the same café on the same list.
    """
    return {a.ip for a in u.addresses.all() if a.signup and a.ip}


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

    shared_ips = _ips(a) & _ips(b)
    for ip in sorted(shared_ips):
        out.append({"key": "same_address", "detail": ip})

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
    strong_pairs = set()  # Track which pairs had strong signals
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
                    if has_strong(sig):
                        strong_pairs.add((min(a.id, b.id), max(a.id, b.id)))
        groups.append({
            "accounts": [account_card(u) for u in members],
            "suggested_keep": members[0].username,
            "pairs": pairs,
        })

    # Find weak-signal-only pairs (accounts with signals but no strong connection)
    weak_pairs = []
    checked = set()
    for bucket in _candidate_pairs(users):
        for i, a in enumerate(bucket):
            for b in bucket[i + 1:]:
                pair_id = (min(a.id, b.id), max(a.id, b.id))
                if pair_id in checked or pair_id in strong_pairs:
                    continue
                checked.add(pair_id)
                sig = signals_between(a, b)
                if sig and not has_strong(sig):  # Only weak signals
                    weak_pairs.append({"a": a.username, "b": b.username, "signals": sig})

    # Return both strong groups and weak pairs
    return {"groups": groups, "weak_pairs": weak_pairs}


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


# ---- Addresses: recording one, and flagging a signup ----------------------


def client_ip(request):
    """The caller's address, best effort. Never raises, never blocks a signup.

    An address is a hint for a human to look at, so a proxy sending something
    unexpected costs us a hint and must not cost somebody their registration.
    """
    try:
        fwd = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
        return (fwd or request.META.get("REMOTE_ADDR") or "")[:64]
    except (AttributeError, TypeError):
        return ""


def remember_address(user, request, *, signup=False):
    """Record where this account was seen, and prune what is no longer needed.

    Bounded on purpose. An address log that grows forever is a tracking
    database nobody asked for, and this one exists for a single question:
    was this account made from somewhere another account was made from.
    """
    ip = client_ip(request)
    if not user or not ip:
        return None
    row, created = AccountIP.objects.get_or_create(
        user=user, ip=ip, defaults={"signup": signup})
    if not created:
        row.hits += 1
        # `signup` only ever goes true. An account created here and visited
        # again later is still an account created here.
        if signup and not row.signup:
            row.signup = True
        row.save(update_fields=["hits", "signup", "last_seen"])

    # Prune: sightings age out, signup addresses never do.
    cutoff = timezone.now() - timedelta(days=ADDRESS_KEEP_DAYS)
    AccountIP.objects.filter(user=user, signup=False, last_seen__lt=cutoff).delete()
    extra = list(AccountIP.objects.filter(user=user, signup=False)
                 .order_by("-last_seen")[ADDRESS_KEEP_PER_USER:]
                 .values_list("id", flat=True))
    if extra:
        AccountIP.objects.filter(id__in=extra).delete()
    return row


def flag_signup(user, request):
    """Raise a DupeFlag when a new account is made where another one was.

    Deliberately ONLY a flag. Nothing is blocked, nothing is deleted, and the
    new member is told nothing unless something stronger than the address
    agrees — because on a studio wifi or a carrier's NAT the honest reading of
    "somebody else signed up here" is "somebody else lives here", and messaging
    a legitimate new member about it is an accusation dressed as a courtesy.
    """
    remember_address(user, request, signup=True)
    ip = client_ip(request)
    if not ip or SharedAddress.objects.filter(ip=ip).exists():
        return None

    others = list(
        User.objects.filter(addresses__ip=ip, addresses__signup=True)
        .exclude(id=user.id).distinct()
        .prefetch_related("oauth_identities").select_related("referred_by")[:ADDRESS_CROWD + 1]
    )
    if not others:
        return None
    if len(others) >= ADDRESS_CROWD:
        # A crowd is a place, not a person. Flagging every signup from a
        # college or a rehearsal room would fill the queue with the members
        # this platform exists for, and a queue nobody can read is one nobody
        # reads the real entries in either.
        return None

    signals, strong = [], False
    for other in others:
        sig = signals_between(user, other)
        if has_strong(sig):
            strong = True
        signals.append({"username": other.username, "signals": sig})

    flag = DupeFlag.objects.create(
        user=user, ip=ip, others=[o.username for o in others],
        signals=signals, strong=strong,
    )
    if strong:
        # Only now, and phrased as the rule rather than an accusation: at this
        # point something other than the address agrees, so the likeliest
        # reader is somebody who genuinely already has an account and would
        # rather have one than two.
        r = rule("one_account") or {}
        notify(user, "system",
               (r.get("rule") or "One person, one account.")
               + " Open DupeZ if one of these is already yours.",
               item_id="dupez")
    return flag


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
        owner = is_owner(me) or is_owner_candidate(me)
        result = duplicate_groups()
        groups = result["groups"]
        weak_pairs = result["weak_pairs"]

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
            weak_pairs = []  # Members don't see weak pairs

        return Response({
            "owner": owner,
            "groups": groups,
            "weak_pairs": weak_pairs,
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
        # SELF-SERVE needs proof, not a hunch — and `has_strong` is what
        # "proof" means here. It was `account_email` alone, which
        # `accounts_user_email_ci_uniq` (accounts.0002) then made unreachable:
        # the database refuses a second account on one address, so two live
        # accounts cannot share one and that signal can no longer fire. Gating
        # on the strength rather than on the one signal keeps the path open for
        # the case that DOES still happen, and is the case this module was
        # written for — different addresses, one verified sign-in behind both.
        #
        # It is not a weaker bar. A shared provider identity means the same
        # person authenticated with the provider on both accounts, which is at
        # least as good as two rows agreeing on a string. Anything WEAK still
        # waits for the owner, which is the whole reason weak signals never
        # group anybody.
        proven = has_strong(signals)

        if proven:
            card = account_card(target)
            owed = _forfeit(card)
            if str(d.get("confirm", "")) != "DELETE":
                return Response({
                    "needs_confirm": True,
                    "account": card,
                    # The cost/gain rule applied to the most expensive action in
                    # the app: the whole list of what goes, and what arrives,
                    # BEFORE the button that does it.
                    "sweeps_cents": owed,
                    "detail": (
                        "Both accounts are provably yours, so you can close that "
                        "one yourself."
                        + (f" Its {owed / 100:.2f} moves to this account."
                           if owed else "")
                        + ' Send {"confirm": "DELETE"} to do it.'
                    ),
                }, status=status.HTTP_409_CONFLICT)
            # `keep` is the claimant, so the cash sweeps to THEM rather than
            # being destroyed — and a member closing their own duplicate is not
            # made to wait on a review to keep money that was already theirs.
            # `delete_duplicate` is still the only thing that moves it, so the
            # "may never destroy money" guard and the KIND_TRANSFER receipt are
            # the same ones every other delete path goes through.
            return Response(delete_duplicate(
                target, request.user, by=request.user,
                reason="provably the same person, closed by the member"))

        claim = _open_claim(request.user, target, signals, note)
        return Response({"claim": _claim_dict(claim), "detail": (
            "Filed. Nothing here PROVES the two are the same person, so the other "
            "account has to confirm it before anything is deleted. They've been "
            "asked — you'll be told either way."
        )}, status=status.HTTP_202_ACCEPTED)


def _open_claim(claimant, target, signals, note):
    claim, _ = AccountClaim.objects.update_or_create(
        claimant=claimant, target=target,
        defaults={"note": note, "signals": signals, "status": AccountClaim.OPEN,
                  "resolved_by": None, "resolved_note": "", "resolved_at": None},
    )
    # The person who actually KNOWS is the account being claimed. An owner
    # looking at two weak signals is guessing from further away than they are,
    # so they are asked rather than adjudicated — and asked in a notification
    # that names what would happen, because the answer deletes an account.
    notify(target, "system",
           f"@{claimant.username} says this account is also theirs and wants to "
           f"close it. Only you can confirm that.",
           actor=claimant, item_id="dupez")
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
        if not (is_owner(request.user) or is_owner_candidate(request.user)):
            return Response({"detail": "owner only"}, status=status.HTTP_403_FORBIDDEN)
        state = (request.query_params.get("status") or AccountClaim.OPEN).lower()
        rows = AccountClaim.objects.select_related("claimant", "target")
        if state != "all":
            rows = rows.filter(status=state)
        return Response({"claims": [_claim_dict(c, with_cards=True) for c in rows[:100]]})

    def post(self, request):
        if not (is_owner(request.user) or is_owner_candidate(request.user)):
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
        if not (is_owner(request.user) or is_owner_candidate(request.user)):
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
        if is_owner(target) or is_owner_candidate(target):
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


class DupeZFlagsView(APIView):
    """The system-raised half of the owner's queue. GET open flags; POST settles one.

    Separate from `DupeZReviewView` because the two say different things: a
    claim is a member asking, a flag is the platform noticing. Settling a flag
    never deletes anything — the owner clears it, marks the address shared, or
    goes and uses the delete endpoint deliberately. Nothing here is one tap
    away from destroying an account.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not (is_owner(request.user) or is_owner_candidate(request.user)):
            return Response({"detail": "owner only"}, status=status.HTTP_403_FORBIDDEN)
        state = (request.query_params.get("status") or DupeFlag.OPEN).lower()
        rows = DupeFlag.objects.select_related("user")
        if state != "all":
            rows = rows.filter(status=state)
        out = []
        for f in rows[:100]:
            out.append({
                "id": f.id,
                "user": f.user.username,
                "account": account_card(f.user),
                "ip": f.ip,
                "others": f.others,
                "signals": f.signals,
                # Said in the row rather than left to the reader: an address on
                # its own is not evidence of anything.
                "strong": f.strong,
                "status": f.status,
                "created_at": f.created_at.isoformat(),
                "resolved_note": f.resolved_note,
            })
        return Response({
            "flags": out,
            "shared_addresses": list(
                SharedAddress.objects.values("ip", "note", "created_at")[:200]),
            "crowd": ADDRESS_CROWD,
            "rule": rule("one_account"),
        })

    def post(self, request):
        if not (is_owner(request.user) or is_owner_candidate(request.user)):
            return Response({"detail": "owner only"}, status=status.HTTP_403_FORBIDDEN)
        d = request.data or {}
        flag = DupeFlag.objects.filter(id=d.get("id")).select_related("user").first()
        if not flag:
            return Response({"detail": "no such flag"}, status=status.HTTP_404_NOT_FOUND)
        note = str(d.get("note", ""))[:2000]
        if d.get("shared"):
            # One studio, one college, one carrier NAT — marked once and it
            # stops raising flags forever. This is what keeps the queue
            # readable, which is what keeps it read.
            SharedAddress.objects.get_or_create(
                ip=flag.ip, defaults={"note": note or "marked shared from a flag",
                                      "added_by": request.user})
            DupeFlag.objects.filter(ip=flag.ip, status=DupeFlag.OPEN).update(
                status=DupeFlag.CLEARED, resolved_by=request.user,
                resolved_note=note or "shared address", resolved_at=timezone.now())
            return Response({"cleared_address": flag.ip})
        flag.status = DupeFlag.CLEARED if d.get("action", "clear") == "clear" else DupeFlag.ACTIONED
        flag.resolved_by, flag.resolved_note = request.user, note
        flag.resolved_at = timezone.now()
        flag.save(update_fields=["status", "resolved_by", "resolved_note", "resolved_at"])
        return Response({"flag": flag.id, "status": flag.status})


class DupeZVerifyView(APIView):
    """The account being claimed answers for itself.

    A weak signal — two accounts on one invite, or one address — is a
    coincidence as often as it is a person, and an owner reading it is guessing
    from further away than the account itself is. So a weak claim asks the
    TARGET, who is the only party that actually knows.

    Two things this must not become:

    * **A way to take somebody's account by asking nicely.** The answer deletes
      an account and moves its balance, so the question states both in full and
      the confirmation is explicit — the same bar the self-serve path uses on
      somebody's own account.
    * **A way to find out who somebody is.** The claimant's name is shown
      because you cannot answer "is this you?" without it, and nothing else
      about them is.

    Saying no is final and costs the target nothing: the claim is refused and
    their account is untouched. Saying nothing is also an answer — an
    unanswered claim stays open for the owner's queue rather than lapsing into
    a delete.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = (AccountClaim.objects
                .filter(target=request.user, status=AccountClaim.OPEN)
                .select_related("claimant"))
        return Response({"claims": [{
            "id": c.id,
            "claimant": c.claimant.username,
            "note": c.note,
            "signals": c.signals,
            "created_at": c.created_at,
            # What agreeing would do, before they agree to it.
            "deletes": account_card(request.user),
            "sweeps_cents": _forfeit(account_card(request.user)),
        } for c in rows]})

    def post(self, request):
        d = request.data or {}
        claim = AccountClaim.objects.filter(
            pk=d.get("claim"), target=request.user, status=AccountClaim.OPEN
        ).first()
        if not claim:
            return Response({"detail": "No open claim on this account."},
                            status=status.HTTP_404_NOT_FOUND)

        if not d.get("agree"):
            claim.status = AccountClaim.REFUSED
            claim.resolved_by = request.user
            claim.resolved_note = str(d.get("note", ""))[:2000] or "Not me."
            claim.resolved_at = timezone.now()
            claim.save(update_fields=["status", "resolved_by", "resolved_note",
                                      "resolved_at"])
            notify(claim.claimant, "system",
                   f"@{request.user.username} says that account isn't yours.",
                   actor=request.user, item_id="dupez")
            return Response({"claim": _claim_dict(claim),
                             "detail": "Refused. Your account is untouched."})

        card = account_card(request.user)
        if str(d.get("confirm", "")) != "DELETE":
            return Response({
                "needs_confirm": True,
                "account": card,
                "sweeps_cents": _forfeit(card),
                "detail": (
                    f"This closes THIS account and everything on it."
                    + (f" Its {_forfeit(card) / 100:.2f} moves to "
                       f"@{claim.claimant.username}." if _forfeit(card) else "")
                    + ' Send {"confirm": "DELETE"} if that is what you want.'
                ),
            }, status=status.HTTP_409_CONFLICT)

        receipt = delete_duplicate(request.user, claim.claimant, by=request.user,
                                   reason=f"confirmed by the account itself "
                                          f"(claim #{claim.id})")
        # The row outlives the account it was about — CASCADE would take the
        # claim with the target and leave the claimant's side of the story with
        # nothing behind it.
        AccountClaim.objects.filter(pk=claim.pk).update(
            status=AccountClaim.APPROVED, resolved_note="Confirmed by the target.",
            resolved_at=timezone.now())
        notify(claim.claimant, "system",
               f"That account was confirmed as yours and closed.",
               item_id="dupez")
        return Response(receipt)
