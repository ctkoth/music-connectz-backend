# PersonaZ skills audit — v2.2/2.3 build

Audit of the persona/skill system as it exists in `musicconnectz_code_2.2.docx`
(the frontend build, titled *Music ConnectZ vA2.3*), and what changed in the
backend as a result.

**Headline: in the audited build, the skills feature could not run at all.** Two
entries are JavaScript syntax errors, and a syntax error anywhere in a `<script>`
block stops the *whole* block from parsing. Nothing in the app initialises — not
the skill picker, not personas, not the tabs. Everything below is downstream of
that.

Verdict per requirement:

| Requirement | Status |
|---|---|
| Audit 2.2 skills | ✅ 12 findings below — **11 closed**, 1 left open by instruction (#6) |
| Existing personas keep these exact skills | ✅ all 5 preserved verbatim, 2 corrupted entries repaired |
| New personas get skills in the same paradigm | ✅ Ghostwriter, Manager, Developer built |
| Developer gets the top 20 languages | ✅ exactly 20, plus the "Any" wildcard |
| Re-audit after adding | ✅ automated — `manage.py audit_personaz`, 46 tests |

---

## Findings

### 🔴 1. `instrumentDatabase['mix-engineer']` is a syntax error

```js
'Reason': 'Reason 🎛️',Reaper:'Reaper🪦': 'Azrael☠️','Studio One': 'Studio One1⃣ 🎛️'
```

`Reaper:'Reaper🪦': 'Azrael☠️'` has two colons in one entry — invalid object
literal. `SyntaxError` at parse time, and the entire script dies with it.

**Fixed:** `"Reaper": "Reaper 🔧"`, and the `Studio One1⃣` typo corrected, both
matching the intact producer copy of the same list.

### 🔴 2. `personaNames` is a syntax error

```js
    'videographer': '🎬 Videographer'
'Ghostwriter':'👻Ghostwriter '
'Manager ':'🕴🏼Manager'
'Developer ':'👾Developer'
  };
```

Three missing commas. Same consequence as #1 — the script never parses.

**Fixed:** the catalog is Python data now, with tests that reject padded keys, so
this class of error can't recur silently.

### 🔴 3. The Mix Engineer button contains a raw line break

```js
<button onclick="openSkillModal('E
ngineer','🎛️Mix Engineer')">🎛️ aMix Engineer</button>
```

A newline inside a string literal — a third syntax error. (The label also reads
"aMix Engineer".)

**Fixed:** `normalize_persona_key()` resolves separator-corrupted keys, so even
`"E\nngineer"` maps to `mix-engineer`.

### 🟠 4. Four of five persona buttons pass keys the database doesn't have

Even with the syntax fixed, `renderSkillModal` does
`Object.entries(instrumentDatabase[personaKey])` — an undefined lookup throws and
the picker renders nothing.

| Button sends | Database has | Result |
|---|---|---|
| `'Independent  artist'` (double space) | `'artist'` | ❌ empty picker |
| `'producer'` | `'Beat-producer'` | ❌ empty picker |
| `'Engineer'` | `'mix-engineer'` | ❌ empty picker |
| `'Designer'` | `'designer'` | ❌ empty picker |
| `'videographer'` | `'videographer'` | ✅ the only one that worked |

**Fixed:** one canonical key per persona plus an alias table covering every
spelling that ever shipped. Nobody loses a persona they already picked.

### 🟠 5. Three personas are named with no skills defined

`Ghostwriter`, `Manager`, and `Developer` appear in `personaNames` but have no
`instrumentDatabase` entry at all — the picker opens empty for each.

**Fixed:** all three built in the paradigm (below).

### 🟡 6. `PreSonus Studio One` and `Studio One` are the same DAW

Listed twice in both DAW categories. **Kept** — both shipped, and members may
have picked either, so removing one would orphan real data. To dedupe later,
delete the `"PreSonus Studio One"` line in `apps/economy/personaz.py` and add
`"PreSonus Studio One": "Studio One"` to a skill-alias map.

### 🟡 7. The DAW list is duplicated by hand

`Beat-producer` and `mix-engineer` each carry their own copy of an 18-entry list.
That's exactly how one of them got corrupted (#1) while the other stayed clean.

**Fixed:** one `_MUSIC_DAWS` constant, referenced by both. A test asserts they
stay identical.

### 🔴 8. Skill start dates were silently discarded — every member's experience read `None`

The picker writes:

```js
persona.skills.push({name: skillName, startDate: `${mo}/${day}/${yr}`})   // "7/4/2020"
```

The backend read:

```python
start = s.get("start")                       # different key
y, m, d = str(start).split("-")              # different format
```

Wrong field name **and** wrong format. `_clean_persona` dropped the date on
write, and `profile_max_experience` couldn't parse it on read — so the
years-of-experience metric answered `None` for everybody regardless of how long
they'd been playing. This is the most damaging *functional* bug in the audit,
because unlike #1–#3 it fails quietly.

**Fixed:** `normalize_start()` accepts `M/D/YYYY` and ISO, and `start`,
`startDate`, and `start_date` are all read on write and on read. Historical
slash dates already in the database now count.

### 🟡 9. Skills are stored as display labels, not keys

`appState.selectedSkillsInModal.add(skillName)` stores `"Acoustic Guitar 🎸"` —
the label, emoji included. Nothing can match that back to a catalog entry, so
skills can't be searched, filtered, or compared across members.

**Fixed:** `skill_key_for()` resolves a key *or* a label, and normalization
records both (`{key, name, start}`).

### 🟡 10. No skill validation anywhere

The backend accepted any string as a skill for any persona. A "Mixing" skill
could be stored under `designer` and nothing objected.

**Fixed:** normalization marks off-catalog entries `catalog: false` rather than
deleting them, and `audit_personaz` reports them. Deliberately non-destructive —
the platform has personas the picker doesn't carry (MimeZ, DirectZ), and a
catalog is not a licence to throw away a member's data.

### 🟡 11. The wildcard convention was undocumented

`renderSkillModal` decides a skill is a wildcard with
`skillKey.toLowerCase().includes('any')` — so any skill with "any" anywhere in
its name would be styled as a wildcard and behave differently.

**Fixed:** wildcards are first-in-category by contract, flagged explicitly as
`"any": true` in the API, and tested (first entry is a wildcard; no others are).

### 🟢 12. Gaps in the artist instrument list — **now closed**

No wind, brass, or woodwind family — a saxophonist, trumpeter, or flautist could
not register their instrument at all. Percussion was also thin (snare, bass,
bongo, cymbals; no full kit, no hand percussion).

**Fixed by ADDING, never editing.** Three new families and eleven new percussion
entries; every 2.2 key and label is untouched, and the tests now assert that as a
subset check against a transcription of the 2.2 data rather than a count that an
addition would break.

- **Wind & Woodwind** (15) — four saxophones, flute, piccolo, clarinet, bass
  clarinet, oboe, bassoon, recorder, harmonica, bagpipes, pan flute
- **Brass Instruments** (10) — trumpet, cornet, trombone, bass trombone, French
  horn, tuba, euphonium, flugelhorn, sousaphone
- **Electronic & DJ** (11) — DJ decks, turntablism, beatboxing, drum machine,
  MPC/sampler, MIDI controller, launchpad, modular synth, vocoder/talkbox,
  theremin. Producing live is performing; 2.2 forced a DJ to claim the producer
  persona for what is a stage skill.
- **Percussion** grew to 16 — full drum kit, hi-hat, congas, djembe, timbales,
  cajón, tambourine, shaker, marimba, steel drum, electronic drum pad

Artist went from 5 categories / 50 skills to **8 categories / 97 skills**. Catalog
total: **271 skills**.

---

## The paradigm

Every persona, old and new, now follows the shape the 2.2 database was reaching
for:

```
persona key -> categories -> {skill key: "Display Label + emoji"}
```

- **2+ categories**, conventionally a *tools* category (what you work in) plus a
  *craft* category (what you can do). `artist` splits by instrument family
  instead, which is the same idea one level finer.
- **Every category opens with an "Any …" wildcard**, so a member can claim a
  category without enumerating it.
- **Every label ends in an emoji.** The key stays stable; the label is what
  members see and what gets stored.

All three rules are enforced by tests, for all 8 personas.

## What each persona carries now

| Persona | Since | Categories | Skills |
|---|---|---|---|
| 🎤 Artist | 2.2 | String · Keyboard · Percussion · **Wind** · **Brass** · **Electronic/DJ** · Rapping · Singing | 97 |
| 🎚️ Beat Producer | 2.2 | Music DAWs · Production Techniques | 24 |
| 🎛️ Mix Engineer | 2.2 | Music DAWs · Engineering Skills | 24 |
| 🎨 Designer | 2.2 | Design Software · Design Skills | 17 |
| 🎬 Videographer | 2.2 | Video Software · Video Skills | 16 |
| 👻 Ghostwriter | **new** | Writing Tools · Writing Skills | 23 |
| 🕴️ Manager | **new** | Management Tools · Management Skills | 25 |
| 👾 Developer | **new** | Programming Languages · Developer Tools · Development Skills | 45 |

**8 personas, 271 skills.**

### Developer — the top 20 languages

Twenty exactly, plus `Any Language`. Ranked by professional use (TIOBE / Stack
Overflow consensus), and deliberately capped so the picker stays a picker:

Python · JavaScript · TypeScript · Java · C · C++ · C# · SQL · Go · Rust · PHP ·
Swift · Kotlin · Ruby · R · Dart · Scala · MATLAB · Perl · Lua

Plus 12 developer tools (VS Code, Git & GitHub, Docker, Kubernetes, Xcode,
Android Studio, IntelliJ, Vim/Neovim, Jupyter, Postman, Terminal & Shell) and 12
development skills including **Audio Programming** and **Game Development**,
which are the two most likely to matter to a developer on a music platform.

A tested constraint worth knowing about: the language list has to cover this
platform's own stack — Python/Django backend, JavaScript frontend, Kotlin
Android. A developer persona that can't describe the app it lives in is the wrong
list.

---

## What shipped in the backend

| File | Purpose |
|---|---|
| `apps/economy/personaz.py` | The catalog + normalization. One source of truth. |
| `apps/economy/personaz_views.py` | `GET /api/economy/personaz/` and `/personaz/<key>/` |
| `apps/economy/management/commands/audit_personaz.py` | Runnable audit, `--fix` to normalize stored data |
| `apps/economy/test_personaz.py` | 46 tests — the audit, automated |
| `apps/accounts/views.py` | `_clean_persona` now keeps the picker's dates (#8) |
| `apps/economy/social.py` | `_skill_years` / `profile_max_experience` parse both formats (#8) |

### Re-auditing

```bash
python manage.py audit_personaz             # catalog + stored data report
python manage.py audit_personaz --catalog   # catalog only, no database
python manage.py audit_personaz --fix       # normalize stored profiles in place
python manage.py test apps.economy.test_personaz
```

The command reports unknown persona keys and unknown skills with counts, so you
can see what real members actually saved before deciding whether a gap (like #12)
is worth filling.

---

## For the frontend

**Delete `instrumentDatabase` and read the API instead.** That object is the root
cause of findings #1, #2, #4, #6, and #7 — a hand-maintained copy of data with
nothing checking it. `GET /api/economy/personaz/` returns the same structure,
public and uncached-per-user:

```json
{
  "personas": [
    {"key": "developer", "name": "Developer", "emoji": "👾",
     "label": "👾 Developer", "skill_count": 45,
     "categories": [
       {"name": "Programming Languages",
        "skills": [{"key": "Any Language", "label": "Any Language 👾", "any": true},
                   {"key": "Python", "label": "Python 🐍", "any": false}]}
     ]}
  ],
  "aliases": {"beat-producer": "producer", "...": "..."},
  "rules": {"any_prefix": "Any", "start_date_format": "YYYY-MM-DD",
            "start_date_required": true}
}
```

Three changes on your side:

1. **Use `persona.key` from the API** as the value you pass to `openSkillModal`.
   That alone fixes finding #4 permanently.
2. **Send `start` as `YYYY-MM-DD`** (finding #8). `startDate` in `M/D/YYYY` is
   still accepted and converted, so existing clients don't break — but ISO is the
   documented form.
3. **Store `skill.key` alongside the label** (finding #9) so skills stay
   matchable.
