"""Exercise the trusted ARM64 release payload with the Android launcher and RapidOCR."""

import argparse
import hashlib
import http.client
import json
import lzma
import os
import secrets
import shutil
import stat
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

SMOKE = """
import sys
import cv2

sys.path.insert(0, '/mower')
from arknights_mower.utils.rapidocr import create_engine

engine = create_engine(threads=2)
image = cv2.cvtColor(cv2.imread('/mower-test.png'), cv2.COLOR_BGR2RGB)
result, elapsed = engine(image, use_det=True, use_cls=True, use_rec=True)
expected = '[卡涅利安]沙缚镣锁'
assert result and result[0][1] == expected, result
assert len(result[0][0]) == 4 and len(elapsed) == 3, (result, elapsed)
print('Android packaged detection, classification and recognition passed:', result[0][1])
"""


def check_service(root, adapter, package, version):
    program = root / "mower"
    shutil.copytree(adapter, program / "mower_android")
    data = root / "mower-data"
    with package.open("rb") as stream:
        active_id = hashlib.file_digest(stream, "sha256").hexdigest()
    programs = data / "mower-programs"
    selected = programs / active_id
    selected.mkdir(parents=True)
    (selected / "mower").symlink_to("/mower", target_is_directory=True)
    state = programs / "active.json"
    state.write_text(json.dumps({"id": active_id, "booting": True, "pending": True}))
    # prepare_files() checks the receipt for an already-installed Android MAA.
    # This UI test does not install or start MaaCore.
    (data / "maa").mkdir()
    shutil.copyfile(adapter / "maa-component-lock.json", data / "maa/.mower-android.json")
    (root / "dev/shm").mkdir(exist_ok=True)
    (root / "dev/shm").chmod(0o1777)
    token = secrets.token_urlsafe(32)
    env = {
        "HOME": "/mower-data", "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8", "TZ": "UTC", "OPENBLAS_NUM_THREADS": "2",
        "OMP_NUM_THREADS": "2", "PYTHONUNBUFFERED": "1",
        "MOWER_ANDROID": "1", "MOWER_SERVICE_RESTART": "1", "MOWER_SOURCE_SELECTED": "1",
        "MOWER_ACTIVE_ID": active_id, "MOWER_DATA_DIR": "/mower-data",
        "MOWER_WEB_BIND": "127.0.0.1", "MOWER_WEB_TOKEN": token, "MOWER_WEB_PORT": "58000",
        "MOWER_BRIDGE_PORT": "1", "MOWER_BRIDGE_TOKEN": secrets.token_urlsafe(32),
        "MOWER_APK_GENERATION": "package-smoke", "MOWER_APK_CODE": "42",
    }
    proc = subprocess.Popen(
        ["chroot", str(root), "/bin/sh", "-c",
         "cd /mower && exec /usr/local/bin/python -m mower_android.launcher"],
        env=env, executable=shutil.which("chroot"),
    )
    def fetch(path):
        conn = http.client.HTTPConnection("127.0.0.1", 58000, timeout=10)
        try:
            conn.request("GET", path, headers={"token": token, "Accept-Encoding": "identity"})
            response = conn.getresponse()
            content = response.read()
            assert response.status == 200, (path, response.status, content[:200])
            return content
        finally:
            conn.close()
    try:
        deadline = time.monotonic() + 120
        while True:
            if proc.poll() is not None:
                raise RuntimeError(f"Android launcher exited with status {proc.returncode}")
            try:
                index = fetch("/")
                break
            except ConnectionRefusedError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.25)
        assert index == (program / "ui/dist/index.html").read_bytes()
        status = json.loads(fetch("/status"))
        assert status["deployment"] == "release" and status["status"] == "stopped", status
        assert status["auto_start_handled"] and status["desktop_startup_handled"], status
        installed = json.loads(fetch("/android/mower-recovery"))["installed"]["version"]
        assert installed.split("+")[0] == version, (installed, version)
        ready_state = json.loads(state.read_text())
        assert ready_state["id"] == active_id and not ready_state.get("booting") and not ready_state.get("pending")
        print("Android launcher served the packaged UI and authenticated stopped status:", installed, flush=True)
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("image", type=Path)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--host-adapter", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(args.package) as update:
        root = Path(tmp) / "rootfs"
        root.mkdir()
        manifest = json.loads(update.read("mower-android.json"))
        assert manifest["format"] == 2 and manifest["min_apk"] == 29
        assert manifest["runtime_api"] == 1 and manifest["arch"] == "arm64"
        runtime = manifest["runtime"]
        print(
            "update bytes:",
            args.package.stat().st_size,
            "rootfs xz bytes:",
            update.getinfo(runtime["file"]).file_size,
            "rootfs file bytes:",
            runtime["unpacked_size"],
            flush=True,
        )
        with tempfile.TemporaryFile() as stored:
            with update.open(runtime["file"]) as wire, lzma.open(wire) as unpacked:
                shutil.copyfileobj(unpacked, stored, 1024 * 1024)
            stored.seek(0)
            with zipfile.ZipFile(stored) as archive:
                names = archive.namelist()
                for name in ("PP-OCRv6_det_small.onnx", "PP-OCRv6_rec_small.onnx"):
                    found = any(n.endswith("/rapidocr/models/" + name) for n in names)
                    assert found == args.baseline, (name, found, args.baseline)
                for suffix in (
                    "/rapidocr/models/ch_ppocr_mobile_v2.0_cls_mobile.onnx",
                    "/ddddocr/common_det.onnx",
                    "/ddddocr/common_old.onnx",
                    "/pnnx/pnnx",
                ):
                    assert any(
                        i.filename.endswith(suffix) and i.file_size > 0
                        for i in archive.infolist()
                    ), suffix
                assert (
                    sum(i.file_size for i in archive.infolist())
                    == runtime["unpacked_size"]
                )
                archive.extractall(root)
                for entry in archive.infolist():
                    mode = (entry.external_attr >> 16) & 0o777
                    if mode:
                        (root / entry.filename).chmod(mode)
        for name, target in json.loads((root / ".symlinks.json").read_text()).items():
            link = root / name
            link.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(target, link)
        os.mknod(root / "dev/null", stat.S_IFCHR | 0o666, os.makedev(1, 3))
        for entry in update.infolist():
            if entry.filename.startswith("mower/"):
                update.extract(entry, root)
        shutil.copyfile(args.image, root / "mower-test.png")
        subprocess.run(
            ["chroot", str(root), "/usr/local/bin/python", "-c", SMOKE], check=True
        )
        if args.host_adapter:
            check_service(root, args.host_adapter, args.package, manifest["version"])


if __name__ == "__main__":
    main()
