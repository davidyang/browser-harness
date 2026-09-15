# Local setup: persistent Brave automation instances

This branch keeps Browser Harness core code aligned with upstream `main` and
adds a machine layer for David's Macs:

- persistent, non-default Brave profiles selected by logical instance name;
- command-line remote debugging on loopback, avoiding the permission popup;
- a sentinel tab that keeps the automation window alive;
- one Brave process per instance and one named daemon per agent;
- cleanup that closes only the stopping agent's owned tab; and
- a repository-owned `agent-workspace` linked into the machine configuration.

## Difference from upstream main

The machine layer owns instance selection and lifecycle. Two small core helpers
generate a durable instance label in controlled tab titles; upstream continues
to own CDP transport, tab attachment, and daemon recovery.

This branch adds only:

| File | Responsibility |
|---|---|
| `agent-workspace/bin/launch-brave` | Idempotently launch the dedicated Brave profile on a dynamic loopback port |
| `agent-workspace/bin/bh-agent` | Select an instance, assign a named daemon, and expose scoped restart |
| `agent-workspace/browser_instance.py` | Resolve profiles/endpoints and verify exact process ownership |
| `agent-workspace/sentinel.html` | Keep the automation window anchored |
| `agent-workspace/agent_helpers.py` | Recover the sentinel and provide scoped temporary-tab cleanup |
| `scripts/install-local-brave.sh` | Link the shared workspace and archive obsolete local setup |
| `SKILL.md` | Require agents on David's Macs to use the named wrapper |

## State placement

| State | Location |
|---|---|
| Shared helper source, wrapper, launcher, sentinel | This Git repository |
| Browser Harness workspace entry point | `~/.config/browser-harness/agent-workspace` symlink |
| Default shared profile and login state | `~/Library/Application Support/BraveSoftware/Brave-Browser-Automation` |
| Named instance profiles and login state | `~/Library/Application Support/BraveSoftware/Brave-Browser-Automation-Instances/<instance>` |
| Named daemon sockets and logs | `/private/tmp/bh-<instance>-<agent-name>` (`shared` keeps the legacy path) |
| Migration backups | `~/Library/Application Support/browser-harness/migration-backups` |

The Brave profile is never placed in Dropbox or Git.

Two running Brave processes never use the same profile directory. A persistent
instance keeps its own authentication through restarts; authenticating a new
instance is a one-time provisioning step unless the site expires the session.

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

For an automation, add a stable instance name distinct from the agent name:

```bash
bh-agent amazon-returns --instance amazon-personal <<'PY'
print(page_info())
PY
```

Controlled tabs use `🐴 [amazon-personal]` as a durable title prefix. When a
login flow activates the tab, macOS displays that prefix in the Brave window
title. Restart plans are read-only:

```bash
bh-agent recovery --instance amazon-personal --restart-instance --dry-run
```

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
