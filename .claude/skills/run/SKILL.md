---
name: run
description: Run the Music ConnectZ API locally, seed it, and hit its endpoints — or launch the whole stack with the frontend to drive it in a browser. Use when asked to run, start or exercise the backend, or to confirm an endpoint works outside the test suite.
---

# Running the Music ConnectZ API

## First: is a screen involved?

If you are checking anything a member SEES, drive the real app instead — the
frontend repo carries the skill that brings both halves up in one command,
seeded, same-origin, with a browser driver:

```bash
cd ../-music-connectz-frontend- && .claude/skills/run/up.sh
```

That skill also lists the traps neither repo announces (the empty
`VITE_API_BASE` that silently points at production, the tab slugs that drop
their trailing z, the persona-skill keys that make prices come out zero). Read
it before running the frontend by hand.

## The API on its own

```bash
python -c 'import _cffi_backend' || pip install cffi   # see below
python manage.py migrate
python manage.py runserver 8000 --noreload &
python manage.py shell < ../-music-connectz-frontend-/.claude/skills/run/seed.py
```

Then get a token and use it — the login field is **`identifier`**, not
`username`, and it takes a username, an email or a phone:

```bash
TOKEN=$(curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"identifier":"corey","password":"pw12345!"}' \
  http://localhost:8000/api/auth/login/ \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access"])')

curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/economy/venuez/
```

**Login answers 500 on a bare container** until `cffi` is installed — the
password hasher needs `_cffi_backend` and the image has not got it. Nothing in
the test suite catches this, because tests use `force_login` and never hash a
password. It reads as broken auth rather than a missing wheel.

**A 500 from the dev server tells you nothing by default.** `DEBUG` is off, so
the response is a bare "A server error occurred" and *no traceback reaches the
log*. Re-run the server with `DEBUG=1` on a spare port to see the real
exception:

```bash
DEBUG=1 python manage.py runserver 8002 --noreload
```

## Tests

```bash
python manage.py test apps.economy.test_venuez      # one module, ~1 min
python manage.py test apps                          # everything, ~28 min
```

Two things to know before you read a result:

- **`main` is not green**, and has not been for a while. Judge a branch by
  whether it adds failures to `main`'s baseline, not by `OK`. To get that
  baseline without a second 28-minute wait, run both at once — `git worktree
  add --detach <tmp> origin/main` and run the suite in each.
- **SQLite locally, Postgres in production**, so a column-width bug is
  invisible here. Anything touching field widths wants
  `DATABASE_URL=postgres://... python manage.py test`. See CLAUDE.md.
