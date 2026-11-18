"""Separate the DWARF in a freshly collected Linux PyInstaller bundle."""

import argparse
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path


def _has_dwarf(binary: Path) -> bool:
    if binary.is_symlink() or not binary.is_file():
        return False
    with binary.open("rb") as source:
        if source.read(4) != b"\x7fELF":
            return False
    sections = subprocess.check_output(["readelf", "-SW", binary])
    return re.search(rb"\]\s+\.z?debug_info\s", sections) is not None


def split_linux_debug_symbols(bundle: Path):
    bundle = bundle.resolve(strict=True)
    internal = bundle / "_internal"
    if not internal.is_dir():
        raise ValueError(f"Missing PyInstaller contents directory: {internal}")

    # The two launchers outside _internal carry appended PyInstaller archives.
    # objcopy only writes ELF sections and would discard those archives.
    with tempfile.TemporaryDirectory(dir=bundle.parent) as staging:
        work = Path(staging)
        archive = work / f"{bundle.name}-linux-debug.tar.gz"
        replacements = []
        with tarfile.open(archive, "w:gz", compresslevel=6) as symbols:
            for binary in sorted(internal.rglob("*")):
                if not _has_dwarf(binary):
                    continue

                relative = binary.relative_to(bundle.parent)
                debug = work / relative.parent / ".debug" / (binary.name + ".debug")
                debug.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    ["objcopy", "--only-keep-debug", binary, debug], check=True
                )
                stripped = work / relative
                subprocess.run(
                    [
                        "objcopy",
                        "--strip-debug",
                        "--remove-section=.gnu_debuglink",
                        f"--add-gnu-debuglink={debug}",
                        binary,
                        stripped,
                    ],
                    check=True,
                )
                shutil.copymode(binary, stripped)
                symbols.add(debug, arcname=debug.relative_to(work))
                replacements.append((stripped, binary))

        archive.replace(bundle.parent / archive.name)
        for stripped, binary in replacements:
            stripped.replace(binary)
        print(f"Separated Linux debug symbols from {len(replacements)} ELF files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="fresh PyInstaller COLLECT directory")
    split_linux_debug_symbols(parser.parse_args().bundle)
