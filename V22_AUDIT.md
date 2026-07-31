# 2.2 skills and genres — full audit

Source: `musicconnectz_code_2.2.docx`, parsed rather than read. Every string
below was extracted from the file; none is from memory.

**Result: 131 skills and 15 genres, all resolving in every stored form.**
Three did not before this audit. One bug in the backend, several in 2.2 itself.

| | Entries | Forms checked | Unresolved before | Unresolved after |
|---|---|---|---|---|
| Skills | 131 | 262 | **3** | 0 |
| Genres | 15 | 90 | 0 | 0 |

"Forms" means every way a client could hand the value back: the key, the
decorated label, case variants, and the label with the emoji touching the name.

---

## 1. The backend bug: an emoji touching the name lost the skill

`skill_key_for` matched a stored label only when the emoji was separated by a
space. 2.2 is not consistent about that space.

```
"Reaper 🔧"   ->  Reaper      ✅
"Reaper🪦"    ->  None        ❌  same skill, no space
"Trap🏚️"      ->  None        ❌
"🎸Acoustic Guitar" -> None   ❌  2.2's persona buttons are all this shape
```

A skill survived or vanished depending on whether whoever typed that catalog
line happened to hit the space bar. `normalize_persona_key` already retried with
the decoration stripped — `skill_key_for` never did, so the fix that landed for
personas never reached the skills underneath them.

Fixed by applying the same `_demoji` retry. Junk that is only decoration still
resolves to nothing rather than becoming a false match.

### 1a. Keycap sequences

`1⃣` is the digit `1` plus a combining mark (U+20E3). Stripping only the mark
left the digit welded to the name, so 2.2's `'Studio One1⃣ 🎛️'` became
`"Studio One1"` and matched nothing.

The whole sequence is now stripped, matched narrowly — dropping every digit
would break real names like `808` or `Sound Forge 2`.

---

## 2. Bugs in 2.2 itself

These are in the file. They are not things the backend can be blamed for, but
they explain what a real client sends.

### 2a. Two JavaScript syntax errors

```js
// mix-engineer -> Music DAWs
'Reason': 'Reason 🎛️',Reaper:'Reaper🪦': 'Azrael☠️','Studio One': 'Studio One1⃣ 🎛️',
```

`Reaper:'Reaper🪦': 'Azrael☠️'` is not valid — a key, a value, then a second
colon. And the Mix Engineer button:

```js
onclick="openSkillModal('E
ngineer','🎛️Mix Engineer')"
```

A literal newline inside a string literal. Both throw at parse time, which takes
`instrumentDatabase` down with them — so on a browser that reaches either line,
**no skills load at all.**

### 2b. Four of the five personas don't match 2.2's own database

The buttons call `openSkillModal` with one key; `instrumentDatabase` is keyed
with another.

| Button sends | Database holds | Match |
|---|---|---|
| `'Independent  artist'` (two spaces) | `'artist'` | ✗ |
| `'producer'` | `'Beat-producer'` | ✗ |
| `'E\nngineer'` | `'mix-engineer'` | ✗ |
| `'Designer'` | `'designer'` | ✗ (case) |
| `'videographer'` | `'videographer'` | ✓ |

Only Videographer lines up. The backend resolves all five correctly — it is
more forgiving than the file that produced the data.

### 2c. Cosmetic

- `'🎛️ aMix Engineer'` — stray `a` in the display label.
- `'Independent  artist'` — double space, inside the string *and* in the
  collab filter option.

---

## 3. Skills, by persona

All 131 verified present, unchanged, and resolvable from both the key and the
label. Counts are from parsing, not memory.

| Persona | Categories | Skills |
|---|---|---|
| artist | String, Keyboard, Percussion, Rapping, Singing | 50 |
| producer | Music DAWs, Production Techniques | 24 |
| mix-engineer | Music DAWs, Engineering Skills | 24 |
| designer | Design Software, Design Skills | 17 |
| videographer | Video Software, Video Skills | 16 |
| | | **131** |

Every category still opens with its `Any …` wildcard, which is what makes a
category selectable as a whole.

### Reaper and Azrael

2.2's broken line reached for one or the other and got neither. Both are
carried, as separate skills:

- **Reaper 🔧** — the real product.
- **Azrael ☠️** — the Music ConnectZ DAW that imitates it.

Being skilled in one is not being skilled in the other, so they are not
aliases.

---

## 4. Genres

All 15, from `openGenreModal()`:

> Trap · Drill · Cloud Rap · Boom Bap · House · Techno · Pop · Hip Hop · R&B ·
> Jazz · Soul · Indie · Electronic · Ambient · Lo-Fi

Every one resolves from the plain string, the decorated label, either emoji
position, both case extremes, and the hand-typed spellings members actually use
(`rnb`, `r and b`, `lofi`, `lo fi`). **No genre failures, before or after.**

Four are also Rapping skills — Trap, Drill, Cloud Rap, Boom Bap. That overlap
is intentional and flagged: a genre and a skill of the same name are different
claims. "I make Trap" is not "I can rap Trap."

---

## 5. What's pinned

`apps/economy/test_v22_skills.py` — 38 tests.

- Every one of the 131 skills resolves from its key.
- Every one resolves from **five** label forms each — as served, emoji welded
  on, uppercased, and with stray whitespace. Over 500 assertions.
- The count is asserted at 131, so a skill going missing fails the suite.
- Decoration alone (`🎸`, `1⃣`, whitespace) still resolves to nothing.
- Both 2.2 corruptions are asserted *absent* from the catalog.
- All 15 genres, in every form.

If any string a 2.2 client sends stops resolving, the suite fails and names it.
