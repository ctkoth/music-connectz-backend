"""Who a post's earnings go to, and in what shares.

A post made by several members belongs to all of them, so its earnings are
split among them rather than paid to whoever pressed Post. The rule is the
one CollabZ already uses for the deal the post came out of, so a post and
its deal can never disagree about who did what:

  * from a CollabZ deal — by each contributor's rating on that deal, once
    RATING_SPLIT_MIN_RATERS people outside the deal have rated; until then by
    the deal's agreed worth
  * credited contributors, no deal — equal shares
  * nobody else credited — all to the author

Shares always sum to exactly the amount; the rounding remainder goes to the
largest share.
"""
from django.contrib.auth import get_user_model


def _weights(post):
    names = [c.get("username") for c in (post.contributors or [])
             if isinstance(c, dict) and c.get("username")]
    if post.author.username not in names:
        names.insert(0, post.author.username)
    if len(names) <= 1:
        return {post.author.username: 1.0}, "solo"

    deal = post.source_deal
    if deal is not None:
        from .collab import rating_split
        parts, snap = rating_split(deal)
        if snap.get("applied"):
            w = {p["username"]: float(p.get("receives_cents") or 0) for p in parts}
            how = "rating"
        else:
            w = {p.get("username"): float(p.get("worth_cents") or p.get("receives_cents") or 0)
                 for p in deal.participants}
            how = "worth"
        w = {u: v for u, v in w.items() if u in names and v > 0}
        if w:
            return w, how
    return {u: 1.0 for u in names}, "equal"


def post_shares(post, cents):
    """[(user, cents, basis)] summing to `cents`."""
    cents = int(cents or 0)
    weights, how = _weights(post)
    users = {u.username: u for u in get_user_model().objects.filter(username__in=list(weights))}
    weights = {u: w for u, w in weights.items() if u in users}
    if not weights or cents <= 0:
        return [(post.author, cents, "solo")]
    total = sum(weights.values())
    order = sorted(weights, key=lambda u: weights[u])
    out, handed = [], 0
    for i, u in enumerate(order):
        share = cents - handed if i == len(order) - 1 else int(cents * weights[u] / total)
        handed += share if i < len(order) - 1 else 0
        out.append((users[u], share, how))
    return out
