"""Shared local helpers for the dedicated Brave automation browser.

This file is canonical in the repository. Machine setup links the Browser
Harness agent workspace to this directory so fixes travel through Git.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - macOS/Linux setup; harmless elsewhere
    fcntl = None

from browser_harness.helpers import (
    cdp,
    close_tab as _core_close_tab,
    current_tab,
    goto_url,
    list_tabs,
    new_tab as _core_new_tab,
    switch_tab,
)


SENTINEL_URL = Path(__file__).resolve().with_name("sentinel.html").as_uri()
_SENTINEL_TITLE = "bh-sentinel"
_SHARED_STATE = Path(os.environ.get("BH_SHARED_STATE_DIR", "/private/tmp/browser-harness-shared"))
_AGENT_STATE = Path(os.environ.get("BH_RUNTIME_DIR", "/private/tmp/browser-harness-agent"))
_OWNED_TARGETS = _AGENT_STATE / "owned-targets.json"


def _is_sentinel(target):
    title = (target.get("title") or "").removeprefix("🐴 ")
    return target.get("url") == SENTINEL_URL or title == _SENTINEL_TITLE


@contextlib.contextmanager
def _sentinel_lock():
    """Serialize sentinel recovery across independently named daemons."""
    _SHARED_STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = _SHARED_STATE / "sentinel.lock"
    with path.open("a+") as handle:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_UN)


def ensure_sentinel():
    """Return the shared sentinel target, recreating it in the background."""
    with _sentinel_lock():
        for target in list_tabs(include_chrome=True):
            if _is_sentinel(target):
                return target["targetId"]
        return cdp(
            "Target.createTarget",
            url=SENTINEL_URL,
            background=True,
        )["targetId"]


def _target_id(target):
    if isinstance(target, dict):
        return target.get("targetId") or target.get("target_id")
    return target


@contextlib.contextmanager
def _owned_targets_lock():
    _AGENT_STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = _AGENT_STATE / "owned-targets.lock"
    with path.open("a+") as handle:
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _read_owned_targets():
    try:
        data = json.loads(_OWNED_TARGETS.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return set()
    return {value for value in data if isinstance(value, str)}


def _write_owned_targets(targets):
    _AGENT_STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = _OWNED_TARGETS.with_suffix(".tmp")
    temporary.write_text(json.dumps(sorted(targets)) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(_OWNED_TARGETS)


def _remember_target(target):
    target_id = _target_id(target)
    if not target_id:
        return
    with _owned_targets_lock():
        targets = _read_owned_targets()
        targets.add(target_id)
        _write_owned_targets(targets)


def _forget_target(target):
    target_id = _target_id(target)
    if not target_id:
        return
    with _owned_targets_lock():
        targets = _read_owned_targets()
        targets.discard(target_id)
        _write_owned_targets(targets)


def new_tab(url="about:blank"):
    """Create or reuse a tab and record it as belonging to this named agent."""
    target_id = _core_new_tab(url)
    _remember_target(target_id)
    return target_id


def close_tab(target=None):
    """Close a target and remove it from this named agent's ownership record."""
    target_id = _target_id(target)
    if target_id is None:
        target_id = _target_id(current_tab())
    result = _core_close_tab(target_id)
    _forget_target(target_id)
    return result


def cleanup_agent_tabs():
    """Close only targets previously recorded by this named agent."""
    sentinel = ensure_sentinel()
    live_targets = {target["targetId"] for target in list_tabs(include_chrome=True)}
    with _owned_targets_lock():
        owned = _read_owned_targets()
        closed = []
        remaining = set()
        for target_id in sorted(owned):
            if target_id == sentinel or target_id not in live_targets:
                continue
            try:
                _core_close_tab(target_id)
                closed.append(target_id)
            except Exception:
                remaining.add(target_id)
        _write_owned_targets(remaining)
    return closed


@contextlib.contextmanager
def tab(url=None, keep=False):
    """Use a temporary agent-owned tab and clean up only that target.

    When the named daemon's existing tab is blank, ``new_tab`` reuses it. In
    that case cleanup navigates it back to blank instead of closing the daemon's
    owned target. ``keep=True`` preserves the final page for a later invocation.
    """
    ensure_sentinel()
    previous = current_tab()
    previous_id = previous.get("targetId") or previous.get("target_id")
    target_id = new_tab(url) if url else new_tab()
    created = target_id != previous_id
    try:
        yield target_id
    finally:
        if not keep:
            if created:
                try:
                    close_tab(target_id)
                finally:
                    if previous_id:
                        try:
                            switch_tab(previous_id)
                        except Exception:
                            pass
            else:
                try:
                    goto_url("about:blank")
                except Exception:
                    pass


def close_extra_tabs():
    """Reject global cleanup in a browser shared by independently named agents."""
    raise RuntimeError(
        "close_extra_tabs() is disabled for shared Brave sessions; "
        "close only a target created by this agent or stop its named daemon"
    )
