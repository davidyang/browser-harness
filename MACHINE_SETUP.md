# Machine setup: dedicated Chrome for Testing + sentinel + auto-launch

This branch turns browser-harness into a driver for a **dedicated Chrome for Testing
(CfT)** instance instead of your everyday Chrome, with:

- **No focus steal** — opening/switching tabs never raises the OS window (`BH_NO_ACTIVATE`).
- **A sentinel window** — one persistent anchor tab keeps the automation window non-empty
  so background tabs stay backgrounded; every new tab lands in that one window.
- **Auto-launch** — any `browser-harness` call starts CfT if it's the configured endpoint
  and not already running, so a fresh session never has to remember a launch command.
- **Clean launches** — CfT never session-restores, so tabs/sentinels don't accumulate.
- **Auto-closing tabs** — a `tab()` context manager disposes throwaway tabs and re-anchors.

It is macOS + Apple-Silicon oriented (CfT path glob is `mac_arm-*`); adjust for other
platforms where noted.

---

## What lives where

| Piece | Location | In this git branch? |
|---|---|---|
| Core patches (`BH_NO_ACTIVATE` gate, `_maybe_launch_cft`) | `src/browser_harness/{helpers,daemon}.py` | **Yes** |
| Config: `.env`, `agent_helpers.py` | `~/.config/browser-harness/agent-workspace/` | No — see below |
| Launcher + anchor page | `~/.config/browser-harness/cft/{launch-cft.sh,sentinel.html}` | No — see below |
| CfT binary | `~/.cache/puppeteer/chrome/...` | No — installed per machine |

The config files live outside the repo (loaded by the tool from the config dir, independent
of the current working directory). Copies are embedded in the [Appendix](#appendix-config-files)
so a machine without them can be set up from this file alone.

---

## What the core patches do

- **`helpers.py`** — `switch_tab()` skips `Target.activateTarget`, and `new_tab()` passes
  `background: true` to `Target.createTarget`, when `BH_NO_ACTIVATE=1`. (macOS: keeps the
  window from raising/stealing focus. Mirrors upstream PR #469.)
- **`daemon.py`** — the no-real-pages bootstrap also passes `background: true`; plus a new
  `_maybe_launch_cft()` called from `get_ws_url()` that, when `BH_CFT_LAUNCHER` is set and the
  loopback CfT endpoint is down, runs the launcher and waits for a real page to load before
  attaching (so the daemon lands on the sentinel instead of spawning a stray `about:blank`).

Both are gated/opt-in: with none of the env vars set, behavior is identical to upstream.

---

## Reproduce on a new machine

### 1. Install browser-harness as an editable clone
A plain `uv tool install browser-harness` from PyPI will **not** contain the patches. You need
this branch, installed editable:

```bash
git clone https://github.com/davidyang/browser-harness.git ~/dev/browser-harness
cd ~/dev/browser-harness
git checkout cft-automation-setup
uv tool install --python 3.12 --force --editable .
```

Verify the tool loads from the clone:

```bash
browser-harness <<'PY'
import browser_harness; print(browser_harness.__file__)
PY
# → .../dev/browser-harness/src/browser_harness/__init__.py
```

### 2. Install Chrome for Testing

```bash
npx -y @puppeteer/browsers install chrome@stable --path "$HOME/.cache/puppeteer"
```

Prints the installed path, e.g.
`~/.cache/puppeteer/chrome/mac_arm-<ver>/chrome-mac-arm64/Google Chrome for Testing.app/...`.
On Intel/Linux the folder is `mac_x64-*` / `linux-*` — update the glob in `launch-cft.sh`
(the `chrome-mac-arm64` path segment) to match.

### 3. Place the config files
If your `~/.config` is the same Dropbox-synced symlink, these arrive automatically — skip to
step 4. Otherwise create them from the [Appendix](#appendix-config-files):

```bash
mkdir -p ~/.config/browser-harness/cft ~/.config/browser-harness/agent-workspace
# write cft/launch-cft.sh, cft/sentinel.html,
#       agent-workspace/agent_helpers.py, agent-workspace/.env
chmod +x ~/.config/browser-harness/cft/launch-cft.sh
```

### 4. Fix the one machine-specific line
`.env` is **not** shell-expanded by the harness — `BH_CFT_LAUNCHER` must be a literal absolute
path. If your username isn't `dyang`, edit it:

```
BH_CFT_LAUNCHER=/Users/<you>/.config/browser-harness/cft/launch-cft.sh
```

### 5. Reload and verify
```bash
browser-harness --reload
browser-harness <<'PY'
new_tab("https://example.com"); wait_for_load()
print(page_info().get("url"))
print("tabs:", [t["title"] for t in list_tabs()])
PY
```

Expected: CfT auto-launches, `example.com` loads in the background (window not raised), and
`list_tabs()` shows exactly `bh-sentinel` + the new tab. Kill CfT and rerun — the tab set must
be identical (no accumulation).

### 6. Logins (optional)
CfT's profile is persistent, so logins survive relaunches (cookies live in the profile, not the
session files the launcher clears). To use 1Password **passkeys** without the browser extension,
enable 1Password as a macOS **system provider**: 1Password app → Settings → General → enable the
macOS AutoFill integration, then System Settings → General → AutoFill & Passwords → turn on
1Password. The passkey then appears in the native macOS sheet in CfT. Fallback that always works:
the sheet's "use a passkey from another device" → scan with your phone. (The browser extension
is not required and is unlikely to connect to CfT anyway.)

---

## Helpers available in `browser-harness` scripts

- `ensure_sentinel()` → targetId of the anchor tab (creates it in the background if missing).
- `tab(url=None, keep=False)` → context manager; opens a throwaway tab, then closes it and
  re-anchors to the sentinel on exit.
- `close_extra_tabs()` → close every tab except the sentinel.

```python
with tab("https://example.com") as tid:
    print(page_info())      # tab auto-closes after the block
```

---

## Gotchas

- **CfT starts clean each launch.** Only the sentinel (plus whatever automation opens) — the
  launcher deletes SNSS session files so tabs don't accumulate. Cookies/logins persist; manually
  opened tabs do **not** survive a restart. Use your normal Chrome if you want durable tabs.
- **`.env` makes CfT the default target.** Every `browser-harness` call now hits `:9333`. If CfT
  can't be started, calls fail after ~30s. Comment out `BU_CDP_URL` + `browser-harness --reload`
  to fall back to normal Chrome.
- **Don't put the CfT profile in a cloud-synced folder.** If `~/.config` is Dropbox-synced, move
  the profile out (e.g. point `PROFILE` in `launch-cft.sh` at `~/.cache/browser-harness/cft-profile`)
  — syncing a live browser profile churns constantly and risks corruption if two machines run CfT
  against it at once.
- **These patches diverge from upstream `main`.** `browser-harness --update` (git pull --ff-only)
  won't fast-forward over local commits; update by rebasing this branch onto upstream instead.

---

## Appendix: config files

### `~/.config/browser-harness/agent-workspace/.env`
```ini
# browser-harness config — auto-loaded by helpers.py and daemon.py.
# NOTE: not shell-expanded — BH_CFT_LAUNCHER must be a literal absolute path.
BU_CDP_URL=http://127.0.0.1:9333
BH_NO_ACTIVATE=1
BH_CFT_LAUNCHER=/Users/dyang/.config/browser-harness/cft/launch-cft.sh
```

### `~/.config/browser-harness/cft/sentinel.html`
```html
<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>bh-sentinel</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  html,body{height:100%;margin:0}
  body{background:#0f1115;color:#8fa3b0;font:15px/1.5 system-ui,sans-serif;
       display:grid;place-items:center;text-align:center}
  h1{font-weight:600;color:#cdd9e0;margin:.2em 0}
  code{background:#1b1f27;padding:.1em .4em;border-radius:4px;color:#9ecbff}
  p{max-width:34rem;margin:.4em auto}
</style>
<body>
  <div>
    <div style="font-size:52px">🐴</div>
    <h1>browser-harness sentinel</h1>
    <p>Keep this tab open. It anchors the Chrome-for-Testing automation window so
       new tabs open in the background without raising the window or stealing focus.</p>
    <p>Managed by <code>agent-workspace/agent_helpers.py</code> · closing it is harmless
       (it will be recreated).</p>
  </div>
</body>
</html>
```

### `~/.config/browser-harness/cft/launch-cft.sh`
```bash
#!/usr/bin/env bash
# Launch Chrome for Testing as a dedicated browser-harness automation instance.
# Idempotent: if the debug endpoint is already up, it does nothing.
set -euo pipefail

PORT="${BH_CFT_PORT:-9333}"
CFT_ROOT="$HOME/.cache/puppeteer/chrome"
PROFILE="$HOME/.config/browser-harness/cft/profile"
SENTINEL="file://$HOME/.config/browser-harness/cft/sentinel.html"

if curl -sf -m 2 "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
  echo "Chrome for Testing already listening on :${PORT}"
  exit 0
fi

# Newest installed CfT binary (mac arm64 — adjust chrome-mac-arm64 for other platforms).
BIN="$(ls -d "$CFT_ROOT/"*/chrome-mac-arm64/"Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing" 2>/dev/null | sort -V | tail -1 || true)"
if [ -z "${BIN:-}" ] || [ ! -x "$BIN" ]; then
  echo "Chrome for Testing not found under $CFT_ROOT" >&2
  echo "Install it: npx -y @puppeteer/browsers install chrome@stable --path \"\$HOME/.cache/puppeteer\"" >&2
  exit 1
fi

mkdir -p "$PROFILE"

# Force a clean-exit state so Chrome doesn't crash-restore the previous session.
PREFS="$PROFILE/Default/Preferences"
if [ -f "$PREFS" ]; then
  python3 - "$PREFS" <<'PYEOF'
import json, sys
path = sys.argv[1]
try:
    with open(path) as f:
        d = json.load(f)
except Exception:
    sys.exit(0)
prof = d.setdefault("profile", {})
prof["exit_type"] = "Normal"
prof["exited_cleanly"] = True
sess = d.setdefault("session", {})
sess["restore_on_startup"] = 5
sess.pop("startup_urls", None)
try:
    with open(path, "w") as f:
        json.dump(d, f)
except Exception:
    pass
PYEOF
fi

# Delete SNSS session-restore files (exit_type=Normal only hides the bubble; CfT still
# restores tabs from these, which accumulated random tabs + duplicate sentinels).
rm -f "$PROFILE/Default/Sessions/"Session_* "$PROFILE/Default/Sessions/"Tabs_* 2>/dev/null || true
rm -f "$PROFILE/Default/Current Session" "$PROFILE/Default/Current Tabs" \
      "$PROFILE/Default/Last Session" "$PROFILE/Default/Last Tabs" 2>/dev/null || true

nohup "$BIN" \
  --remote-debugging-port="$PORT" \
  --remote-debugging-address=127.0.0.1 \
  --user-data-dir="$PROFILE" \
  --no-first-run \
  --no-default-browser-check \
  --disable-session-crashed-bubble \
  --hide-crash-restore-bubble \
  "$SENTINEL" \
  >/dev/null 2>&1 &
disown || true

for _ in $(seq 1 50); do
  if curl -sf -m 1 "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
    echo "Chrome for Testing up on :${PORT}"
    exit 0
  fi
  sleep 0.2
done
echo "Chrome for Testing did not expose :${PORT} within ~10s" >&2
exit 1
```

### `~/.config/browser-harness/agent-workspace/agent_helpers.py`
```python
"""Agent-editable browser helpers: sentinel window + auto-closing tabs.

browser_harness.helpers execs this file at import and merges its public names into the
helpers namespace, so `browser-harness` scripts can call these directly. Because it runs
as its own module, the core primitives it uses must be imported explicitly below.
"""

import contextlib
import os
from pathlib import Path

from browser_harness.helpers import (
    cdp, list_tabs, new_tab, switch_tab, close_tab,
)

SENTINEL_URL = Path(os.path.expanduser("~/.config/browser-harness/cft/sentinel.html")).as_uri()
_SENTINEL_TITLE = "bh-sentinel"


def _is_sentinel(t):
    url = t.get("url") or ""
    title = (t.get("title") or "").lstrip("\U0001F434 ")  # strip 🐴 marker
    return url == SENTINEL_URL or url.endswith("/sentinel.html") or title == _SENTINEL_TITLE


def ensure_sentinel():
    """Return the sentinel tab's targetId, creating it in the background if absent."""
    for t in list_tabs(include_chrome=True):
        if _is_sentinel(t):
            return t["targetId"]
    bg = os.environ.get("BH_NO_ACTIVATE") == "1"
    params = {"url": SENTINEL_URL}
    if bg:
        params["background"] = True
    return cdp("Target.createTarget", **params)["targetId"]


@contextlib.contextmanager
def tab(url=None, keep=False):
    """Open a throwaway tab, run the block against it, then close it and re-anchor
    to the sentinel. keep=True leaves it open but still re-anchors on exit."""
    sentinel = ensure_sentinel()
    tid = new_tab(url) if url else new_tab()
    try:
        yield tid
    finally:
        if not keep:
            try: close_tab(tid)
            except Exception: pass
        try: switch_tab(sentinel)
        except Exception: pass


def close_extra_tabs():
    """Close every real tab except the sentinel, then attach to the sentinel."""
    sentinel = ensure_sentinel()
    for t in list_tabs(include_chrome=False):
        if t["targetId"] != sentinel:
            try: close_tab(t["targetId"])
            except Exception: pass
    switch_tab(sentinel)
```
