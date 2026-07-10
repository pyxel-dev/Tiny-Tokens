# Architecture

tito is one Python file, no dependencies. It does two unrelated jobs, connected only by the fact that they both know which commands are "handled":

```
Claude (Bash tool)
  │
  ▼
PreToolUse hook — rewrites "git status" into "tito git status"
  │                (never runs anything, never sees output)
  ▼
Bash tool executes the rewritten command
  │
  ▼
tito runs the real command, filters its output,
prints the compact version, records byte savings
```

## 1. The hook (interception)

Registered once by `tito install` as a Claude Code `PreToolUse` hook on the Bash tool. It reads the hook JSON on stdin, and if the command string is a chain of recognized commands, rewrites each segment to be prefixed with `tito`. This is what makes the tool "transparent" — you type `git status`, Claude Code actually runs `tito git status`, and the model never has to know tito exists.

Rewrite rules, in order of importance:

- Only rewrite a segment if its first word is a recognized command.
- Never rewrite anything whose output is consumed by something else: pipes (`git diff | wc -l`), command substitution (`` $(...) `` / backticks), or redirections.
- Never double-rewrite (`tito`/`rtk` prefix already present).
- Skip anything with unclear shell structure (unbalanced quotes, backgrounding, heredocs).

**Doubt always favors passthrough.** A missed rewrite just means one command runs unfiltered for a turn; a wrong rewrite could change what a pipeline actually does. The hook is deliberately conservative.

## 2. Dispatch (the actual filtering)

When tito runs a command, the flow is:

1. Look up a **filter** for the command name in the registry.
2. No filter → run the command as-is, print raw output, done.
3. Filter found → optionally **transform** the argv (e.g. add `--porcelain=v1` to `git status`) before running it.
4. Run the (possibly transformed) command for real, capturing stdout/stderr/exit code.
5. **Render** the captured output into a compact string — or `None` if the renderer doesn't recognize the shape of this particular output.
6. `None` → print raw output. A string → print the compact version and record the bytes saved.

Every step after "filter found" is wrapped so that any exception (transform crashing, render crashing) falls back to raw output rather than surfacing an error or hiding the command's result. That fallback behavior is the core guarantee of the tool: **tito can never break a command**, only fail to compress it.

Convention: renderers check the exit code first and return `None` on failure, so command errors always reach Claude in full — compact rendering is a courtesy for success, not for debugging failures.

## 3. Filters today

Only one extension ships in the repo so far — `git`
(`extensions/git/default.py`), the reference/example filter:

| Command | Strategy |
|---|---|
| `git status` | `--porcelain=v1 -b` internally, 1 line per file + branch |
| `git diff` / `show` | file headers + hunk markers + changed lines only |
| `git log` | 1 line per commit (`--format=%h %ad %s --date=short`) |
| `git add` / `commit` / `push` / `pull` | ultra-short confirmation |

Everything else — `grep`, `find`, `diff`, `env`, `ls`, and the rest of
the [planned catalog](Extensions.md#whats-available) — passes straight
through until an extension for it is written.

## 4. Extensions

See [Extensions](Extensions.md) — the same registry mechanism that loads core filters also loads user-installed ones from `~/.config/tito/filters/`, with local files always taking priority.

## 5. Stats

Every filtered run appends one JSONL line (timestamp, command, raw bytes, filtered bytes) to `~/.config/tito/stats.jsonl`. `tito gain` aggregates it into a per-command and total savings report, estimating tokens as bytes ÷ 4. Passthrough runs record nothing — there's nothing saved to measure.
