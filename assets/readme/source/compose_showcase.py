#!/usr/bin/env python3
"""Compose real Mower screenshots into the README proof wall."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "assets" / "readme" / "showcase.png"
FONT_DIR = Path("C:/Windows/Fonts")


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = {
        "sans": ["msyh.ttc", "segoeui.ttf"],
        "bold": ["msyhbd.ttc", "seguisb.ttf", "segoeuib.ttf"],
        "mono": ["consola.ttf", "cour.ttf"],
    }[name]
    for candidate in candidates:
        path = FONT_DIR / candidate
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default(size=size)


def rounded_screenshot(
    path: Path, size: tuple[int, int], radius: int = 18
) -> Image.Image:
    screenshot = Image.open(path).convert("RGB")
    screenshot = ImageOps.fit(screenshot, size, method=Image.Resampling.LANCZOS)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size[0], size[1]), radius=radius, fill=255
    )
    result = Image.new("RGBA", size, (255, 255, 255, 0))
    result.paste(screenshot, mask=mask)
    return result


def artifact(
    image_path: Path,
    size: tuple[int, int],
    label: str,
    accent: str,
    angle: float,
) -> Image.Image:
    frame = Image.new("RGBA", (size[0] + 28, size[1] + 72), (0, 0, 0, 0))
    draw = ImageDraw.Draw(frame)
    draw.rounded_rectangle(
        (0, 0, frame.width - 1, frame.height - 1),
        radius=24,
        fill="#FFFEFA",
        outline="#D8D5CB",
        width=2,
    )
    draw.rounded_rectangle((18, 16, 74, 23), radius=4, fill=accent)
    draw.text((18, 30), label, font=font("sans", 18), fill="#46534C")
    frame.alpha_composite(rounded_screenshot(image_path, size), (14, 58))
    return frame.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)


def paste_with_shadow(
    canvas: Image.Image, item: Image.Image, position: tuple[int, int]
) -> None:
    shadow = Image.new("RGBA", item.size, (0, 0, 0, 0))
    alpha = item.getchannel("A").point(lambda value: 48 if value > 0 else 0)
    shadow.putalpha(alpha)
    canvas.alpha_composite(shadow, (position[0] + 12, position[1] + 15))
    canvas.alpha_composite(item, position)


def main() -> None:
    canvas = Image.new("RGBA", (1200, 720), "#F3F0E7")
    draw = ImageDraw.Draw(canvas)
    for x in range(0, 1201, 40):
        draw.line((x, 0, x, 720), fill="#E2DFD5", width=1)
    for y in range(0, 721, 40):
        draw.line((0, y, 1200, y), fill="#E2DFD5", width=1)
    draw.rounded_rectangle((0, 0, 1199, 719), radius=30, outline="#E3E0D6", width=2)

    draw.text((58, 44), "PROJECT INTERFACES", font=font("mono", 19), fill="#6D7771")
    draw.rounded_rectangle((58, 76, 114, 82), radius=3, fill="#18A058")
    draw.text(
        (58, 102),
        "排班编辑器、运行日志和基建报表",
        font=font("bold", 42),
        fill="#131B17",
    )
    draw.text((60, 163), "PLAN / LOG / REPORT", font=font("mono", 19), fill="#819087")

    plan = artifact(
        REPO / "img" / "plan-editor.png",
        (700, 442),
        "PLAN EDITOR · 排班编辑器",
        "#18A058",
        -1.1,
    )
    settings = artifact(
        REPO / "img" / "settings.png",
        (370, 234),
        "SETTINGS · 设备与任务设置",
        "#2080F0",
        2.4,
    )
    log = artifact(
        REPO / "img" / "log.png", (450, 284), "RUN LOG · 运行日志", "#F0A020", -3.2
    )
    report = artifact(
        REPO / "img" / "riic-report.png",
        (390, 246),
        "RIIC REPORT · 基建报表",
        "#D03050",
        2.7,
    )

    paste_with_shadow(canvas, settings, (760, 152))
    paste_with_shadow(canvas, plan, (325, 184))
    paste_with_shadow(canvas, log, (34, 375))
    paste_with_shadow(canvas, report, (770, 430))

    canvas.convert("RGB").save(OUT, optimize=True, quality=95)


if __name__ == "__main__":
    main()
