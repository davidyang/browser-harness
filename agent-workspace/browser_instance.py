"""Persistent, isolated local Brave instances for Browser Harness agents."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import re
import signal
import subprocess
import time


DEFAULT_BRAVE_PATH = Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser")
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,24}$")


class InstanceError(RuntimeError):
    pass


def _validate_name(value: str, label: str) -> str:
    if not NAME_RE.fullmatch(value or ""):
        raise ValueError(f"{label} must contain 1–24 letters, digits, underscores, or hyphens")
    return value


def singleton_pid(profile: Path) -> int | None:
    lock = profile / "SingletonLock"
    try:
        target = os.readlink(lock)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise InstanceError(f"browser profile has an unreadable SingletonLock: {lock}") from error
    match = re.search(r"-(\d+)$", target)
    if not match:
        raise InstanceError(f"browser profile has a malformed SingletonLock: {lock} -> {target}")
    return int(match.group(1))


def read_process_command(pid: int) -> str | None:
    completed = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "command="],
        text=True,
        capture_output=True,
    )
    command = completed.stdout.strip()
    return command if completed.returncode == 0 and command else None


class BrowserInstance:
    def __init__(self, agent_name: str, instance_name: str, profile: Path, brave_path: Path):
        self.agent_name = agent_name
        self.name = instance_name
        self.profile = profile
        self.brave_path = brave_path

    @classmethod
    def create(cls, agent_name: str, instance_name: str = "shared", *, home: Path | None = None, environ=None):
        environment = os.environ if environ is None else environ
        agent_name = _validate_name(agent_name, "agent name")
        instance_name = _validate_name(instance_name, "instance name")
        home = Path.home() if home is None else Path(home)
        if instance_name == "shared":
            profile = Path(environment.get(
                "BH_BRAVE_PROFILE",
                home / "Library/Application Support/BraveSoftware/Brave-Browser-Automation",
            ))
        else:
            root = Path(environment.get(
                "BH_BRAVE_INSTANCES_ROOT",
                home / "Library/Application Support/BraveSoftware/Brave-Browser-Automation-Instances",
            ))
            profile = root / instance_name
        brave_path = Path(environment.get("BH_BRAVE_PATH", DEFAULT_BRAVE_PATH))
        return cls(agent_name, instance_name, profile, brave_path)

    def environment(self, base=None) -> dict[str, str]:
        environment = dict(os.environ if base is None else base)
        if self.name == "shared":
            daemon_name = f"agent-{self.agent_name}"
            runtime = f"/private/tmp/bh-{self.agent_name}"
            temporary = f"/private/tmp/bh-{self.agent_name}-tmp"
            shared_state = "/private/tmp/browser-harness-shared"
        else:
            daemon_name = f"agent-{self.name}-{self.agent_name}"
            runtime = f"/private/tmp/bh-{self.name}-{self.agent_name}"
            temporary = f"/private/tmp/bh-{self.name}-{self.agent_name}-tmp"
            shared_state = f"/private/tmp/browser-harness-{self.name}"
        environment.update({
            "BU_NAME": daemon_name,
            "BH_AGENT_WORKSPACE": str(Path(__file__).resolve().parent),
            "BH_RUNTIME_DIR": runtime,
            "BH_TMP_DIR": temporary,
            "BH_SHARED_STATE_DIR": shared_state,
            "BH_BRAVE_INSTANCE": self.name,
            "BH_BRAVE_PROFILE": str(self.profile),
            "BH_TAB_TITLE_PREFIX": self.name,
        })
        return environment

    def endpoint(self) -> str:
        try:
            lines = (self.profile / "DevToolsActivePort").read_text(encoding="utf-8").splitlines()
            port, path = lines[0], lines[1]
        except (FileNotFoundError, OSError, IndexError) as error:
            raise InstanceError(f"browser instance {self.name!r} has no valid DevToolsActivePort") from error
        if not port.isdigit() or not path.startswith("/devtools/browser/"):
            raise InstanceError(f"browser instance {self.name!r} has an invalid DevToolsActivePort")
        return f"ws://127.0.0.1:{port}{path}"

    def _owns_process(self, command: str) -> bool:
        profile_flag = f"--user-data-dir={self.profile}"
        return command.startswith(str(self.brave_path)) and re.search(
            re.escape(profile_flag) + r"(?:\s|$)", command
        ) is not None

    @contextmanager
    def mutation_lock(self):
        self.profile.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock_path = self.profile.parent / f".{self.profile.name}.browser-harness.lock"
        with lock_path.open("a+") as handle:
            os.chmod(lock_path, 0o600)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def restart(
        self,
        *,
        dry_run: bool = False,
        process_reader=read_process_command,
        signal_process=os.kill,
        launch,
        sleep=time.sleep,
        timeout: float = 15.0,
    ) -> dict:
        def perform() -> dict:
            pid = singleton_pid(self.profile)
            if pid is not None:
                original = process_reader(pid)
                if original is not None and not self._owns_process(original):
                    raise InstanceError(
                        f"PID {pid} from {self.profile / 'SingletonLock'} does not own browser instance {self.name!r}"
                    )
            else:
                original = None
            if dry_run:
                return {
                    "instance": self.name,
                    "previous_pid": pid,
                    "restarted": False,
                    "would_restart": True,
                }
            if pid is not None and original is not None:
                if process_reader(pid) != original:
                    raise InstanceError(f"browser instance {self.name!r} changed process ownership before restart")
                signal_process(pid, signal.SIGTERM)
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    current = process_reader(pid)
                    if current is None or current != original:
                        break
                    sleep(0.1)
                else:
                    raise InstanceError(f"browser instance {self.name!r} did not exit gracefully within {timeout:g}s")
            launch()
            return {"instance": self.name, "previous_pid": pid, "restarted": True}

        if dry_run:
            return perform()
        with self.mutation_lock():
            return perform()
