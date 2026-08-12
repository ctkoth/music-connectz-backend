"""The tools OCC uses to change code, and the executor behind them.

Until now `occ.py` made ONE `messages.create()` call with no `tools=` at all,
which is the whole difference between an assistant that explains code and one
that changes it. This module is the other half: the tool definitions the model
is given, and the code that runs them against `OccFile`.

Four rules it inherits from the rest of the app.

**The path gate is not optional.** Every tool takes a `path` and every path goes
through `normalize_occ_path` before it touches a query. These rows become real
files in a sandbox, so a path checked in the view and not here is a path that
isn't checked.

**A tool that fails says why, to the model.** Errors come back as
`{"ok": False, "error": ...}` and are returned to the model as a normal tool
result with `is_error`, never raised. The model can then fix its own mistake —
a 500 makes the member fix it instead, and they didn't make it.

**Reading is free; changing is not.** `read`, `glob` and `grep` are
side-effect-free and can run in parallel. `write` and `edit` change a member's
source, so they carry `changes_files: True` and the loop routes them through
TaskZ for approval. That split is what makes an approval prompt possible at all
— see `agent-design.md` on why a dedicated tool beats a bash string here.

**The caps come from `catalog.py`.** Never a literal in this file: the tier
ceilings are published to the client from one place, and a second copy here is
how the "20 free prompts" figure got into nine.
"""
import fnmatch
import re

from .catalog import (
    OCC_MAX_FILE_CHARS,
    OCC_MAX_PROJECT_NAME_CHARS,
    occ_file_limits,
)
from .models import OccFile, membership_for, normalize_occ_path

# How much of a file a single `read` may return, and how many hits `grep` and
# `glob` may report. A 200,000-character file read into a 1M context is fine
# once and ruinous in a loop that reads it forty times, so the tool truncates
# and SAYS it truncated — silently returning half a file is how a model
# confidently edits the part it couldn't see.
MAX_READ_CHARS = 60_000
MAX_MATCHES = 200
MAX_GREP_LINE_CHARS = 400


def _project(raw):
    """A project name, cleaned — or None. Same shape as the path gate.

    Blank means the default project, not an error: the tool signature already
    defaults to "main", so a caller sending "" or nothing is saying "wherever I
    already am". Anything blank-but-not-empty used to fall the other way and be
    refused, which meant `""` and `"   "` did different things for no reason a
    member could have predicted.

    A name that is present but unusable — a separator, a NUL, one longer than
    the column — is still refused, because those are attempts at a different
    project rather than an unstated one.
    """
    name = str(raw if raw is not None else "").strip() or "main"
    if "\x00" in name or "/" in name or "\\" in name:
        return None
    # Capped against catalog, which is capped against the column. SQLite would
    # take a longer name and Postgres would 500 on it — the exact gap CLAUDE.md
    # says to respect.
    return name if len(name) <= OCC_MAX_PROJECT_NAME_CHARS else None


def _err(message):
    return {"ok": False, "error": message}


# ---------------------------------------------------------------------------
# The tool definitions handed to the model
# ---------------------------------------------------------------------------
#
# Descriptions are deliberately long. A tool description is the single biggest
# factor in whether a model uses a tool correctly, and the common failure is
# under-describing it — so each says what it does, when to reach for it, and
# what it does NOT return.

TOOLS = [
    {
        "name": "read",
        "description": (
            "Read a file from the member's OCC project. Returns the file's full "
            "text with line numbers, so you can quote exact line references back "
            "to the member. Use this before editing anything — an edit written "
            "against a file you have not read is a guess. If the file is longer "
            "than the read limit the result is truncated and says so explicitly; "
            "when that happens, use grep to find the region you need rather than "
            "re-reading. Returns an error, not an empty file, when the path does "
            "not exist — so an error here means check the path with glob, not "
            "that the file is blank."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string",
                         "description": "Project-relative path, e.g. src/main.py"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "write",
        "description": (
            "Create a file, or replace one entirely. This overwrites the whole "
            "file — to change part of an existing file use edit instead, which "
            "will not silently discard the parts you did not mention. Creating "
            "parent directories is automatic; paths are plain relative strings. "
            "This changes the member's source, so it may require their approval "
            "before it takes effect."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Project-relative path"},
                "content": {"type": "string", "description": "The complete file contents"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "edit",
        "description": (
            "Replace an exact string in a file. `old` must appear EXACTLY once — "
            "if it appears zero times or more than once the edit is refused and "
            "nothing changes, which is deliberate: an edit that lands in the "
            "wrong one of three identical blocks is worse than an edit that "
            "fails. Include enough surrounding context in `old` to make it "
            "unique. Preserve the file's existing indentation exactly. This "
            "changes the member's source, so it may require their approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Project-relative path"},
                "old": {"type": "string",
                        "description": "Exact text to replace; must occur exactly once"},
                "new": {"type": "string", "description": "Text to put in its place"},
            },
            "required": ["path", "old", "new"],
            "additionalProperties": False,
        },
    },
    {
        "name": "glob",
        "description": (
            "List files in the project whose path matches a glob pattern, e.g. "
            "'*.py', 'src/**/*.jsx', 'src/*'. Use this to find out what exists "
            "before reading — it is much cheaper than reading files to discover "
            "them. Returns paths and sizes only, never file contents. With no "
            "pattern it lists every file in the project."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string",
                            "description": "Glob pattern; omit to list everything"},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "grep",
        "description": (
            "Search file contents with a regular expression and return matching "
            "lines with their paths and line numbers. This is the right way to "
            "locate something in a project too large to read — search first, "
            "then read only the files that matched. Optionally narrow to a glob "
            "pattern. Returns matching lines only, not whole files; long lines "
            "are truncated."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regular expression"},
                "glob": {"type": "string",
                         "description": "Optional path filter, e.g. '*.py'"},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
]

# Which tools change a member's source. The loop reads this to decide what needs
# an approval prompt, so a new tool that writes MUST be added here — a tool
# missing from this set is one that edits code with nobody being asked.
CHANGES_FILES = {"write", "edit"}

TOOL_NAMES = {tool["name"] for tool in TOOLS}


# ---------------------------------------------------------------------------
# The executor
# ---------------------------------------------------------------------------

def _numbered(text):
    """File contents with line numbers, the format models quote back reliably."""
    lines = text.splitlines()
    return "\n".join(f"{i:>5}\t{line}" for i, line in enumerate(lines, 1))


def run_tool(user, name, args, *, project="main"):
    """Run one tool call. Returns a dict — never raises for a bad input.

    `{"ok": True, ...}` on success, `{"ok": False, "error": "..."}` otherwise.
    The caller turns a falsy `ok` into a tool result with `is_error: True`, so
    the model reads its own mistake and retries instead of the member seeing a
    500 for something they didn't do.
    """
    if name not in TOOL_NAMES:
        return _err(f"There's no tool called {name!r}.")
    args = args or {}

    slug = _project(project)
    if not slug:
        return _err("That project name isn't usable.")

    tier = membership_for(user).tier
    limits = occ_file_limits(tier)
    files = OccFile.objects.filter(user=user, project=slug)

    # ---- read
    if name == "read":
        path = normalize_occ_path(args.get("path"))
        if not path:
            return _err("That path isn't usable — give a relative path like src/main.py.")
        row = files.filter(path=path).first()
        if row is None:
            return _err(f"There's no file at {path!r} in this project. "
                        "Use glob to see what exists.")
        body, truncated = row.content, False
        if len(body) > MAX_READ_CHARS:
            body, truncated = body[:MAX_READ_CHARS], True
        out = {"ok": True, "path": path, "content": _numbered(body),
               "chars": len(row.content)}
        if truncated:
            # Said out loud. A model that edits the part of a file it could not
            # see is confidently wrong, and it has no way to know.
            out["truncated"] = (
                f"Only the first {MAX_READ_CHARS:,} of {len(row.content):,} "
                "characters are shown. Use grep to find the rest.")
        return out

    # ---- write
    if name == "write":
        path = normalize_occ_path(args.get("path"))
        if not path:
            return _err("That path isn't usable — give a relative path like src/main.py.")
        content = args.get("content")
        if not isinstance(content, str):
            return _err("`content` must be the complete text of the file.")
        if len(content) > OCC_MAX_FILE_CHARS:
            return _err(f"That file is {len(content):,} characters — the limit is "
                        f"{OCC_MAX_FILE_CHARS:,}. Split it across files.")
        existing = files.filter(path=path).first()
        if existing is None and files.count() >= limits["files_per_project"]:
            return _err(f"This project is at its {limits['files_per_project']} file "
                        "limit. Delete something, or a higher tier carries more.")
        row, created = OccFile.objects.update_or_create(
            user=user, project=slug, path=path, defaults={"content": content})
        return {"ok": True, "path": path, "created": created,
                "chars": len(content),
                "detail": f"{'Created' if created else 'Replaced'} {path}"}

    # ---- edit
    if name == "edit":
        path = normalize_occ_path(args.get("path"))
        if not path:
            return _err("That path isn't usable — give a relative path like src/main.py.")
        old, new = args.get("old"), args.get("new")
        if not isinstance(old, str) or not isinstance(new, str):
            return _err("`old` and `new` must both be strings.")
        if not old:
            return _err("`old` can't be empty — use write to create a file.")
        row = files.filter(path=path).first()
        if row is None:
            return _err(f"There's no file at {path!r} to edit. Use write to create it.")
        hits = row.content.count(old)
        if hits == 0:
            return _err(f"That exact text isn't in {path!r}. Read the file again — "
                        "whitespace and indentation have to match exactly.")
        if hits > 1:
            # Refusing beats guessing: an edit landing in the wrong one of three
            # identical blocks is a bug the member finds much later.
            return _err(f"That text appears {hits} times in {path!r}, so this edit "
                        "is ambiguous. Include more surrounding context to make "
                        "it unique.")
        updated = row.content.replace(old, new, 1)
        if len(updated) > OCC_MAX_FILE_CHARS:
            return _err(f"That edit would take {path!r} over the "
                        f"{OCC_MAX_FILE_CHARS:,} character limit.")
        row.content = updated
        row.save(update_fields=["content", "updated_at"])
        return {"ok": True, "path": path, "chars": len(updated),
                "detail": f"Edited {path}"}

    # ---- glob
    if name == "glob":
        pattern = str(args.get("pattern") or "*")
        rows = list(files.values_list("path", "content"))
        matched = [
            {"path": path, "chars": len(content)}
            for path, content in rows
            # fnmatch treats "*" as crossing "/" — which is what a member means
            # by "*.py" in a project this size, and it makes "src/**/*.py" work
            # without a second matcher.
            if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, f"{pattern}/*")
        ]
        return {"ok": True, "pattern": pattern, "count": len(matched),
                "files": matched[:MAX_MATCHES]}

    # ---- grep
    if name == "grep":
        raw = str(args.get("pattern") or "")
        if not raw:
            return _err("`pattern` is required.")
        try:
            rx = re.compile(raw)
        except re.error as exc:
            # The model wrote the regex, so the model gets to fix it.
            return _err(f"That isn't a valid regular expression: {exc}")
        path_filter = args.get("glob")
        hits = []
        for path, content in files.values_list("path", "content"):
            if path_filter and not fnmatch.fnmatch(path, str(path_filter)):
                continue
            for number, line in enumerate(content.splitlines(), 1):
                if rx.search(line):
                    hits.append({"path": path, "line": number,
                                 "text": line[:MAX_GREP_LINE_CHARS]})
                    if len(hits) >= MAX_MATCHES:
                        break
            if len(hits) >= MAX_MATCHES:
                break
        return {"ok": True, "pattern": raw, "count": len(hits), "matches": hits}

    return _err(f"There's no tool called {name!r}.")   # pragma: no cover
