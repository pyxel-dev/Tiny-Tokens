"""git filter for tito — the example bundled extension.

Compact git output: porcelain status, hunk-only diffs, short log, and
one-word confirmations for write ops. Errors (code != 0) fall through
raw so real failures are never hidden.
"""

COMMANDS = ["git"]


def _subcommand(argv):
    """First non-flag argument after 'git', or None."""
    for arg in argv[1:]:
        if not arg.startswith("-"):
            return arg
    return None


def transform(argv):
    """Prefer machine-readable output over scraping human-formatted text."""
    sub = _subcommand(argv)
    if sub == "status" and not any(a.startswith("--porcelain") for a in argv):
        return argv + ["--porcelain=v1", "-b"]
    if sub == "log" and not any(
        a.startswith("--format") or a.startswith("--pretty") for a in argv
    ):
        return argv + ["--format=%h %ad %s", "--date=short"]
    return argv


def _render_status(stdout):
    """Porcelain v1 -b output -> branch line + one line per file."""
    lines = [l for l in stdout.splitlines() if l]
    parts = []
    for line in lines:
        parts.append(line[3:] if line.startswith("## ") else line)
    if len(parts) == 1:
        return parts[0] + " clean"
    return "\n".join(parts)


def _render_diff(stdout):
    """Unified diff -> file headers, hunk markers, changed lines only.

    Returns None (raw fallback) unless at least one hunk/content line was
    kept, so --stat/--name-only/header-only diffs pass through raw.
    """
    if not stdout.strip():
        return "no diff"
    kept = []
    has_content = False
    for line in stdout.splitlines():
        if line.startswith("diff --git"):
            kept.append("=== " + line.split(" b/")[-1])
        elif line.startswith("@@"):
            end = line.find("@@", 2)
            kept.append(line[: end + 2] if end != -1 else line)
            has_content = True
        elif line[:1] in ("+", "-") and not line.startswith(("+++", "---")):
            kept.append(line)
            has_content = True
    if not has_content:
        return None
    return "\n".join(kept)


def _render_confirm(sub, stdout, stderr):
    """Ultra-short success confirmations for write operations."""
    if sub == "add":
        return "ok"
    if sub == "commit":
        ref, summary = "", ""
        for line in stdout.splitlines():
            if line.startswith("[") and "]" in line:
                ref = line[1 : line.index("]")]
            elif "changed" in line:
                summary = line.strip()
        return f"ok [{ref}] {summary}".rstrip()
    if sub == "push":
        return "ok pushed"
    lines = [l.strip() for l in stdout.splitlines() if l.strip()]
    return "ok " + (lines[-1] if lines else "done")


def filter(argv, stdout, stderr, code):
    if code != 0:
        return None  # errors go through raw so Claude sees them
    sub = _subcommand(argv)
    if sub == "status":
        return _render_status(stdout)
    if sub == "log":
        return stdout
    if sub in ("diff", "show"):
        return _render_diff(stdout)
    if sub in ("add", "commit", "push", "pull"):
        return _render_confirm(sub, stdout, stderr)
    return None
