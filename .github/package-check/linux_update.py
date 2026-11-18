"""Apply a real full package to a disposable frozen Linux installation."""

import hashlib
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import requests

TEMP = Path(os.environ["RUNNER_TEMP"]).resolve()
INSTALL = TEMP / "installed"
PACKAGE = TEMP / "after.tar.gz"
DATA = TEMP / "desktop-check"
ARCH = os.environ["ARCH"]
OLD = "0.0.0-alpha.1"
NEW = "0.0.0-alpha.2"
STATE = DATA / "tmp/updates" / hashlib.sha256(os.fsencode(INSTALL)).hexdigest()[:20]


def split_witness():
    with tarfile.open("dist/mower-linux-debug.tar.gz") as archive:
        debug = next(
            Path(m.name)
            for m in archive
            if m.isfile()
            and ".so" in Path(m.name).name
            and Path(m.name).parent.name == ".debug"
        )
    relative = debug.relative_to("mower").parent.parent / debug.name.removesuffix(
        ".debug"
    )
    sections = subprocess.check_output(["readelf", "-SW", INSTALL / relative])
    assert b".debug_info" in sections or b".zdebug_info" in sections, relative
    with tarfile.open(PACKAGE, "r|gz") as archive:
        for member in archive:
            if member.name == "mower/" + relative.as_posix():
                return relative, hashlib.file_digest(
                    archive.extractfile(member), "sha256"
                ).digest()
    raise AssertionError(f"Missing replacement library: {relative}")


def wait(description, timeout, check):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (requests.ConnectionError, requests.Timeout, FileNotFoundError) as exc:
            last = exc
        time.sleep(1)
    raise RuntimeError(
        f"Timed out waiting for {description}; last transport error: {last}"
    )


def run():
    relative, expected_hash = split_witness()
    subprocess.run(
        [
            sys.executable,
            "scripts/inject_version.py",
            OLD,
            "--system",
            "linux",
            "--arch",
            ARCH,
            "--path",
            INSTALL / "_internal/arknights_mower/__init__.py",
        ],
        check=True,
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    token = secrets.token_urlsafe(32)
    if os.getenv("GITHUB_ACTIONS"):
        print(f"::add-mask::{token}", flush=True)
    config = DATA / "config/conf.yml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps(
            {
                "webview": {"token": token, "port": port, "tray": False},
                "start_automatically": False,
                "screenshot_interval": 731,
                "resource_update": {"enable": False, "auto_update": False},
            }
        ),
        encoding="utf-8",
    )
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"token": token, "Origin": origin, "X-Mower-Update": "1"})

    def api(method, path, timeout=5, **kwargs):
        response = session.request(method, origin + path, timeout=timeout, **kwargs)
        if not response.ok:
            raise RuntimeError(
                f"{path} HTTP {response.status_code}: {response.text[:600]}"
            )
        return response.json()

    def registrations():
        return [
            json.loads(p.read_bytes()) for p in (STATE / "instances").glob("*.json")
        ]

    def ready(version, job=""):
        registered = next(
            (
                r
                for r in registrations()
                if r.get("kind") == "instance"
                and r.get("ready")
                and r.get("port") == port
                and r.get("root") == str(INSTALL)
                and r.get("restart_job") == job
            ),
            None,
        )
        if not registered:
            return None
        info = api("GET", "/software-update/info")
        assert info["deployment"] == "release" and not info["blockers"], info[
            "blockers"
        ]
        return registered if info["version"] == version else None

    def stop_owned_processes():
        # Both the updater and restarted app launch detached. Only stop processes
        # executing the disposable app or its worker copy in this test's data tree.
        for proc in Path("/proc").iterdir():
            if not proc.name.isdecimal():
                continue
            try:
                executable = (proc / "exe").resolve(strict=True)
                if executable.is_relative_to(INSTALL) or executable.is_relative_to(
                    STATE
                ):
                    os.kill(int(proc.name), signal.SIGTERM)
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                continue

    with (DATA / "desktop-launch.log").open("wb") as log:
        proc = subprocess.Popen(
            [INSTALL / "mower"],
            cwd=INSTALL,
            env={**os.environ, "MOWER_DATA_DIR": str(DATA), "MOWER_BACKGROUND": "1"},
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:

            def booted():
                if proc.poll() is not None:
                    raise RuntimeError(
                        f"Baseline desktop exited with {proc.returncode}"
                    )
                return ready(OLD)

            initial = wait("baseline desktop readiness", 160, booted)
            assert api("GET", "/conf")["screenshot_interval"] == 731
            with PACKAGE.open("rb") as source:
                plan = api(
                    "POST",
                    "/software-update/manual/inspect",
                    timeout=200,
                    files={
                        "file": (f"mower_{ARCH}.tar.gz", source, "application/gzip")
                    },
                )
            assert (
                plan["ok"]
                and plan["version"] == "v" + NEW
                and plan["package_kind"] == "full"
            ), plan
            started = api(
                "POST",
                "/software-update/start",
                timeout=150,
                json={"check_id": plan["check_id"], "background": True},
            )
            assert started["ok"], started
            job = started["id"]
            observed = None

            def finished():
                nonlocal observed
                status = api("GET", "/software-update/status")
                if status.get("id") != job:
                    return False
                progress = (status["status"], status.get("phase"))
                if progress != observed:
                    print("Update", job, *progress, flush=True)
                    observed = progress
                if progress[0] in ("failed", "cancelled"):
                    raise RuntimeError(status.get("message", str(progress)))
                return progress[0] == "succeeded"

            wait("copied updater success", 420, finished)
            final = wait("replacement process readiness", 45, lambda: ready(NEW, job))
            assert final["pid"] != initial["pid"]
            assert api("GET", "/conf")["screenshot_interval"] == 731
            with (INSTALL / relative).open("rb") as source:
                assert hashlib.file_digest(source, "sha256").digest() == expected_hash
            sections = subprocess.check_output(["readelf", "-SW", INSTALL / relative])
            assert (
                b".gnu_debuglink" in sections
                and b".debug_info" not in sections
                and b".zdebug_info" not in sections
            )
            subprocess.run(
                [INSTALL / "_internal/platform-tools/adb", "version"], check=True
            )
            print(
                f"{ARCH}: {OLD} -> {NEW}, PID {initial['pid']} -> {final['pid']}; "
                f"configuration and stripped {relative} verified.",
                flush=True,
            )
        finally:
            stop_owned_processes()
            session.close()


if __name__ == "__main__":
    run()
