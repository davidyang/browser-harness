import importlib.util
import json
import signal
from pathlib import Path

import pytest

from browser_harness import helpers as core_helpers


ROOT = Path(__file__).resolve().parents[2]


def _load_browser_instance():
    path = ROOT / "agent-workspace" / "browser_instance.py"
    spec = importlib.util.spec_from_file_location("test_browser_instance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_wrapper_delegates_instance_layout_and_endpoint_resolution():
    text = (ROOT / "agent-workspace" / "bin" / "bh-agent").read_text()
    assert "BrowserInstance.create" in text
    assert 'environment["BU_CDP_WS"] = instance.endpoint()' in text
    assert 'WORKSPACE / "bin" / "launch-brave"' in text


def test_named_browser_instance_has_its_own_persistent_profile(tmp_path):
    module = _load_browser_instance()
    instance = module.BrowserInstance.create(
        agent_name="amazon-returns",
        instance_name="amazon-personal",
        home=tmp_path,
    )

    assert instance.profile == tmp_path / "Library/Application Support/BraveSoftware/Brave-Browser-Automation-Instances/amazon-personal"
    assert instance.environment()["BU_NAME"] == "agent-amazon-personal-amazon-returns"
    assert instance.environment()["BH_TAB_TITLE_PREFIX"] == "amazon-personal"
    assert instance.environment()["BH_BRAVE_PROFILE"] == str(instance.profile)


def test_shared_browser_instance_preserves_existing_paths(tmp_path):
    module = _load_browser_instance()
    instance = module.BrowserInstance.create(agent_name="research-a", instance_name="shared", home=tmp_path)

    assert instance.profile == tmp_path / "Library/Application Support/BraveSoftware/Brave-Browser-Automation"
    assert instance.environment()["BU_NAME"] == "agent-research-a"
    assert instance.environment()["BH_RUNTIME_DIR"] == "/private/tmp/bh-research-a"


@pytest.mark.parametrize("name", ["", "has space", "../escape", "a" * 25])
def test_browser_instance_rejects_unsafe_names(tmp_path, name):
    module = _load_browser_instance()
    with pytest.raises(ValueError):
        module.BrowserInstance.create(agent_name="task", instance_name=name, home=tmp_path)


def test_restart_signals_only_the_verified_profile_process(tmp_path):
    module = _load_browser_instance()
    instance = module.BrowserInstance.create(agent_name="amazon-returns", instance_name="amazon-personal", home=tmp_path)
    instance.profile.mkdir(parents=True)
    (instance.profile / "SingletonLock").symlink_to("host.example-6045")
    command = f"{module.DEFAULT_BRAVE_PATH} --remote-debugging-port=0 --user-data-dir={instance.profile}"
    reads = iter([command, command, None])
    signals = []
    launches = []

    result = instance.restart(
        process_reader=lambda _pid: next(reads),
        signal_process=lambda pid, sig: signals.append((pid, sig)),
        launch=lambda: launches.append(True),
        sleep=lambda _seconds: None,
    )

    assert signals == [(6045, signal.SIGTERM)]
    assert launches == [True]
    assert result == {"instance": "amazon-personal", "previous_pid": 6045, "restarted": True}


def test_restart_refuses_an_unverified_process(tmp_path):
    module = _load_browser_instance()
    instance = module.BrowserInstance.create(agent_name="amazon-returns", instance_name="amazon-personal", home=tmp_path)
    instance.profile.mkdir(parents=True)
    (instance.profile / "SingletonLock").symlink_to("host.example-6045")

    with pytest.raises(module.InstanceError, match="does not own browser instance"):
        instance.restart(
            process_reader=lambda _pid: "/usr/bin/python --user-data-dir=/tmp/not-this-profile",
            signal_process=lambda *_args: pytest.fail("must not signal"),
            launch=lambda: pytest.fail("must not launch"),
        )


def test_restart_recovers_a_stale_singleton_pid_without_signaling(tmp_path):
    module = _load_browser_instance()
    instance = module.BrowserInstance.create(agent_name="amazon-returns", instance_name="amazon-personal", home=tmp_path)
    instance.profile.mkdir(parents=True)
    (instance.profile / "SingletonLock").symlink_to("host.example-6045")
    launches = []

    result = instance.restart(
        process_reader=lambda _pid: None,
        signal_process=lambda *_args: pytest.fail("must not signal a stale PID"),
        launch=lambda: launches.append(True),
    )

    assert launches == [True]
    assert result == {"instance": "amazon-personal", "previous_pid": 6045, "restarted": True}


def test_restart_dry_run_changes_nothing(tmp_path):
    module = _load_browser_instance()
    instance = module.BrowserInstance.create(agent_name="amazon-returns", instance_name="amazon-personal", home=tmp_path)
    instance.profile.mkdir(parents=True)
    (instance.profile / "SingletonLock").symlink_to("host.example-6045")
    command = f"{module.DEFAULT_BRAVE_PATH} --user-data-dir={instance.profile}"

    result = instance.restart(
        dry_run=True,
        process_reader=lambda _pid: command,
        signal_process=lambda *_args: pytest.fail("must not signal"),
        launch=lambda: pytest.fail("must not launch"),
    )

    assert result == {"instance": "amazon-personal", "previous_pid": 6045, "restarted": False, "would_restart": True}


def test_launcher_hides_automation_controlled_signal():
    """--remote-debugging-port=0 sets navigator.webdriver; challenges loop on it."""
    text = (ROOT / "agent-workspace" / "bin" / "launch-brave").read_text()
    assert "--remote-debugging-port=0" in text
    assert "--disable-blink-features=AutomationControlled" in text
    assert "--enable-automation" not in text


def test_installer_links_repository_workspace():
    text = (ROOT / "scripts" / "install-local-brave.sh").read_text()
    assert 'link_exact "$REPO_ROOT/agent-workspace" "$WORKSPACE_LINK"' in text
