# ⚠️ DRAFT — branch only, do NOT merge to main as-is

Written before reading `apps/economy/gates.py`, `SkillRating`/`ratez.skills_of` and the persona skill
periods. `main` auto-deploys and migrates unattended, and this app overlaps what already exists:

| This draft | Already in the repo | Do instead |
|---|---|---|
| `WorkRating`, `WorkSkillTag` (own ratings) | `SkillRating` (rated work -> skill), `ratez.skills_of`, `skill_rating_median` | Read `SkillRating`; delete the two tables. Two skill medians that disagree is the substance rule's failure. |
| `MemberFacet` (birth_date, lat/lon, attractiveness) | `Profile.birthday` (`profile_age`), `Profile.lat/lng/share_location`, `attractiveness_shown_medians` | Delete it. It bypasses `share_location` and the member's own attractiveness switch (a privacy regression). |
| `SkillGate` + `evaluate_gate` | `gates.py` (`clean_gates`, `failing_gate`, `MemberMetrics`) already stored on posts, deals, venues, lessons, ChallengeZ filters | Add ONE new key to `gates.py` (e.g. `skills`: list of `{skill|family, rating:[lo,hi], years:[lo,hi]}` + any/all) so every surface inherits it. |
| `UserSkill.learned_at` | `Profile.personas[].skills[]` dated stints (`social._skill_years`, `skill_activity`) | Use the dated stints for experience. Label it "declared" in the UI. |
| `distribute()` rating split | collab contribution ratings already re-cut a split | Check `collab.py` before adding a second split. |

## What IS new here and worth keeping
- Per-skill and per-FAMILY requirements ("any Rapping, 5-20 yrs, rated 5-10") with free min/max on every bound.
- The gauge (lower of experience tier and rating tier) as a read-only display next to a skill.
- The add-a-skill CTA in the skill picker; type-ahead instead of a long list.
- The 22 tests in `tests.py` are a spec for the above; port them onto `gates.py`.

## House rules this draft does not yet follow (see CLAUDE.md)
- Cost/gain up front: the picker must show `−N ⚡` beside the control (post cost is currently only returned after).
- Experience from a typed date is a declaration, not a measurement; say so on screen.
- One writer per field.

---

