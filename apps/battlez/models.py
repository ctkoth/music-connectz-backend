"""BattleZ — one post vs another post, with wagering.

Three formats, matching the icons:

    Freestyle 🆓        live, sporadic, anyone can enter
    1v1 1️⃣             one artist vs one artist, whoever helped behind the scenes
    Battle Cypher 🧑‍🤝‍🧑  teams vs teams

The money rule from the spec, implemented literally: **a contestant who is
verified 18+ may back themselves with cash. Everybody else bets SpinAZ.** Those
are two separate pools that settle independently — see `settle()`. Mixing them
would let a spectator's play money win somebody's rent.
"""
from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.economy.models import (DEV_TAX, TIER_FREE, Post, award_spinaz,
                                 credit_funds, membership_for, split_cents,
                                 wallet_for)

FORMAT_FREESTYLE = "freestyle"
FORMAT_1V1 = "1v1"
FORMAT_CYPHER = "cypher"
FORMAT_CHOICES = [
    (FORMAT_FREESTYLE, "Freestyle 🆓"),
    (FORMAT_1V1, "1v1 1️⃣"),
    (FORMAT_CYPHER, "Battle Cypher 🧑‍🤝‍🧑"),
]

SIDE_A, SIDE_B = "a", "b"
SIDE_CHOICES = [(SIDE_A, "Side A"), (SIDE_B, "Side B")]

CURRENCY_MONEY = "money"
CURRENCY_SPINAZ = "spinaz"
CURRENCY_CHOICES = [(CURRENCY_MONEY, "Money"), (CURRENCY_SPINAZ, "SpinAZ")]

STATUS_OPEN = "open"          # accepting entries
STATUS_LIVE = "live"          # running, bets accepted
STATUS_VOTING = "voting"      # entries closed, votes open, no new bets
STATUS_SETTLED = "settled"
STATUS_CANCELLED = "cancelled"
STATUS_CHOICES = [
    (STATUS_OPEN, "Open"), (STATUS_LIVE, "Live"), (STATUS_VOTING, "Voting"),
    (STATUS_SETTLED, "Settled"), (STATUS_CANCELLED, "Cancelled"),
]

# A battle with one bettor is not a market. Below this the pool refunds instead
# of paying out, so nobody "wins" by being the only person who showed up.
MIN_BETTORS_PER_SIDE = 1


class Battle(models.Model):
    format = models.CharField(max_length=12, choices=FORMAT_CHOICES,
                              default=FORMAT_1V1, db_index=True)
    title = models.CharField(max_length=160)
    rules = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                   related_name="battles_created")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES,
                              default=STATUS_OPEN, db_index=True)

    # The two posts going head to head. Freestyle battles start with neither.
    post_a = models.ForeignKey(Post, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="battles_as_a")
    post_b = models.ForeignKey(Post, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="battles_as_b")

    opens_at = models.DateTimeField(default=timezone.now)
    closes_at = models.DateTimeField(null=True, blank=True, db_index=True)
    winner = models.CharField(max_length=1, choices=SIDE_CHOICES, blank=True, default="")
    settled_at = models.DateTimeField(null=True, blank=True)
    # Why it resolved the way it did — shown to everyone, because a wagering
    # market that can't explain its own result is one people stop trusting.
    settlement = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Battle<{self.id}> {self.format} {self.title}"

    # --- membership -------------------------------------------------------

    def contestant_ids(self, side=None):
        qs = self.entries.all()
        if side:
            qs = qs.filter(side=side)
        return set(qs.values_list("user_id", flat=True))

    def side_of(self, user):
        entry = self.entries.filter(user=user).first()
        return entry.side if entry else None

    def is_contestant(self, user):
        return self.entries.filter(user=user).exists()

    @property
    def accepts_entries(self):
        return self.status == STATUS_OPEN

    @property
    def accepts_bets(self):
        return self.status in (STATUS_OPEN, STATUS_LIVE)

    @property
    def accepts_votes(self):
        return self.status in (STATUS_LIVE, STATUS_VOTING)

    def max_per_side(self):
        """1v1 is one artist a side. Freestyle and cypher are open."""
        return 1 if self.format == FORMAT_1V1 else None

    # --- voting -----------------------------------------------------------

    def vote_counts(self):
        counts = {SIDE_A: 0, SIDE_B: 0}
        for row in self.votes.values("side").annotate(n=models.Count("id")):
            counts[row["side"]] = row["n"]
        return counts

    def leading_side(self):
        counts = self.vote_counts()
        if counts[SIDE_A] == counts[SIDE_B]:
            return None
        return SIDE_A if counts[SIDE_A] > counts[SIDE_B] else SIDE_B

    # --- pools ------------------------------------------------------------

    def pool(self, currency, side=None):
        qs = self.bets.filter(currency=currency, refunded=False)
        if side:
            qs = qs.filter(side=side)
        return qs.aggregate(total=models.Sum("amount"))["total"] or 0

    def pools(self):
        return {
            currency: {
                "a": self.pool(currency, SIDE_A),
                "b": self.pool(currency, SIDE_B),
                "total": self.pool(currency),
            }
            for currency in (CURRENCY_MONEY, CURRENCY_SPINAZ)
        }

    # --- settlement -------------------------------------------------------

    @transaction.atomic
    def settle(self, winner=None):
        """Resolve the battle and pay both pools out independently.

        Cash and SpinAZ never cross. A winning cash bettor is paid from the cash
        pool only; a spectator's SpinAZ can't fund somebody's cash winnings, and
        cash can't leak into the play-money economy.

        A side with no losing counterpart is refunded rather than "won" — there
        is nothing to win, and taking a rake off a market that never formed
        would just be a fee for showing up.
        """
        if self.status == STATUS_SETTLED:
            return self.settlement

        winner = winner or self.leading_side()
        if winner is None:
            # A tie refunds everything. Picking a winner by coin flip on
            # somebody's money is not a product decision we get to make.
            return self.refund_all(reason="tie")

        self.winner = winner
        loser = SIDE_B if winner == SIDE_A else SIDE_A
        report = {"winner": winner, "reason": "votes", "currencies": {}}

        for currency in (CURRENCY_MONEY, CURRENCY_SPINAZ):
            won_pool = self.pool(currency, winner)
            lost_pool = self.pool(currency, loser)
            winners = list(self.bets.filter(currency=currency, side=winner,
                                            refunded=False))

            if not winners or lost_pool <= 0:
                # Nothing to distribute — hand every stake back untouched.
                refunded = self._refund(self.bets.filter(currency=currency,
                                                         refunded=False))
                report["currencies"][currency] = {
                    "outcome": "refunded", "reason": "no opposing stake",
                    "refunded": refunded}
                continue

            # The rake comes off the LOSING pool only, so a winner never gets
            # back less than they staked.
            tax_rate = DEV_TAX.get(membership_for(self.created_by).tier,
                                   DEV_TAX[TIER_FREE]) if currency == CURRENCY_MONEY else 0.0
            dev_cut, distributable = split_cents(lost_pool, tax_rate)

            paid = 0
            for bet in winners:
                # Proportional to stake. Integer maths throughout; the remainder
                # is handed to the largest stake below rather than vanishing.
                share = (distributable * bet.amount) // won_pool if won_pool else 0
                bet.payout = bet.amount + share
                bet.settled = True
                bet.save(update_fields=["payout", "settled"])
                paid += share

            remainder = distributable - paid
            if remainder > 0:
                top = max(winners, key=lambda b: b.amount)
                top.payout += remainder
                top.save(update_fields=["payout"])

            for bet in winners:
                self._credit(bet.user, currency, bet.payout,
                             f"BattleZ #{self.id} win")

            for bet in self.bets.filter(currency=currency, side=loser, refunded=False):
                bet.payout = 0
                bet.settled = True
                bet.save(update_fields=["payout", "settled"])

            report["currencies"][currency] = {
                "outcome": "paid", "winning_pool": won_pool,
                "losing_pool": lost_pool, "developer_cut": dev_cut,
                "distributed": distributable, "winners": len(winners)}

        self.status = STATUS_SETTLED
        self.settled_at = timezone.now()
        self.settlement = report
        self.save(update_fields=["status", "winner", "settled_at", "settlement"])
        return report

    @transaction.atomic
    def refund_all(self, reason="cancelled"):
        refunded = self._refund(self.bets.filter(refunded=False))
        self.status = STATUS_CANCELLED if reason == "cancelled" else STATUS_SETTLED
        self.settled_at = timezone.now()
        self.settlement = {"outcome": "refunded", "reason": reason,
                           "refunded": refunded}
        self.save(update_fields=["status", "settled_at", "settlement"])
        return self.settlement

    def _refund(self, bets):
        total = {CURRENCY_MONEY: 0, CURRENCY_SPINAZ: 0}
        for bet in bets:
            self._credit(bet.user, bet.currency, bet.amount,
                         f"BattleZ #{self.id} refund")
            bet.refunded = True
            bet.settled = True
            bet.payout = bet.amount
            bet.save(update_fields=["refunded", "settled", "payout"])
            total[bet.currency] += bet.amount
        return total

    @staticmethod
    def _credit(user, currency, amount, note):
        """Return money that is ALREADY inside the economy.

        Deliberately not `credit_funds` — that taxes a gross deposit coming in
        from a card, and is right for funding a wallet. Using it here would tax
        the money a second time: once as the rake off the losing pool, then
        again on the way back into the winner's wallet. It would also shrink
        every refund, so cancelling a battle would cost the bettors money.
        """
        from apps.economy.models import Transaction

        amount = int(amount or 0)
        if amount <= 0:
            return
        w = wallet_for(user)
        if currency == CURRENCY_MONEY:
            w.money_cents = (w.money_cents or 0) + amount
            w.save(update_fields=["money_cents", "updated_at"])
            Transaction.objects.create(user=user, kind=Transaction.KIND_REWARD,
                                       amount_cents=amount, dev_tax_cents=0,
                                       note=note[:200])
        else:
            award_spinaz(user, amount, note=note)


class BattleEntry(models.Model):
    """A contestant on one side. 1v1 allows one per side; cypher allows many."""
    battle = models.ForeignKey(Battle, on_delete=models.CASCADE, related_name="entries")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="battle_entries")
    side = models.CharField(max_length=1, choices=SIDE_CHOICES)
    post = models.ForeignKey(Post, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="battle_entries")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("battle", "user")
        ordering = ["joined_at"]


class Bet(models.Model):
    """A wager. Cash is contestants-only and self-only; SpinAZ is everyone else.

    `amount` is cents for money and whole SpinAZ otherwise — one field, because
    two nullable amount columns would let a row mean nothing at all.
    """
    battle = models.ForeignKey(Battle, on_delete=models.CASCADE, related_name="bets")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="battle_bets")
    side = models.CharField(max_length=1, choices=SIDE_CHOICES)
    currency = models.CharField(max_length=8, choices=CURRENCY_CHOICES)
    amount = models.PositiveIntegerField()
    payout = models.PositiveIntegerField(default=0)
    settled = models.BooleanField(default=False)
    refunded = models.BooleanField(default=False)
    placed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["placed_at"]
        indexes = [models.Index(fields=["battle", "currency", "side"])]


class BattleVote(models.Model):
    battle = models.ForeignKey(Battle, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="battle_votes")
    side = models.CharField(max_length=1, choices=SIDE_CHOICES)
    voted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("battle", "user")


# --------------------------------------------------------------- eligibility --

def money_bet_error(battle, user, side):
    """Why this member may NOT stake cash — or None if they may.

    Three conditions, all from the spec: you must be in the battle, you must be
    backing your own side, and you must be verified 18+. The age check reads
    `verified_18plus`, never a self-reported birthday — the whole reason that
    column exists is that a date typed into a form is not verification.
    """
    entry = battle.entries.filter(user=user).first()
    if not entry:
        return ("Only contestants can bet money. Spectators back a side with "
                "SpinAZ.")
    if entry.side != side:
        return "You can only put money on yourself."
    if not wallet_for(user) or not _is_verified_adult(user):
        return ("Cash wagers need a verified 18+ account. Verify your age in "
                "Onboarding 🛂, or bet SpinAZ instead.")
    return None


def spinaz_bet_error(battle, user, side):
    """Contestants use cash; spectators use SpinAZ. Keeps the pools honest."""
    if battle.is_contestant(user):
        return ("You're in this battle — back yourself with money, not SpinAZ.")
    return None


def _is_verified_adult(user):
    from apps.economy.models import profile_for
    profile = profile_for(user)
    return bool(getattr(profile, "verified_18plus", False))


def take_stake(user, currency, amount):
    """Debit a stake from the wallet, or return an error string.

    `money_cents` and `spinaz` are both non-negative columns, so an unchecked
    subtraction doesn't just overdraw — it raises on save and leaves the bet
    half-created. Check first, subtract second, and never trust the caller to
    have checked.
    """
    from apps.economy.models import Transaction

    amount = int(amount or 0)
    if amount <= 0:
        return "Stake something above zero."

    w = wallet_for(user)
    if currency == CURRENCY_MONEY:
        if (w.money_cents or 0) < amount:
            return "That's more than your balance."
        w.money_cents -= amount
        w.save(update_fields=["money_cents", "updated_at"])
        Transaction.objects.create(user=user, kind=Transaction.KIND_SPEND,
                                   amount_cents=-amount, note="BattleZ stake")
    else:
        if (w.spinaz or 0) < amount:
            return "That's more SpinAZ than you have."
        w.spinaz -= amount
        w.save(update_fields=["spinaz", "updated_at"])
    return None
