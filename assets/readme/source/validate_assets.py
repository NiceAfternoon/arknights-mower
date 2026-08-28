#!/usr/bin/env python3
"""Validate README assets, local references, and the GIF loop."""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageChops

REPO = Path(__file__).resolve().parents[3]
ROOT = REPO / "assets" / "readme"


def main() -> None:
    svgs = sorted(ROOT.glob("*.svg"))
    print("svg_count", len(svgs))
    for svg in svgs:
        root = ET.parse(svg).getroot()
        raw = svg.read_text(encoding="utf-8")
        assert root.attrib.get("viewBox", "").startswith("0 0 1200 "), svg
        assert "<title" in raw and "<desc" in raw, svg
        assert "<script" not in raw and "foreignObject" not in raw, svg
        assert "<image" not in raw, svg
        print("svg_ok", svg.name, root.attrib["viewBox"])

    readme = (REPO / "README.md").read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="(\./[^"#?]+)', readme)
    missing = [ref for ref in refs if not (REPO / ref[2:]).exists()]
    print("local_refs", len(refs), "missing", missing)
    assert not missing

    gif = Image.open(ROOT / "hero.gif")
    frames: dict[int, Image.Image] = {}
    for index in [0, 57, 120, 161]:
        gif.seek(index)
        frames[index] = gif.convert("RGBA").copy()
    hold_identical = ImageChops.difference(frames[57], frames[120]).getbbox() is None
    loop_identical = ImageChops.difference(frames[0], frames[161]).getbbox() is None
    print("gif", gif.size, gif.n_frames, "loop", gif.info.get("loop"))
    print("hold_identical", hold_identical)
    print("loop_identical", loop_identical)
    print("transparent_corner_alpha", frames[0].getpixel((0, 0))[3])
    assert hold_identical and loop_identical

    for relative in [
        "showcase.png",
        "preview/readme-desktop.png",
        "preview/readme-mobile.png",
        "preview/hero-storyboard.png",
    ]:
        path = ROOT / relative
        image = Image.open(path)
        print(relative, image.size, path.stat().st_size)


if __name__ == "__main__":
    main()
