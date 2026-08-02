# TabZ — the tab and modal map

Your `=` / `+` notation, encoded as data:

```
=Name 🙂   a TAB    → gets its own URL
+Name 🙂   a MODAL  → lives in a tab, opens when its icon is tapped
```

**35 tabs, 45 modals**, served by `GET /api/tabz/`. The frontend renders
navigation from this instead of hardcoding it, so adding a tab here makes it
appear everywhere at once.

## URLs

The rule from your spec — "named after the tab, -Z at the end" — is a function,
not a column, so a renamed tab can't drift from its route:

| Tab | URL |
|---|---|
| BattleZ | `/battle` |
| CollabZ | `/collab` |
| SingZ | `/sing` |
| GameZ | `/game` |
| SettingZ | `/setting` |
| Trump Toupee | `/trumptoupee` |

Two get an explicit override because the literal rule reads badly: **RoyaltieZ →
`/royalties`** (not `/royaltie`) and **Social ConnectZ → `/social`** (not
`/socialconnect`).

## What the spec still owes

`GET /api/tabz/audit/` computes this — a hand-written list would rot the moment
a row changed.

**5 entries have no icon:**

| Where | Why |
|---|---|
| `Home` | Only the URL `/home` was given, no name line and no emoji |
| `CollabZ → OriginalZ` | **Revealed by your artwork.** It has no line in the written spec at all — no emoji, no description |
| `MessageZ → Inbox` | Listed as `+Inbox` with no emoji |
| `MessageZ → Outbox` | Listed as `+outbox` with no emoji |
| `SettingZ → Theme` | Listed as "theme" with no emoji |

**One structural note:** `FormulaWon 🚦` was written without a leading `+`,
unlike every other DawZ entry. Treated as a DawZ modal like its siblings.

## Icon artwork on hand

`brand/tabz/` holds the six PNGs you sent:

| File | For |
|---|---|
| `battlez-freestyle.png` | BattleZ → Freestyle 🆓 |
| `battlez-1v1.png` | BattleZ → 1v1 1️⃣ |
| `battlez-cypher.png` | BattleZ → Battle Cypher 🧑‍🤝‍🧑 |
| `collabz-originalz.png` | CollabZ → OriginalZ |
| `collabz-coverz.png` | CollabZ → CoverZ 🫴🏼 |
| `collabz-remixez.png` | CollabZ → RemixeZ 🔄 |

Note these are **artwork**, which is a separate thing from the **emoji**. A tab
row carries an emoji for inline rendering (tab bars, lists, text); the PNG is for
tiles and store listings. OriginalZ has artwork but still needs an emoji.

---

# BattleZ 🪖

`/battle` · `GET /api/battlez/catalog/`

Three formats, matching your icons: **Freestyle 🆓** (live, open entry), **1v1
1️⃣** (one artist a side, enforced), **Battle Cypher 🧑‍🤝‍🧑** (teams).

## The wagering rules, as specified

> Contestants verified 18+ can bet money on themselves; others can bet spinaz.

Implemented literally, and each half is a separate check:

- **Cash** requires all three: you're a contestant, you're backing *your own*
  side, and your account is **verified 18+**. The age check reads
  `verified_18plus`, never the self-reported birthday — that column exists
  precisely because a date typed into a form is not verification.
- **SpinAZ** is spectators only. A contestant backs themselves with money.

## Settlement

**Cash and SpinAZ settle as two independent pools and never cross.** A
spectator's play money can't fund somebody's cash winnings, and cash can't leak
into the SpinAZ economy.

The rake comes off the **losing** pool only, so **a winner never gets back less
than they staked**. Three cases refund instead of paying out:

- **A tie** refunds everything. Deciding who gets paid by coin flip isn't a call
  the platform gets to make.
- **An unopposed pool** refunds. If nobody took the other side there's nothing to
  win, and taking a rake on a market that never formed is a fee for showing up.
- **Cancellation** refunds.

Refunds credit the wallet directly rather than through `credit_funds` — that
function taxes a gross deposit arriving from a card, which is correct for
funding a wallet and wrong here. Routing settlements through it would tax the
money twice and make every refund smaller than the stake.

Contestants can't vote in their own battle. `settlement` is stored and returned
in full, because a wagering market that can't explain its own result is one
people stop trusting.

## ⚠️ Before this takes real money

Skill-based wagering where entrants stake on their own performance is legally
distinct from gambling in most US states — but "most" is not "all", and a few
(Arizona, Arkansas, Connecticut, Delaware, Louisiana, Montana, South Carolina,
South Dakota, Tennessee) restrict paid entry even for skill contests. Both app
stores also treat real-money contests as a licensed category needing extra
review.

The SpinAZ pool has none of these problems. **My recommendation: ship SpinAZ
first, keep the cash pool dark behind a flag until you've had this looked at by
someone who does gaming law.** The code is built so that's a config change, not
a rewrite.

## Endpoints

```
GET  /api/battlez/catalog/                     formats + the rules
GET  /api/battlez/battles/[?format=&status=]
POST /api/battlez/battles/                     {title, format, rules}
GET  /api/battlez/battles/<id>/
PATCH /api/battlez/battles/<id>/               {status: live|voting|settled|cancelled}
POST /api/battlez/battles/<id>/entries/        {side, post_id}
POST /api/battlez/battles/<id>/bets/           {side, currency, amount}
POST /api/battlez/battles/<id>/votes/          {side}
```

---

# CollabZ 🤝

`/collab` · `GET /api/collabz/catalog/`

Three kinds, matching your icons: **OriginalZ**, **CoverZ 🫴🏼**, **RemixeZ 🔄**.

CoverZ and RemixeZ are derivative by definition, so they need a source — either
a linked post on the platform, or a written credit for something that isn't. An
original needs neither, and demanding one would make the commonest case the
awkward one.

**Splits are reported, not enforced.** `split_warning` fires when they add to
anything other than 0% or 100% — 0 means "still negotiating", 100 means
"agreed", and everything between is the dangerous state that looks decided but
isn't. Refusing the save would make the tool useless exactly while it's being
used; it hard-fails at payout instead.

Money is **not** reimplemented here. `economy.CollabDeal` is already the escrow
that holds each payer's cash until release, and a project points at one. Two
escrows would eventually disagree about who got paid.

```
GET  /api/collabz/catalog/
GET  /api/collabz/projects/[?mine=1&kind=&status=]
POST /api/collabz/projects/           {title, kind, source_post_id|source_credit}
GET/PATCH/DELETE /api/collabz/projects/<id>/
GET/POST/DELETE  /api/collabz/projects/<id>/members/
```
