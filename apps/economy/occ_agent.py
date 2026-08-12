"""OCC's agent loop — the part that changes code instead of describing it.

`occ.py` makes ONE `messages.create()` call with no `tools=`. That is the whole
difference between an assistant that explains a bug and one that fixes it. This
module is the loop: call the model, run whatever tools it asked for, feed the
results back, repeat until it stops asking.

Four things it is careful about, each of them a rule from somewhere else in this
codebase rather than an invention here.

**The ceiling is stated before the run, and it binds.** A run is 20-80 model
calls; nobody — including the model — can predict how many. So the member is not
given an estimate, they are given a MAXIMUM, and the loop checks the accumulated
spend before every call and stops when it reaches it. Charged after is what it
actually used, which is nearly always less. A price discovered by paying it is a
bill; a ceiling is a price.

**A run that produced nothing is not billed.** Same rule `vocalcoach.py` bills
on and `occ_run.py` inherited: if the model never answered, nothing is charged.

**A failed tool is the model's problem, not the member's.** Every tool result
comes back as a readable error with `is_error`, never an exception, so the model
fixes its own mistake instead of the member seeing a 500 for something they did
not do.

**Writing is gated, reading is not.** `read` / `glob` / `grep` always run.
`write` / `edit` change a member's source and only run when writes are allowed
for this run; otherwise they come back refused, and the model reports what it
WOULD change. Phase 3 turns that flag into the AutomationZ / SuggestionZ
toggles, which already exist and currently gate nothing.

A manual loop rather than the SDK's `tool_runner`, deliberately: the runner is
synchronous and this loop has to stop mid-way on a spend ceiling and — once
Phase 3 lands — hand a proposed write to a member who may not answer for an
hour. That is not a shape the runner's per-turn hook fits.
"""
import json
import logging

from .catalog import (
    ai_model_for,
    ai_run_budget,
    ai_run_charge_cents,
    ai_run_cost_cents,
)
from .models import (
    OccFile,
    OccTask,
    charge_ai_usage,
    membership_for,
    profile_for,
)
from .occ_tools import CHANGES_FILES, TOOLS, run_tool

log = logging.getLogger(__name__)

# How many times round the loop before we stop regardless of budget. The spend
# ceiling is the real limit; this is the backstop for a model that gets stuck in
# a read-read-read cycle cheap enough never to reach it.
MAX_TURNS = 24

# Per call, not per run. Big enough for thinking plus a substantial edit, small
# enough to stay well inside the SDK's non-streaming timeout.
MAX_TOKENS_PER_TURN = 16_000

AGENT_SYSTEM = """You are OCC, the coding agent inside Music ConnectZ. You work \
on the member's project by calling tools — you can read files, search them, and \
change them.

How to work:
- Look before you edit. Use glob to see what exists and grep to find things; \
read a file before changing it. An edit written against a file you have not read \
is a guess.
- Prefer edit over write on a file that already exists. write replaces the whole \
file and will silently discard anything you did not include.
- Make the change the member asked for, at the scope they asked for. Do not add \
features, refactor surrounding code, or introduce abstractions they did not ask \
for. A bug fix does not need a tidy-up around it.
- Do not add error handling, validation, or fallbacks for situations that cannot \
happen.
- When you are done, say what you changed in one or two sentences. Lead with the \
outcome. Do not recap every tool call — the member can see the files.
- If you cannot do something, say so plainly and say why. Do not claim work you \
did not do, and do not report a file as changed unless a tool told you it was.

You have a spending limit for this task and you are told what is left. Work \
within it: do the important part first, and if you are running short, finish \
cleanly and say what remains rather than stopping mid-edit."""


def _client():
    """The Anthropic client, or None when the key isn't configured."""
    try:
        import anthropic
    except ImportError:                                      # pragma: no cover
        return None
    try:
        return anthropic.Anthropic()
    except Exception:                                        # pragma: no cover
        return None


def _text_of(content):
    """The plain text of a response, ignoring thinking and tool blocks."""
    return "".join(
        block.text for block in content
        if getattr(block, "type", "") == "text"
    ).strip()


def _budget_note(spent, max_cents):
    """What the model has left, in the only unit it can act on: how much is gone.

    The system prompt tells the model it has a limit and will be told what
    remains. Without this it never was — a prompt that promises the model
    information nobody sends it is a prompt that lies, and the model paces
    itself against a number it had to invent.
    """
    used = int(round(100 * spent / max(1, max_cents)))
    if used < 50:
        return f"\n\nBudget: about {used}% used. Plenty left — work normally."
    if used < 80:
        return (f"\n\nBudget: about {used}% used. Start prioritising — do the "
                "important part of the task first.")
    return (f"\n\nBudget: about {used}% used. Finish cleanly NOW: stop opening "
            "new work, complete what is half-done, and say plainly what remains.")


def _accumulate(total, usage):
    """Add one response's usage to the running total for the whole run."""
    for field in ("input_tokens", "output_tokens",
                  "cache_read_input_tokens", "cache_creation_input_tokens"):
        total[field] = total.get(field, 0) + int(getattr(usage, field, 0) or 0)
    return total


def run_agent(user, prompt, *, project="main", model_key=None,
              writes_allowed=False, tab="occ"):
    """Run one agent task. Returns a dict the view can serialise as-is.

    Never raises for anything the model or the member did — a bad tool call, an
    exhausted budget and a refusal are all ordinary outcomes with a `stopped`
    reason. Only a missing API key short-circuits, and it says so.
    """
    tier = membership_for(user).tier
    model_key, spec = ai_model_for(model_key or profile_for(user).ai_model, tier)
    budget = ai_run_budget(tier)
    max_cents = budget["max_cents"]

    client = _client()
    if client is None:
        return {"ok": False, "stopped": "unavailable",
                "detail": "OCC's model backend isn't configured on the server yet."}

    # The task row exists from the start: a run that dies halfway should still
    # leave a record of what was asked, not vanish.
    task = OccTask.objects.create(
        user=user, title=str(prompt).strip().splitlines()[0][:200] or "OCC task",
        kind=OccTask.KIND_EDIT, status=OccTask.STATUS_RUNNING,
        detail=f"{spec['emoji']} {spec['name']} · up to {max_cents} 🏷️",
    )

    messages = [{"role": "user", "content": str(prompt)}]
    total = {}
    changed = set()
    turns = 0
    stopped = "end_turn"
    text = ""

    while turns < MAX_TURNS:
        # Charged, not cost. The ceiling is the number on the button, so the gate
        # has to measure the same thing the member's wallet will.
        spent = ai_run_charge_cents(model_key, total)
        if spent >= max_cents:
            # Checked BEFORE the call, the way the API's own session budgets
            # work: the ceiling bounds new work, so the last call completes and
            # the next one never starts.
            stopped = "budget"
            break

        # `effort` is GA and needs no beta header, but it 400s on Haiku — hence
        # the per-model flag rather than sending it to everything.
        #
        # The API's own `task_budget` would be the better pacing signal, but it
        # needs the beta endpoint AND the beta flag, and sending it here would
        # 400 every real request while the tests' fake client happily accepted
        # it. The budget note below does the same job with no beta surface.
        extra = {}
        if spec.get("effort"):
            extra["output_config"] = {"effort": "medium"}

        try:
            response = client.messages.create(
                model=spec["id"],
                max_tokens=MAX_TOKENS_PER_TURN,
                system=AGENT_SYSTEM + _budget_note(spent, max_cents),
                tools=TOOLS,
                messages=messages,
                **extra,
            )
        except Exception as exc:
            log.error("OCC agent: %s call failed — %s", spec["id"], str(exc)[:300])
            stopped = "error"
            text = text or "The model backend couldn't be reached for that one."
            break

        turns += 1
        _accumulate(total, getattr(response, "usage", None) or object())

        # Checked before `content` is read: on a refusal the content list is
        # empty or partial, and indexing it is how this becomes a 500.
        if getattr(response, "stop_reason", "") == "refusal":
            stopped = "refused"
            text = ("The model declined that request. Rephrasing it, or asking "
                    "for a smaller piece of it, usually gets past this.")
            break

        text = _text_of(response.content) or text
        calls = [b for b in response.content if getattr(b, "type", "") == "tool_use"]
        if not calls:
            stopped = "end_turn"
            break

        # The assistant turn goes back verbatim — dropping the tool_use blocks
        # breaks the pairing the next request validates.
        messages.append({"role": "assistant", "content": response.content})

        results = []
        for call in calls:
            if call.name in CHANGES_FILES and not writes_allowed:
                out = {"ok": False, "error": (
                    "Writes aren't approved for this run, so nothing was changed. "
                    "Describe the change you would make instead, precisely enough "
                    "that the member can approve it.")}
            else:
                out = run_tool(user, call.name, call.input, project=project)
                if out.get("ok") and call.name in CHANGES_FILES:
                    changed.add(out.get("path"))
                    OccFile.objects.filter(
                        user=user, project=project, path=out.get("path")
                    ).update(task=task)
            results.append({
                "type": "tool_result",
                "tool_use_id": call.id,
                # JSON, not str(dict). A Python repr comes back with single
                # quotes and `True`, which the model then has to guess at;
                # JSON is the shape it reads reliably.
                "content": json.dumps(out, default=str),
                "is_error": not out.get("ok", False),
            })
        # Every result in ONE user message. Splitting them teaches the model to
        # stop making parallel calls.
        messages.append({"role": "user", "content": results})
    else:
        stopped = "max_turns"

    # Two numbers on purpose. `cost` is what Anthropic billed the platform;
    # `price` is what the member pays for it. The member is charged the price;
    # the cost is kept so a run can be audited against the real bill later.
    cost = ai_run_cost_cents(model_key, total)
    price = ai_run_charge_cents(model_key, total)
    charged = 0
    if price:
        remaining = charge_ai_usage(
            user, price, note=f"OCC agent · {spec['name']} · {turns} turns",
            count_daily=False)
        # None means they couldn't cover it. The work is already done and the
        # tokens are already spent, so the honest thing is to record it and say
        # so rather than pretend the run didn't happen.
        charged = price if remaining is not None else 0

    task.status = OccTask.STATUS_DONE if stopped in ("end_turn", "budget") else OccTask.STATUS_FAILED
    task.progress = 100 if stopped == "end_turn" else task.progress
    task.detail = (f"{turns} turns · {len(changed)} file(s) · −{charged} 🏷️"
                   + ("" if stopped == "end_turn" else f" · stopped: {stopped}"))
    task.save(update_fields=["status", "progress", "detail", "updated_at"])

    return {
        "ok": stopped in ("end_turn", "budget"),
        "text": text,
        "stopped": stopped,
        "turns": turns,
        "changed": sorted(p for p in changed if p),
        # What left the member's wallet. Named `cost_cents` because every other
        # AI surface in this app reports it under that key and the client reads
        # one shape — but it is the PRICE, and `served_cents` beside it is what
        # the run actually cost to serve.
        "cost_cents": charged,
        "served_cents": cost,
        "max_cents": max_cents,
        "engine": model_key,
        "engine_name": spec["name"],
        "engine_emoji": spec["emoji"],
        "usage": total,
        "task_id": task.id,
        "writes_allowed": writes_allowed,
        # A result you can't take anywhere is a dead end with a scrollbar.
        "open_in": "occ", "target": "occ:filez",
    }
