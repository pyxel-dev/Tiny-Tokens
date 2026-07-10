# Writing your own filter

Drop a Python file in `~/.config/tito/filters/`. No registration step — tito loads every `*.py` file in that directory automatically. A plain flat file (e.g. `docker.py`) works fine for a hand-written filter, but `tito new-filter`/`enable` use one folder per command with the file named `default.py` — see [Managing filters](#managing-filters) below.

```python
# ~/.config/tito/filters/docker/default.py
COMMANDS = ["docker"]

def filter(argv, stdout, stderr, code):
    """Return compact output, or None to keep the raw output."""
    if code != 0:
        return None  # let Claude see real errors, unfiltered
    return "\n".join(l for l in stdout.splitlines() if "Up " in l)
```

That's the whole contract:

- `COMMANDS` — list of command names this file handles (usually one).
- `filter(argv, stdout, stderr, code) -> str | None` — `argv` is the full command as a list (`["docker", "ps", "-a"]`), `stdout`/`stderr` are the captured strings, `code` is the exit code. Return `None` to fall back to raw output for this particular invocation (e.g. a shape of output your filter doesn't understand yet).

## Optional: rewrite the command before it runs

If you need a machine-readable flag that isn't there by default, add a `transform`:

```python
def transform(argv):
    """docker ps -> docker ps --format '{{.Names}}\t{{.Status}}'"""
    if "--format" in argv:
        return argv
    return argv + ["--format", "{{.Names}}\t{{.Status}}"]
```

`transform(argv) -> argv` runs before the command executes. Prefer this over parsing whatever the tool prints by default — structured flags (`--porcelain`, `--format`, `--json`, `-1F`…) are far more stable across tool versions and locales than scraping human-oriented output.

## Rules of thumb

- **Fail safe.** If your filter raises an exception, tito silently falls back to raw output — it will never crash a command or hide its result. You don't need defensive `try/except` inside `filter()` unless you specifically want partial results instead of a full fallback.
- **Check the exit code first.** Compact rendering is for successful runs. On failure, return `None` so Claude sees the real error output — don't try to compress error messages.
- **Return `None`, don't guess.** If the output doesn't look like what you expected (unexpected flags used, unfamiliar format), return `None` rather than producing a misleading compact summary.

## Optional: split one command across subcommands

If a command's subcommands print genuinely different output shapes (`go build`'s compiler diagnostics vs. `go test`'s pass/fail report), put one file per subcommand in a folder instead of cramming both shapes into one `filter()`:

```
~/.config/tito/filters/go/build.py   # COMMANDS = ["go"], SUBCOMMANDS = ["build"]
~/.config/tito/filters/go/test.py    # COMMANDS = ["go"], SUBCOMMANDS = ["test"]
```

Each file adds `SUBCOMMANDS = [...]` (the first non-flag argument after the command, e.g. `"build"` in `go build -v`) alongside its `COMMANDS`. tito merges every file under `go/` into one filter for `go` that routes by subcommand at call time. A file with no `SUBCOMMANDS` is the folder's default and handles any subcommand none of its siblings claimed; with no default, an unclaimed subcommand just passes through raw. `tito enable`/`disable`/`new-filter` accept the nested form directly: `tito new-filter go/vet`.

A folder can also just group unrelated commands from the same ecosystem with no routing involved — e.g. `java/mvn.py` and `java/gradle.py` each declare their own distinct `COMMANDS`. That's purely organizational.

## Testing a filter

There's no test harness required — a filter is just a plain function. Feed it fixture stdout/stderr and assert on the returned string, the same way `tests/extensions/git/test_git.py` tests the bundled `git` filter. See [Contributing](../CONTRIBUTING.md) for running the test suite.

## Managing filters

```
tito filters             # list core filters + installed extensions
tito new-filter <name>   # scaffold ~/.config/tito/filters/<name>/default.py
tito disable <name>      # rename to <name>/default.py.disabled (kept, not deleted)
tito enable <name>       # re-enable a locally disabled filter, or
                            # download an official one — see Extensions
```

(`<name>` can also be a nested path like `go/vet`, in which case it's used as-is: `go/vet.py`, no `default` involved.)
