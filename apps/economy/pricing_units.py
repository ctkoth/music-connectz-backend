"""Every price a member sets, and what it is a price PER.

Corey: any variable should have the same freedom skill prices now have — the member says
whether a price is per hour or per work, and every screen that quotes it says which. This is
the list, and `test_pricing_units` is the enforcement: a model field that looks like a price or
a rate and is on neither list below fails the suite, so a new price cannot ship without
saying what its unit is and whether the member may choose it.

Three lists, because they are three different things:

PRICES     a price a member SETS. `units` is what they may choose between; `choosable` is True
           when the member actually gets the choice today, and `gap` says what is missing when it
           is False. A price that is only ever per item (a beat, a merch piece) is honestly a
           single-unit price — the unit is part of what it is — not a missing feature.
SNAPSHOTS  a record of what was PAID or agreed at the time (a purchase row, a call's locked
           rate). Copied from a PRICES entry, never set by a member, so no unit choice lives here.
GAPS       a price that SHOULD offer the choice and does not yet. Honest and visible, so the
           next person starts from the list rather than an audit.
"""

PRICES = {
    # The skill price: per hour (the default, never stored) or per work. Unit: `rate_unit`.
    "Profile.personas.skills.rate_cents": {
        "units": ("hour", "work"), "choosable": True, "unit_field": "rate_unit",
        "read_by": ["postz.skill_price_units", "venuez.quote_for", "callz.hourly_skills", "social.profile_skill_rate"],
    },
    "Post.price_cents": {"units": ("work",), "choosable": True,
                         "why": "What a finished piece is sold for; there is no hour in a sale."},
    "MerchItem.price_cents": {"units": ("item",), "choosable": True,
                              "why": "A physical item has one price per item."},
    "BeatZ.price_cents": {"units": ("work",), "choosable": True,
                          "why": "A beat is sold as a finished work."},
    "VenueEvent.spinaz_price": {"units": ("entry",), "choosable": True,
                                "why": "A flat entry; the same for every visitor and every number of hours."},
    # Time-sold-by-the-minute. A lesson priced per finished lesson, or per hour, is not yet possible.
    "CoachProfile.lesson_rate_cents_per_min": {
        "units": ("minute",), "choosable": False,
        "gap": "Only per minute. A coach cannot price a whole lesson, or an hour, as such; "
               "the booking maths multiplies minutes."},
}

SNAPSHOTS = {
    "PostSale.price_cents": "what the buyer paid, copied from Post.price_cents",
    "MerchPurchase.price_cents": "what the buyer paid, copied from MerchItem.price_cents",
    "BeatPurchase.price_cents": "what the buyer paid, copied from BeatZ.price_cents",
    "SpecZPurchase.price_spinaz": "what the buyer paid in 🍥",
    "Call.rate_cents_per_min": "the callee's rate, locked at ring from their hourly skills",
}

GAPS = {
    "CoachProfile.lesson_rate_cents_per_min": PRICES["CoachProfile.lesson_rate_cents_per_min"]["gap"],
}
