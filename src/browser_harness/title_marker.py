"""Generate idempotent Browser Harness tab-title marker scripts."""

from __future__ import annotations

import json
import os


def prefix(environ=None) -> str:
    environment = os.environ if environ is None else environ
    label = environment.get("BH_TAB_TITLE_PREFIX", "").strip()
    return f"🐴 [{label}] " if label else "🐴 "


def mark_script(environ=None) -> str:
    title_prefix = json.dumps(prefix(environ), ensure_ascii=False)
    return f"""(() => {{
  const prefix = {title_prefix};
  const key = '__browserHarnessTitleObserver';
  const clean = () => document.title.replace(/^\ud83d\udc34(?: \\[[A-Za-z0-9_-]{{1,24}}\\])? /, '');
  const mark = () => {{ if (!document.title.startsWith(prefix)) document.title = prefix + clean(); }};
  mark();
  if (!globalThis[key]) {{
    const observer = new MutationObserver(mark);
    observer.observe(document.head || document.documentElement, {{subtree: true, childList: true, characterData: true}});
    globalThis[key] = observer;
  }}
}})()"""


def unmark_script(environ=None) -> str:
    title_prefix = json.dumps(prefix(environ), ensure_ascii=False)
    return f"""(() => {{
  const prefix = {title_prefix};
  const key = '__browserHarnessTitleObserver';
  if (globalThis[key]) {{ globalThis[key].disconnect(); delete globalThis[key]; }}
  if (document.title.startsWith(prefix)) document.title = document.title.slice(prefix.length);
}})()"""
