"""Exercise RapidOCR using only the trusted ARM64 release payload and a test image."""

import argparse
import json
import lzma
import os
import shutil
import stat
import subprocess
import tempfile
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("image", type=Path)
    parser.add_argument("--baseline", action="store_true")
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


if __name__ == "__main__":
    main()
