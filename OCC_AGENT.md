# OCC as a coding agent

OCC could explain code. Now it can change it.

`POST /api/economy/ai/occ/` asks the model once and returns text — that can't
edit a file, because one turn can't look, decide, act, and check. The agent runs
the loop instead:

```
"add rate limiting to the login endpoint"

  search("def login")          → api/auth.py:1
  read_file("api/auth.py")     → sees it
  edit_file(...)               → changes it
  read_file("api/auth.py")     → confirms the change landed
  "Rate limited login to 5/min. One file changed."
```

Five model calls, four tool calls, one request from the client.

---

## What it can and can't do

Read this before deciding it replaces Claude Code, because it doesn't — not yet,
and the gap is a deliberate one.

| Claude Code does | OCC does | Notes |
|---|---|---|
| Read files | ✅ `read_file` | numbered lines, paginated |
| Write files | ✅ `write_file` | refuses to clobber an unread file |
| Exact-string edit | ✅ `edit_file` | unique-match required, like Claude Code's Edit |
| Grep / search | ✅ `search` | regex + glob filter |
| Glob / list | ✅ `list_files` | |
| Move & delete | ✅ `rename_file`, `delete_file` | |
| Multi-step agentic loop | ✅ | 8–64 steps by tier |
| **Run commands / tests** | ❌ | see below |
| **Git** | ❌ | no repo, no commits |
| **Fetch the web / MCP** | ❌ | |
| **Sub-agents** | ❌ | |
| Real repo on disk | ❌ | a workspace of up to 200 files |

### Why there's no code execution

Running member-supplied code on the API host is remote code execution. The fix
isn't a cleverer allowlist — an allowlist around a shell is a puzzle attackers
enjoy solving. It's per-run isolation: a throwaway container per execution, no
network, no credentials, a CPU and memory cap, and a hard timeout. That's
infrastructure this backend doesn't have on Render today.

**So OCC is told, in its system prompt, that it cannot run anything and must
never claim it did.** An agent that says "I ran the tests and they pass" when it
has no test runner is worse than one that says "run `pytest tests/` and tell me
what breaks."

To close the gap, in the order I'd do it:

1. A separate worker service with a container-per-run sandbox
   ([gVisor](https://gvisor.dev/), [Firecracker](https://firecracker-microvm.github.io/),
   or a managed option like [E2B](https://e2b.dev/) / Modal).
2. A `run_command` tool that posts the workspace to that worker and returns
   stdout/stderr/exit code — the agent contract is already shaped for it.
3. Git on the workspace, so runs become commits and a bad run is revertible.

Steps 2 and 3 are small once 1 exists. Step 1 is the whole job.

### Where the workspace lives

Files are rows in `ProjectFile`, never paths on disk. That's the containment
story: OCC can't read `settings.py`, walk `/etc`, or reach another member's
project, because there is no path out of the workspace — the filesystem was
never in scope. Traversal isn't blocked by a filter that might be outwitted; the
thing traversal reaches for isn't there.

Paths are still validated (`normalize_path`), because a path is also a lookup key
and a display string. That check is segment-wise, not string-wise — `lstrip("./")`
strips a *character set*, so it turns `../secrets.py` into `secrets.py`, a
traversal that then passes every later check because the `..` is gone. A test
covers exactly that string.

---

## API

```
GET    POST   /api/economy/occ/projects/                list / create
GET    DELETE /api/economy/occ/projects/<id>/           detail with files / delete
GET    POST   /api/economy/occ/projects/<id>/files/     read / write a file by hand
DELETE        /api/economy/occ/projects/<id>/files/?path=…
POST          /api/economy/occ/projects/<id>/agent/     run the loop
GET           /api/economy/occ/projects/<id>/runs/      what it actually did
```

A project id you don't own is a **404, not a 403**, so ids can't be probed.

### Running the agent

```http
POST /api/economy/occ/projects/7/agent/
{"prompt": "add a /health endpoint that returns uptime",
 "dry_run": false, "max_steps": 12,
 "history": [{"role": "user", "text": "…"}, {"role": "occ", "text": "…"}]}
```

```json
{
  "project": "beatmaker",
  "steps": 4,
  "changed": ["api/health.py", "api/urls.py"],
  "text": "🔥 Added /health…",
  "tool_calls": [
    {"step": 1, "name": "list_files", "input": {}, "ok": true, "result": "3 file(s):…"},
    {"step": 2, "name": "write_file",
     "input": {"path": "api/health.py", "content": "<412 chars>"},
     "ok": true, "result": "Created api/health.py (412 chars)."}
  ],
  "stopped": "done",
  "cost_cents": 4,
  "money": 12.34
}
```

`stopped` is one of:

| Value | Means |
|---|---|
| `done` | the model finished and stopped asking for tools |
| `max_steps` | hit the step cap — say "keep going" to continue |
| `out_of_balance` | ran out mid-run; edits already made are kept |
| `error` | upstream failure; edits already made are kept |

**A run that changed files returns 200 even when it ended badly.** Those edits are
already in the workspace, and a non-200 invites a client to throw the result away.

### `dry_run`

Every write tool is refused and the model is told so up front, so it investigates
and describes the plan instead of pretending to act. The right first move on a
project that already has work in it.

---

## Limits and billing

Billed per model call at Corey's rate — the same pass-through pricing as OCC
chat, no markup. A four-step run costs four cents.

| Tier | Steps per run |
|---|---|
| Free | 8 |
| Premium | 16 |
| StatZ | 32 |
| Owner | 64 |

Per project: 200 files, 200,000 chars per file, 2,000,000 chars total. 25
projects per member. `max_steps` in the request can lower the cap but never raise
it past the tier ceiling.

The loop stops the moment the balance can't cover the next step, reports
`out_of_balance`, and keeps what it already changed. It never runs a step it
can't bill.

---

## Why the tool semantics are copied from Claude Code

They're the ones that make an agent reliable rather than merely capable:

- **`edit_file` requires a unique exact match.** Fuzzy editing is how agents
  silently corrupt files. If the string appears twice, the tool refuses and tells
  the model to include more context.
- **`write_file` refuses a file not read this run.** An agent overwriting what it
  never looked at is guessing.
- **`read_file` returns numbered lines**, so line 42 means line 42.
- **Tools return errors as text, not exceptions.** A failed tool is information
  the model can act on — the loop feeds it back with `is_error` and lets it
  recover.

Every run is recorded in `AgentRun` with its tool calls and changed paths. An
agent that edits files without a record isn't auditable: a member has to be able
to see what OCC *did*, not just what it said.
