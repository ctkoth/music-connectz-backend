"""The tools OCC can actually use — Claude Code's file toolset, over a workspace.

Every tool operates on a `Project`'s rows in the database, never on the server's
filesystem. That is the whole security model: OCC cannot read `settings.py`, walk
`/etc`, or touch another member's project, because there is no path that leads
out of the workspace. Traversal isn't blocked by a filter it could be tricked
past — the filesystem simply isn't in scope.

Semantics deliberately mirror Claude Code, because they're the ones that make an
agent reliable rather than merely capable:

* `edit_file` replaces an EXACT string and refuses when the match isn't unique.
  Fuzzy editing is how agents silently corrupt files.
* `read_file` returns numbered lines, so the model can talk about line 42 and
  mean it.
* `write_file` refuses to overwrite a file that hasn't been read this run,
  unless it's creating one. An agent that overwrites what it never looked at is
  guessing.

Each tool returns `(ok: bool, text: str)`. The text goes straight back to the
model as a tool result, so it is written for a reader who has no other context.
"""
import re

# Per-project ceilings. Generous enough for a real app, bounded enough that one
# member can't turn the workspace into free unlimited storage.
MAX_FILES = 200
MAX_FILE_CHARS = 200_000
MAX_TOTAL_CHARS = 2_000_000
MAX_PATH = 300
MAX_READ_LINES = 2_000
MAX_SEARCH_HITS = 100

_SAFE_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")


def normalize_path(raw):
    """A workspace-relative path, or None if it isn't one.

    Rejects absolute paths, `..`, backslashes, control characters and anything
    outside a conservative character set — not because the filesystem is
    reachable, but because a path is also a lookup key and a display string.
    """
    path = str(raw or "").strip()
    if not path or len(path) > MAX_PATH:
        return None
    if path.startswith("/") or "\\" in path:
        return None
    if not _SAFE_PATH.match(path):
        return None
    # Segment-wise, NOT string-wise. `lstrip("./")` strips a character *set*, so
    # it turns "../secrets.py" into "secrets.py" — a traversal that then passes
    # every later check because the `..` is gone. Split first, judge each part.
    parts = [p for p in path.split("/") if p and p != "."]
    if not parts or any(p == ".." for p in parts):
        return None
    # Collapsing empty parts also makes "a//b.py" and "a/b.py" one file.
    return "/".join(parts)


def _glob_to_re(pattern):
    """`**/*.py` / `src/*.js` as a regex. Small on purpose — enough to filter a
    workspace, not a general-purpose glob engine."""
    out, i = ["^"], 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    out.append("$")
    return re.compile("".join(out))


class Workspace:
    """The tool surface for one project. Tracks what's been read, so
    `write_file` can refuse to clobber a file the agent never looked at."""

    def __init__(self, project):
        from .models import ProjectFile

        self.project = project
        self._files = ProjectFile
        self.read_paths = set()
        self.changed = []       # paths this run created/edited/deleted, in order

    # ------------------------------------------------------------ helpers
    def _get(self, path):
        return self._files.objects.filter(project=self.project, path=path).first()

    def _total_chars(self, excluding=None):
        total = 0
        for f in self._files.objects.filter(project=self.project).only("path", "content"):
            if excluding and f.path == excluding:
                continue
            total += len(f.content)
        return total

    def _record(self, path):
        if path not in self.changed:
            self.changed.append(path)

    # ------------------------------------------------------------ tools
    def list_files(self, path=""):
        prefix = normalize_path(path) if path else ""
        if path and prefix is None:
            return False, f"Not a valid path: {path!r}"
        rows = self._files.objects.filter(project=self.project).order_by("path")
        if prefix:
            rows = rows.filter(path__startswith=prefix)
        rows = list(rows.only("path", "content"))
        if not rows:
            where = f" under {prefix}" if prefix else ""
            return True, f"The project has no files{where} yet. Use write_file to create one."
        lines = [f"{f.path} ({len(f.content)} chars, {f.content.count(chr(10)) + 1} lines)"
                 for f in rows]
        return True, f"{len(rows)} file(s):\n" + "\n".join(lines)

    def read_file(self, path, offset=None, limit=None):
        norm = normalize_path(path)
        if not norm:
            return False, f"Not a valid path: {path!r}"
        row = self._get(norm)
        if not row:
            return False, f"No such file: {norm}. Use list_files to see what exists."
        lines = row.content.split("\n")
        start = max(int(offset or 1), 1)
        count = min(int(limit or MAX_READ_LINES), MAX_READ_LINES)
        chunk = lines[start - 1:start - 1 + count]
        self.read_paths.add(norm)
        if not chunk:
            return True, f"{norm} has {len(lines)} lines; line {start} is past the end."
        body = "\n".join(f"{start + i:>5}\t{line}" for i, line in enumerate(chunk))
        more = ""
        if start - 1 + len(chunk) < len(lines):
            more = f"\n… {len(lines) - (start - 1 + len(chunk))} more lines. Read with offset={start + len(chunk)}."
        return True, body + more

    def write_file(self, path, content):
        norm = normalize_path(path)
        if not norm:
            return False, f"Not a valid path: {path!r}"
        content = str(content if content is not None else "")
        if len(content) > MAX_FILE_CHARS:
            return False, f"That file is {len(content)} chars; the limit is {MAX_FILE_CHARS}."

        row = self._get(norm)
        if row and norm not in self.read_paths:
            return False, (
                f"{norm} already exists and you haven't read it this run. Read it first, "
                "then write — or use edit_file to change one part without risking the rest."
            )
        if not row and self._files.objects.filter(project=self.project).count() >= MAX_FILES:
            return False, f"This project already has {MAX_FILES} files, the maximum."
        if self._total_chars(excluding=norm) + len(content) > MAX_TOTAL_CHARS:
            return False, "That would put the project over its total size limit."

        if row:
            row.content = content
            row.save(update_fields=["content", "updated_at"])
            verb = "Overwrote"
        else:
            self._files.objects.create(project=self.project, path=norm, content=content)
            verb = "Created"
        self.read_paths.add(norm)
        self._record(norm)
        return True, f"{verb} {norm} ({len(content)} chars)."

    def edit_file(self, path, old_string, new_string, replace_all=False):
        norm = normalize_path(path)
        if not norm:
            return False, f"Not a valid path: {path!r}"
        row = self._get(norm)
        if not row:
            return False, f"No such file: {norm}"
        old = str(old_string or "")
        new = str(new_string if new_string is not None else "")
        if not old:
            return False, "old_string is required. To create or replace a whole file use write_file."
        if old == new:
            return False, "old_string and new_string are identical — nothing to do."

        hits = row.content.count(old)
        if hits == 0:
            return False, (
                f"That exact string isn't in {norm}. Read the file and copy the text "
                "verbatim, including indentation."
            )
        if hits > 1 and not replace_all:
            return False, (
                f"That string appears {hits} times in {norm}. Include enough surrounding "
                "lines to make it unique, or pass replace_all=true."
            )

        updated = row.content.replace(old, new) if replace_all else row.content.replace(old, new, 1)
        if len(updated) > MAX_FILE_CHARS:
            return False, f"That edit would push {norm} past {MAX_FILE_CHARS} chars."
        row.content = updated
        row.save(update_fields=["content", "updated_at"])
        self.read_paths.add(norm)
        self._record(norm)
        return True, f"Edited {norm} ({hits if replace_all else 1} replacement(s))."

    def delete_file(self, path):
        norm = normalize_path(path)
        if not norm:
            return False, f"Not a valid path: {path!r}"
        row = self._get(norm)
        if not row:
            return False, f"No such file: {norm}"
        row.delete()
        self.read_paths.discard(norm)
        self._record(norm)
        return True, f"Deleted {norm}."

    def rename_file(self, path, new_path):
        norm, dest = normalize_path(path), normalize_path(new_path)
        if not norm or not dest:
            return False, "Both path and new_path have to be valid workspace paths."
        row = self._get(norm)
        if not row:
            return False, f"No such file: {norm}"
        if self._get(dest):
            return False, f"{dest} already exists."
        row.path = dest
        row.save(update_fields=["path", "updated_at"])
        self._record(norm)
        self._record(dest)
        return True, f"Renamed {norm} -> {dest}."

    def search(self, pattern, glob=None, case_sensitive=False):
        try:
            rx = re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
        except re.error as exc:
            return False, f"That isn't a valid regular expression: {exc}"
        matcher = _glob_to_re(glob) if glob else None
        hits, files = [], 0
        for f in self._files.objects.filter(project=self.project).order_by("path").only("path", "content"):
            if matcher and not matcher.match(f.path):
                continue
            found = False
            for n, line in enumerate(f.content.split("\n"), 1):
                if rx.search(line):
                    found = True
                    hits.append(f"{f.path}:{n}: {line.strip()[:200]}")
                    if len(hits) >= MAX_SEARCH_HITS:
                        break
            files += 1 if found else 0
            if len(hits) >= MAX_SEARCH_HITS:
                break
        if not hits:
            return True, f"No matches for {pattern!r}" + (f" in {glob}" if glob else "") + "."
        capped = f"\n… stopped at {MAX_SEARCH_HITS} matches." if len(hits) >= MAX_SEARCH_HITS else ""
        return True, f"{len(hits)} match(es) in {files} file(s):\n" + "\n".join(hits) + capped


# The schemas handed to the model. Descriptions are prompts in their own right —
# a vague one produces an agent that reaches for the wrong tool.
TOOL_SCHEMAS = [
    {
        "name": "list_files",
        "description": "List the files in the project with their sizes. Call this first when you don't know what's in the project.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Optional folder prefix to list."}},
        },
    },
    {
        "name": "read_file",
        "description": "Read a file, returned as numbered lines. Read a file before overwriting it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer", "description": "1-based first line to read."},
                "limit": {"type": "integer", "description": "How many lines to read."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Create a new file, or fully replace one you have already read this run. For a partial change use edit_file instead.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace an exact string in a file. old_string must match the file byte for byte, including indentation, and must be unique unless replace_all is true.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
                "replace_all": {"type": "boolean"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "search",
        "description": "Regex search across the project's file contents. Returns path:line: text. Use this instead of reading every file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "glob": {"type": "string", "description": "Filter paths, e.g. **/*.py"},
                "case_sensitive": {"type": "boolean"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "rename_file",
        "description": "Move or rename a file within the project.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "new_path": {"type": "string"}},
            "required": ["path", "new_path"],
        },
    },
    {
        "name": "delete_file",
        "description": "Delete a file from the project. There is no undo, so be sure.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
]

TOOL_NAMES = [t["name"] for t in TOOL_SCHEMAS]

# Tools that change the workspace. Used to decide whether a run needs the
# member's confirmation, and to report what a run touched.
WRITE_TOOLS = {"write_file", "edit_file", "delete_file", "rename_file"}


def run_tool(workspace, name, params):
    """Dispatch one tool call. Returns (ok, text) — never raises."""
    if name not in TOOL_NAMES:
        return False, f"There is no tool called {name!r}. Available: {', '.join(TOOL_NAMES)}"
    params = params if isinstance(params, dict) else {}
    method = getattr(workspace, name)
    allowed = set(TOOL_SCHEMAS[TOOL_NAMES.index(name)]["input_schema"]["properties"])
    kwargs = {k: v for k, v in params.items() if k in allowed}
    try:
        return method(**kwargs)
    except TypeError as exc:
        return False, f"Wrong arguments for {name}: {exc}"
    except Exception as exc:  # a tool must never take the run down
        return False, f"{name} failed: {str(exc)[:200]}"
