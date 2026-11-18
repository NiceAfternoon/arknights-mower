"""Round-trip two trusted release packages with the official publisher and Android installer."""

import argparse
import json
import runpy
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PUBLISHER = "https://raw.githubusercontent.com/ArkMowers/MowerRelease/6b84f90626070ae53d751f5fb1bb2eb88db17268/scripts/build_ota.py"
INSTALLER = "https://raw.githubusercontent.com/ALEXsun0/arknights-mower-android/ad19d1963e4e38d2d4fb82d8899ef6d4822d6951/runtime/mower_android/mower_ota.py"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("rebuilt", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        publisher, installer = stage / "build_ota.py", stage / "mower_ota.py"
        for url, path in ((PUBLISHER, publisher), (INSTALLER, installer)):
            subprocess.run(
                [
                    "curl",
                    "--fail",
                    "--silent",
                    "--show-error",
                    "--location",
                    "--retry",
                    "3",
                    "--connect-timeout",
                    "15",
                    "--max-time",
                    "90",
                    url,
                    "--output",
                    str(path),
                ],
                check=True,
            )
        with (
            zipfile.ZipFile(args.baseline) as before,
            zipfile.ZipFile(args.target) as after,
        ):
            source_version = json.loads(before.read("mower-android.json"))["version"]
            expected = json.loads(after.read("mower-android.json"))
            target_version = expected["version"]
            assert source_version != target_version, (
                "use distinct test versions for OTA"
            )
            before.extractall(stage / "installed")
        delta = stage / "ota.zip"
        subprocess.run(
            [
                sys.executable,
                str(publisher),
                str(args.baseline),
                str(args.target),
                str(delta),
                "--from-version",
                source_version,
                "--to-version",
                target_version,
                "--platform",
                "android",
                "--arch",
                "arm64",
            ],
            check=True,
        )
        with zipfile.ZipFile(delta) as ota:
            format_version = json.loads(ota.read("ota.json"))["format"]
            assert format_version == 2, format_version
        runpy.run_path(str(installer))["reconstruct"](
            delta,
            stage / "installed",
            args.rebuilt,
            from_version=source_version,
            to_version=target_version,
        )
        with zipfile.ZipFile(args.rebuilt) as rebuilt:
            actual = json.loads(rebuilt.read("mower-android.json"))
            # The host may recompress logically identical runtime contents using another XZ encoder.
            for manifest in (expected, actual):
                del manifest["runtime"]["sha256"]
            assert actual == expected, (actual, expected)
        print(
            "Android format-2 OTA reconstructed:",
            source_version,
            "->",
            target_version,
            "delta bytes:",
            delta.stat().st_size,
        )


if __name__ == "__main__":
    main()
