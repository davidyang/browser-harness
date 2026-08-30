import importlib.util
import json
from pathlib import Path

import pytest

from browser_harness import helpers as core_helpers


ROOT = Path(__file__).resolve().parents[2]


def _load_agent_helpers(monkeypatch, tmp_path, targets, closed):
    monkeypatch.setenv("BH_RUNTIME_DIR", str(tmp_path / "agent-runtime"))
    monkeypatch.setenv("BH_SHARED_STATE_DIR", str(tmp_path / "shared-runtime"))

    monkeypatch.setattr(core_helpers, "current_tab", lambda: targets["current"])
    monkeypatch.setattr(core_helpers, "list_tabs", lambda include_chrome=True: list(targets["live"].values()))

    def fake_new_tab(url="about:blank"):
        target_id = "agent-extra"
        targets["live"][target_id] = {"targetId": target_id, "title": "extra", "url": url}
        targets["current"] = targets["live"][target_id]
        return target_id

    def fake_close_tab(target):
        closed.append(target)
        targets["live"].pop(target, None)

    monkeypatch.setattr(core_helpers, "new_tab", fake_new_tab)
    monkeypatch.setattr(core_helpers, "close_tab", fake_close_tab)
    monkeypatch.setattr(core_helpers, "switch_tab", lambda target: target)
    monkeypatch.setattr(core_helpers, "goto_url", lambda url: url)
    monkeypatch.setattr(core_helpers, "cdp", lambda *args, **kwargs: {"targetId": "new-sentinel"})

    path = ROOT / "agent-workspace" / "agent_helpers.py"
    spec = importlib.util.spec_from_file_location("test_local_agent_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_named_agent_records_and_cleans_only_its_targets(monkeypatch, tmp_path):
    sentinel = {
        "targetId": "sentinel",
        "title": "bh-sentinel",
        "url": (ROOT / "agent-workspace" / "sentinel.html").resolve().as_uri(),
    }
    user_tab = {"targetId": "user-tab", "title": "manual", "url": "https://example.net"}
    targets = {
        "current": user_tab,
        "live": {"sentinel": sentinel, "user-tab": user_tab},
    }
    closed = []
    module = _load_agent_helpers(monkeypatch, tmp_path, targets, closed)

    assert module.new_tab("https://example.com") == "agent-extra"
    ownership = json.loads(module._OWNED_TARGETS.read_text())
    assert ownership == ["agent-extra"]

    assert module.cleanup_agent_tabs() == ["agent-extra"]
    assert closed == ["agent-extra"]
    assert "user-tab" in targets["live"]
    assert "sentinel" in targets["live"]


def test_global_tab_cleanup_is_disabled(monkeypatch, tmp_path):
    sentinel = {"targetId": "sentinel", "title": "bh-sentinel", "url": "file:///sentinel.html"}
    targets = {"current": sentinel, "live": {"sentinel": sentinel}}
    module = _load_agent_helpers(monkeypatch, tmp_path, targets, [])

    with pytest.raises(RuntimeError, match="disabled for shared Brave sessions"):
        module.close_extra_tabs()


def test_shared_wrapper_uses_named_daemon_and_brave_endpoint():
    text = (ROOT / "agent-workspace" / "bin" / "bh-agent").read_text()
    assert 'export BU_NAME="agent-${agent_name}"' in text
    assert 'export BU_CDP_URL="http://127.0.0.1:${port}"' in text
    assert '"$workspace_dir/bin/launch-brave"' in text


def test_installer_links_repository_workspace():
    text = (ROOT / "scripts" / "install-local-brave.sh").read_text()
    assert 'link_exact "$REPO_ROOT/agent-workspace" "$WORKSPACE_LINK"' in text
