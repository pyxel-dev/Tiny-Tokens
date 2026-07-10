# Extensions

An extension is just a filter file (see [Writing Filters](Writing-Filters.md)) that lives in the same directory whether you wrote it yourself or downloaded it: `~/.config/tito/filters/`. There's no separate mechanism for "official" vs "custom" — only where the file came from.

## Official registry

```
tito enable <name>    # downloads <name>/default.py from the registry
tito disable <name>   # renames it to <name>/default.py.disabled
```

`tito enable` fetches `<name>/default.py` from:

```
https://raw.githubusercontent.com/pyxel-dev/Tiny-Tokens/main/extensions/<name>/default.py
```

(A nested name like `go/build` is used as-is instead: `go/build.py`.)

Set `TITO_REGISTRY` to point at a different source (including a `file://` URL) if you maintain your own extensions directory.

If `<name>/default.py.disabled` already exists locally, `enable` just renames it back rather than re-downloading — so disabling and re-enabling an extension never loses local edits you made to it.

## Browsing the registry

```
tito browse
```

Fetches `extensions/manifest.json` from the registry, shows every available extension with its description and local status (`enabled`/`disabled`/not installed) in a checkbox picker (`↑`/`↓` or `j`/`k` to move, `space` to toggle, `a`/`n` to select/deselect all, `Enter` to install everything checked, `q`/`Esc` to cancel), and installs each selection the same way `tito enable <name>` would. Requires an interactive terminal.

## Priority

Extensions are loaded after core filters and always win — there's no separate override step, it falls out of load order:

```
core filters  →  ~/.config/tito/filters/*.py (alphabetical)
```

So a custom filter with the same `COMMANDS` entry as a core filter (or as another extension loaded earlier alphabetically) replaces it entirely. This is intentional: you can always override any built-in behavior by dropping a file with the same command name.

## Safety

A broken extension (syntax error, missing `COMMANDS`, import failure) is skipped with a warning to stderr — it never prevents tito from loading the rest of the registry, and never blocks the command you were trying to run.

## What's available

The `extensions/` directory in the repo holds the official extensions served over the registry URL. Today that's just `git` (`extensions/git/default.py`) — the reference/example extension covering `status`, `diff`, `show`, `log`, `add`, `commit`, `push`, `pull`. Everything else (cargo, gh, npm, pnpm, docker, kubectl, curl, playwright, the JS/TS and Python toolchains, per-ecosystem folders for Go/.NET/Java/Ruby/PHP) is planned but not yet in the repo. Contributions of new ones are welcome; see [Contributing](../CONTRIBUTING.md).
