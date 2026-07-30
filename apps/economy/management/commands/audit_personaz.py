"""Audit PersonaZ: the catalog's own consistency, then the stored member data.

    python manage.py audit_personaz              # report only
    python manage.py audit_personaz --fix        # also normalise stored profiles
    python manage.py audit_personaz --catalog    # catalog checks only, no DB

Two halves, because there are two ways this breaks:

1. **The catalog** — every persona has to follow the paradigm (two or more
   categories, each opening with an "Any …" wildcard, labels carrying an emoji,
   no duplicate or untidy keys). The v2.2 frontend had none of these checks and
   drifted badly; the tests in test_personaz.py enforce them on every commit,
   and this prints the same findings for a human.

2. **What members actually saved** — persona keys the catalog doesn't know,
   skills stored as labels, and skill dates in the picker's `M/D/YYYY` form under
   a `startDate` key the backend never read. `--fix` rewrites those in place.

``--fix`` is non-destructive: unrecognised personas and skills are kept and
reported, never deleted.
"""
from django.core.management.base import BaseCommand

from apps.economy.models import Profile
from apps.economy.personaz import (PERSONAZ, is_any_skill, normalize_personas,
                                   normalize_persona_key, normalize_start,
                                   skill_key_for, skills_for)


class Command(BaseCommand):
    help = "Audit the PersonaZ catalog and every member's stored personas/skills."

    def add_arguments(self, parser):
        parser.add_argument("--fix", action="store_true",
                           help="Normalise stored profiles (keys, skill names, dates).")
        parser.add_argument("--catalog", action="store_true",
                           help="Check the catalog only; touch no database rows.")

    # ------------------------------------------------------------ catalog
    def audit_catalog(self):
        problems = []
        self.stdout.write(self.style.MIGRATE_HEADING("\nCatalog"))
        for key, persona in PERSONAZ.items():
            cats = persona["categories"]
            flat = skills_for(key)
            counted = sum(len(s) for s in cats.values())

            if key != key.strip().lower() or " " in key:
                problems.append(f"{key}: persona key is not tidy (lowercase, no spaces)")
            if len(cats) < 2:
                problems.append(f"{key}: only {len(cats)} category — paradigm wants 2+")
            if counted != len(flat):
                problems.append(
                    f"{key}: {counted - len(flat)} skill key(s) repeat across categories"
                )

            for cat, skills in cats.items():
                if not skills:
                    problems.append(f"{key}/{cat}: empty category")
                    continue
                first = next(iter(skills))
                if not is_any_skill(first):
                    problems.append(f"{key}/{cat}: opens with '{first}', not an 'Any …' wildcard")
                for sk, label in skills.items():
                    if sk != sk.strip():
                        problems.append(f"{key}/{cat}/{sk!r}: key has padding whitespace")
                    if not label.strip():
                        problems.append(f"{key}/{cat}/{sk}: empty label")
                    elif label.strip()[-1].isalnum():
                        problems.append(f"{key}/{cat}/{sk}: label has no trailing emoji")

            self.stdout.write(
                f"  {persona['emoji']} {persona['name']:<14} "
                f"{len(cats)} categories, {len(flat):>3} skills   (since {persona['since']})"
            )

        self.stdout.write(
            f"\n  {len(PERSONAZ)} personas, "
            f"{sum(len(skills_for(k)) for k in PERSONAZ)} skills total"
        )
        return problems

    # ------------------------------------------------------------ stored data
    def audit_profiles(self, fix=False):
        problems = []
        self.stdout.write(self.style.MIGRATE_HEADING("\nStored member data"))

        totals = {
            "profiles": 0, "with_personas": 0, "personas": 0,
            "unknown_persona": 0, "aliased_key": 0,
            "skills": 0, "unknown_skill": 0, "label_as_key": 0,
            "slash_dates": 0, "undated": 0, "fixed": 0,
        }
        unknown_personas, unknown_skills = {}, {}

        for p in Profile.objects.exclude(personas=[]).iterator():
            totals["profiles"] += 1
            if not isinstance(p.personas, list) or not p.personas:
                continue
            totals["with_personas"] += 1

            for item in p.personas:
                totals["personas"] += 1
                raw_key = item.get("key") or item.get("name") if isinstance(item, dict) else item
                canonical = normalize_persona_key(raw_key)
                if not canonical:
                    totals["unknown_persona"] += 1
                    unknown_personas[str(raw_key)] = unknown_personas.get(str(raw_key), 0) + 1
                    continue
                if str(raw_key) != canonical:
                    totals["aliased_key"] += 1

                skills = (item.get("skills") or []) if isinstance(item, dict) else []
                for s in skills:
                    totals["skills"] += 1
                    name = (s.get("name") or s.get("key")) if isinstance(s, dict) else s
                    raw_start = (
                        s.get("start") or s.get("startDate") or s.get("start_date")
                        if isinstance(s, dict) else None
                    )
                    sk = skill_key_for(canonical, name)
                    if not sk:
                        totals["unknown_skill"] += 1
                        label = f"{canonical}/{name}"
                        unknown_skills[label] = unknown_skills.get(label, 0) + 1
                    elif str(name) != sk:
                        totals["label_as_key"] += 1
                    if not raw_start:
                        totals["undated"] += 1
                    elif "/" in str(raw_start):
                        totals["slash_dates"] += 1
                        if not normalize_start(raw_start):
                            problems.append(f"{p.user_id}: unparseable skill date {raw_start!r}")

            if fix:
                cleaned = normalize_personas(p.personas)
                if cleaned != p.personas:
                    p.personas = cleaned
                    p.save(update_fields=["personas", "updated_at"])
                    totals["fixed"] += 1

        for label, count in totals.items():
            self.stdout.write(f"  {label:<16} {count}")
        for title, found in (("Unknown personas", unknown_personas),
                             ("Unknown skills", unknown_skills)):
            if found:
                self.stdout.write(self.style.WARNING(f"\n  {title} (kept, not deleted):"))
                for name, count in sorted(found.items(), key=lambda kv: -kv[1])[:20]:
                    self.stdout.write(f"    {count:>4}x  {name}")
        return problems

    # ------------------------------------------------------------ entry point
    def handle(self, *args, **options):
        problems = self.audit_catalog()
        if not options["catalog"]:
            problems += self.audit_profiles(fix=options["fix"])

        if problems:
            self.stdout.write(self.style.ERROR(f"\n{len(problems)} problem(s):"))
            for line in problems:
                self.stdout.write(self.style.ERROR(f"  - {line}"))
        else:
            self.stdout.write(self.style.SUCCESS("\nNo problems found."))
        if options["fix"]:
            self.stdout.write("\nRan with --fix: stored personas normalised in place.")
