# Local setup: shared Brave automation

This branch keeps Browser Harness core code aligned with upstream `main` and
adds a machine layer for David's Macs:

- a persistent, non-default Brave automation profile;
- command-line remote debugging on loopback, avoiding the permission popup;
- a sentinel tab that keeps the automation window alive;
- one named daemon and owned background tab per agent;
- cleanup that closes only the stopping agent's owned tab; and
- a repository-owned `agent-workspace` linked into the machine configuration.

## Difference from upstream main

There are no custom patches under `src/browser_harness/`. Current upstream
already opens and switches tabs in the background, gives named local daemons a
dedicated tab, recovers that tab safely, and closes only that owned tab when the
daemon stops.

This branch adds only:

| File | Responsibility |
|---|---|
| `agent-workspace/bin/launch-brave` | Idempotently launch the dedicated Brave profile on port 9333 |
| `agent-workspace/bin/bh-agent` | Assign a stable named daemon and shared Brave endpoint |
| `agent-workspace/sentinel.html` | Keep the automation window anchored |
| `agent-workspace/agent_helpers.py` | Recover the sentinel and provide scoped temporary-tab cleanup |
| `scripts/install-local-brave.sh` | Link the shared workspace and archive obsolete local setup |
| `SKILL.md` | Require agents on David's Macs to use the named wrapper |

## State placement

| State | Location |
|---|---|
| Shared helper source, wrapper, launcher, sentinel | This Git repository |
| Browser Harness workspace entry point | `~/.config/browser-harness/agent-workspace` symlink |
| Brave automation profile and login state | `~/Library/Application Support/BraveSoftware/Brave-Browser-Automation` |
| Named daemon sockets and logs | `/private/tmp/bh-<agent-name>` |
| Migration backups | `~/Library/Application Support/browser-harness/migration-backups` |

The Brave profile is never placed in Dropbox or Git.

## Install on a Mac

Install the editable package from this checkout, then install the machine layer:

```bash
uv tool install --python 3.12 --force --editable ~/dev/browser-harness
~/dev/browser-harness/scripts/install-local-brave.sh --dry-run
~/dev/browser-harness/scripts/install-local-brave.sh
```

The installer preserves replaced configuration in a timestamped local backup.
It does not delete the prior browser profile.

## Agent use

Give each concurrent task a unique, stable name:

```bash
bh-agent research-a <<'PY'
new_tab("https://example.com")
wait_for_load()
print(page_info())
PY
```

Reuse that name for later calls in the same task. When the task is complete:

```bash
bh-agent research-a --stop
```

The wrapper records targets opened through `new_tab()`. On stop it closes those
recorded targets, then upstream shutdown closes the daemon's dedicated tab. It
does not close Brave, the sentinel, another agent's tab, or a manually opened
tab.

For a one-call throwaway page, the shared helper is also available:

```bash
bh-agent research-b <<'PY'
with tab("https://example.com"):
    wait_for_load()
    print(page_info())
PY
bh-agent research-b --stop
```

Never enable global tab pruning or call `close_extra_tabs()` in the shared
browser. Neither mechanism can prove ownership of another target.

## Verification

```bash
bh-agent verify-a <<'PY'
print(page_info())
print([t["title"] for t in list_tabs()])
PY

bh-agent verify-b <<'PY'
print(page_info())
PY

bh-agent verify-a --stop
bh-agent verify-b --stop
```

Expected behavior:

- Brave starts automatically without a remote-debugging prompt.
- Exactly one sentinel remains available.
- `verify-a` and `verify-b` attach to different background tabs.
- stopping `verify-a` does not affect `verify-b`.
- stopping both leaves Brave and the sentinel open.

## Updating from upstream

Because the customization does not patch core files, update by merging current
upstream `main`, run the full test suite, and repeat the two-agent verification.
