"""OCC's agentic loop — the difference between a chatbot and a coding agent.

`OccChatView` asks the model once and returns the text. That can explain code; it
can't *change* code, because one turn can't look at a file, decide, edit, and
check its work. This module runs the loop instead: call the model, execute the
tools it asked for, hand back the results, repeat until it says it's finished.

What this gives OCC that plain chat cannot:

    "add rate limiting to the login endpoint"
      -> search("def login")            find it
      -> read_file("api/auth.py")       look at it
      -> edit_file(...)                 change it
      -> read_file(...)                 verify the change landed
      -> "Done — here's what I changed and why."

Honest boundaries, because they matter more than the feature list. This is NOT
all of Claude Code, and the gap is deliberate:

* **No code execution.** No shell, no test runner, no package installs. Running
  member-supplied code on the API host would be a remote-code-execution hole, and
  the fix isn't a cleverer allowlist — it's per-run container isolation, which is
  infrastructure this backend doesn't have. OCC reasons about code and edits it;
  it cannot prove it runs. See OCC_AGENT.md for what closing that would take.
* **No git, no network, no MCP.** Same reason.
* **One workspace at a time**, capped in files and size.

Everything else — the tool loop, exact-string editing, read-before-write, search,
step limits, per-step billing, a full transcript of what it did — is here.
"""
import json
import logging

from .catalog import ai_cost
from .models import (TIER_DEBUG, TIER_FREE, TIER_PREMIUM, TIER_STATZ,
                     can_afford_ai, charge_ai_usage, membership_for, wallet_for)
from .occ_tools import (TOOL_SCHEMAS, WRITE_TOOLS, Workspace, run_tool,
                        take_snapshot)

log = logging.getLogger("apps.omviardz")

# How many model calls one run may make. An agent needs room to look, act and
# check; it does not need unbounded room, because a loop that never converges
# bills forever. Higher tiers get more rope.
MAX_STEPS = {TIER_FREE: 8, TIER_PREMIUM: 16, TIER_STATZ: 32, TIER_DEBUG: 64}
MAX_TOKENS = 4096
# Trim the transcript so a long run can't grow the prompt without bound.
MAX_HISTORY_BLOCKS = 60

STOP_DONE = "done"
STOP_MAX_STEPS = "max_steps"
STOP_BUDGET = "out_of_balance"
STOP_ERROR = "error"

AGENT_STYLE = (
    "YOU ARE OCC IN CODING-AGENT MODE. You have tools that read and change the files in this "
    "member's project. Use them; do not ask permission for ordinary edits, and do not paste a "
    "file's whole contents into chat when you can just edit it.\n\n"
    "HOW TO WORK:\n"
    "- Look before you leap: list_files or search first when you don't already know the layout. "
    "Never guess a path.\n"
    "- Prefer edit_file over write_file. write_file replaces everything and is for new files.\n"
    "- old_string must be copied byte for byte from what read_file showed you, indentation "
    "included, and must be unique — include surrounding lines if it isn't.\n"
    "- After a non-trivial edit, read the file back and check it says what you meant.\n"
    "- Finish the job. If the request needs four files changed, change four files; don't stop "
    "after one and describe the rest.\n"
    "- YOU CANNOT RUN CODE. There is no shell, no test runner, no installs. Never claim you ran "
    "or tested anything. If something needs verifying, say plainly what the member should run.\n\n"
    "WHEN YOU'RE DONE: a short summary — what you changed, in which files, and anything you "
    "deliberately didn't do. Skip the preamble; they can see the diff."
)


def max_steps_for(user):
    return MAX_STEPS.get(membership_for(user).tier, MAX_STEPS[TIER_FREE])


def _blocks(content):
    """Normalise the SDK's response blocks to plain dicts.

    Keeps the transcript JSON-serialisable — which is what lets it be stored on
    the run, replayed, and asserted against in tests without the SDK present.
    """
    out = []
    for block in content or []:
        # Read dicts and SDK objects separately rather than `getattr(...) or
        # block.get(...)`: a tool call with empty input ({} — every list_files
        # call) is falsy, so the `or` fell through to .get() on an object.
        if isinstance(block, dict):
            kind, text = block.get("type"), block.get("text", "")
            bid, name, params = block.get("id"), block.get("name"), block.get("input")
        else:
            kind, text = getattr(block, "type", None), getattr(block, "text", "")
            bid = getattr(block, "id", None)
            name = getattr(block, "name", None)
            params = getattr(block, "input", None)

        if kind == "text" and text:
            out.append({"type": "text", "text": text})
        elif kind == "tool_use":
            out.append({
                "type": "tool_use",
                "id": bid,
                "name": name,
                "input": params if isinstance(params, dict) else {},
            })
    return out


def _summarize_input(params):
    """A one-line, safe rendering of a tool's arguments for the transcript.

    File contents are summarised rather than stored twice — a run that writes
    three 40KB files shouldn't triple the size of its own audit record.
    """
    if not isinstance(params, dict):
        return {}
    out = {}
    for key, value in params.items():
        if isinstance(value, str) and len(value) > 120:
            out[key] = f"<{len(value)} chars>"
        else:
            out[key] = value
    return out


def build_system(project, extra=""):
    """Corey's voice + agent mode + what's in the project right now."""
    try:
        from .occ import COREY_VOICE, COURSES
    except Exception:  # pragma: no cover
        COREY_VOICE, COURSES = "You are OCC.", ""

    files = list(project.files.order_by("path").only("path", "content")[:200])
    if files:
        listing = "\n".join(f"- {f.path} ({len(f.content)} chars)" for f in files)
    else:
        listing = "- (empty project — nothing created yet)"

    parts = [
        COREY_VOICE,
        AGENT_STYLE,
        f"PROJECT: {project.name}\n"
        + (f"WHAT IT IS: {project.description}\n" if project.description else "")
        + f"FILES RIGHT NOW:\n{listing}",
        COURSES,
    ]
    if extra:
        parts.append(extra)
    return "\n\n".join(p for p in parts if p)


def run_agent(user, project, prompt, history=None, max_steps=None, dry_run=False):
    """Run the loop until the model is done, the steps run out, or money does.

    Returns a dict describing the whole run — the text reply, every tool call and
    its result, which files changed, and what it cost. Never raises for an
    upstream failure; a run that dies mid-way still reports the work it managed
    to land, because those edits are already in the workspace.
    """
    from .models import AgentRun

    cap = int(max_steps or max_steps_for(user))
    cap = max(1, min(cap, MAX_STEPS[TIER_DEBUG]))
    per_step = ai_cost("corey-gpt")
    workspace = Workspace(project)

    result = {
        "project": project.name,
        "steps": 0,
        "tool_calls": [],
        "changed": [],
        "text": "",
        "stopped": STOP_DONE,
        "cost_cents": 0,
        "max_steps": cap,
    }

    if not can_afford_ai(user, per_step):
        result.update(stopped=STOP_BUDGET,
                      text="Not enough balance to start a run.")
        return result, 402

    try:
        import anthropic

        from .occ import MODEL_BY_VOICE, OCC_LLM_MODEL, _create_with_fallback
    except ImportError:
        result.update(stopped=STOP_ERROR, text="Coding agent unavailable (no LLM backend).")
        return result, 503

    # Snapshot BEFORE anything runs, so a bad run is one call to undo. Skipped on
    # a dry run, which by definition changes nothing.
    snapshot = None if dry_run else take_snapshot(project, label=str(prompt)[:140])

    messages = []
    for turn in (history or [])[-6:]:
        role = "assistant" if turn.get("role") in ("occ", "assistant") else "user"
        text = str(turn.get("text", "")).strip()
        if text:
            messages.append({"role": role, "content": text})
    messages.append({"role": "user", "content": str(prompt)})

    # A dry run plans without touching anything: the model sees a note saying its
    # write tools will be refused, so it explains its plan instead of pretending.
    extra = (
        "DRY RUN: the member asked for a plan only. Every write tool will be refused. "
        "Investigate with read-only tools and describe exactly what you would change."
        if dry_run else ""
    )
    system = build_system(project, extra)

    client = anthropic.Anthropic()
    texts = []

    while result["steps"] < cap:
        if not can_afford_ai(user, per_step):
            result["stopped"] = STOP_BUDGET
            break

        try:
            resp = _create_with_fallback(
                client,
                MODEL_BY_VOICE.get("corey-gpt", OCC_LLM_MODEL),
                OCC_LLM_MODEL,
                max_tokens=MAX_TOKENS,
                system=system,
                tools=TOOL_SCHEMAS,
                messages=messages,
            )
        except Exception as exc:
            log.info("occ agent: model call failed on step %s (%s)",
                     result["steps"] + 1, str(exc)[:200])
            result["stopped"] = STOP_ERROR
            if not texts:
                result["text"] = f"The model call failed: {str(exc)[:160]}"
            break

        result["steps"] += 1
        charged = charge_ai_usage(user, per_step, note=f"OCC agent · {project.name}")
        if charged is not None:
            result["cost_cents"] += per_step

        blocks = _blocks(getattr(resp, "content", None))
        texts += [b["text"] for b in blocks if b["type"] == "text"]
        calls = [b for b in blocks if b["type"] == "tool_use"]

        if not calls:
            result["stopped"] = STOP_DONE
            break

        messages.append({"role": "assistant", "content": blocks})
        results = []
        for call in calls:
            name, params = call["name"], call["input"]
            if dry_run and name in WRITE_TOOLS:
                ok, text = False, (
                    f"Refused: this is a dry run, so {name} is disabled. Describe the change "
                    "instead."
                )
            else:
                ok, text = run_tool(workspace, name, params)
            result["tool_calls"].append({
                "step": result["steps"],
                "name": name,
                "input": _summarize_input(params),
                "ok": ok,
                "result": text[:600],
            })
            results.append({
                "type": "tool_result",
                "tool_use_id": call["id"],
                "content": text[:8000],
                **({"is_error": True} if not ok else {}),
            })
        messages.append({"role": "user", "content": results})

        # Keep the transcript bounded: drop the oldest exchanges but always keep
        # the original request, which is the one message the model must not lose.
        if len(messages) > MAX_HISTORY_BLOCKS:
            messages = messages[:1] + messages[-(MAX_HISTORY_BLOCKS - 1):]
    else:
        result["stopped"] = STOP_MAX_STEPS

    result["changed"] = list(workspace.changed)
    if texts:
        result["text"] = "\n\n".join(t.strip() for t in texts if t.strip())
    elif result["stopped"] == STOP_MAX_STEPS:
        result["text"] = (
            f"Stopped after {cap} steps without finishing. "
            f"{len(result['changed'])} file(s) changed so far — say 'keep going' to continue."
        )
    elif result["stopped"] == STOP_BUDGET:
        result["text"] = (
            "Ran out of balance mid-run. "
            f"{len(result['changed'])} file(s) changed before it stopped."
        )

    run = AgentRun.objects.create(
        user=user, project=project, prompt=str(prompt)[:4000],
        reply=result["text"][:8000], steps=result["steps"],
        tool_calls=result["tool_calls"][:200], changed=result["changed"][:200],
        cost_cents=result["cost_cents"], stopped=result["stopped"], dry_run=dry_run,
    )
    result["run_id"] = run.id
    # Only offer an undo when there is something to undo.
    if snapshot and result["changed"]:
        snapshot.run = run
        snapshot.save(update_fields=["run"])
        result["undo"] = {"snapshot_id": snapshot.id, "files": snapshot.file_count}
    elif snapshot:
        snapshot.delete()
    result["money"] = round((wallet_for(user).money_cents or 0) / 100, 2)
    status = 200 if result["stopped"] in (STOP_DONE, STOP_MAX_STEPS) else (
        402 if result["stopped"] == STOP_BUDGET else 503
    )
    # A run that changed files did real work even if it ended badly — don't hand
    # back an error status that makes a client discard the result.
    if result["changed"] and status != 200:
        status = 200
    return result, status


def transcript(run):
    """One run as a compact, replayable record."""
    return {
        "id": run.id,
        "project": run.project.name,
        "prompt": run.prompt,
        "text": run.reply,
        "steps": run.steps,
        "tool_calls": run.tool_calls,
        "changed": run.changed,
        "cost_cents": run.cost_cents,
        "stopped": run.stopped,
        "dry_run": run.dry_run,
        "undo": (
            {"snapshot_id": run.snapshot.id, "files": run.snapshot.file_count}
            if getattr(run, "snapshot", None) else None
        ),
        "created_at": run.created_at,
    }


def as_json(value):
    """Defensive JSON for the transcript fields (sqlite + Postgres both fine)."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):  # pragma: no cover
        return str(value)[:2000]
