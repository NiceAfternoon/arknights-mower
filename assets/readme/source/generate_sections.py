#!/usr/bin/env python3
"""Generate the coordinated README section-title SVGs."""

from __future__ import annotations

from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SECTIONS = [
    ("proof", "01", "INTERFACE & OUTPUT", "界面与运行结果", "#18A058"),
    ("capabilities", "02", "AUTOMATION TASKS", "支持的自动化任务", "#F0A020"),
    ("workflow", "03", "EXECUTION FLOW", "任务执行流程", "#2080F0"),
    ("start", "04", "INSTALL & RUN", "安装与第一次运行", "#18A058"),
    ("build", "05", "RUN · TEST · PACKAGE", "源码运行、测试与打包", "#F0A020"),
    ("community", "06", "COMMUNITY & NOTES", "交流、反馈与项目说明", "#D03050"),
]


def render(slug: str, number: str, label: str, title: str, accent: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="138" viewBox="0 0 1200 138" role="img" aria-labelledby="title desc">
  <title id="title">{escape(number)} {escape(title)}</title>
  <desc id="desc">Mower README 中“{escape(title)}”章节的标题。</desc>
  <defs>
    <pattern id="section-grid" width="42" height="42" patternUnits="userSpaceOnUse">
      <path d="M42 0H0V42" fill="none" stroke="#E1DED4" stroke-width="1"/>
    </pattern>
  </defs>
  <rect width="1200" height="138" rx="24" fill="#F3F0E7"/>
  <rect width="1200" height="138" rx="24" fill="url(#section-grid)" opacity="0.68"/>
  <g transform="translate(54 26)">
    <text fill="#747E78" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="17" font-weight="800" letter-spacing="2.3">{escape(number)} · {escape(label)}</text>
    <rect y="25" width="54" height="6" rx="3" fill="{accent}"/>
    <text y="86" fill="#131B17" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', sans-serif" font-size="43" font-weight="800">{escape(title)}</text>
  </g>
  <g transform="translate(918 20)">
    <path d="M0 48H88" stroke="#CAC8C0" stroke-width="4" stroke-linecap="round"/>
    <circle cx="0" cy="48" r="8" fill="{accent}"/>
    <circle cx="44" cy="48" r="6" fill="#D3D1C9"/>
    <circle cx="88" cy="48" r="6" fill="#D3D1C9"/>
    <text x="218" y="98" text-anchor="end" fill="#D5D3CB" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif" font-size="74" font-weight="850">{escape(number)}</text>
  </g>
</svg>
'''


def main() -> None:
    for slug, number, label, title, accent in SECTIONS:
        (ROOT / f"section-{slug}.svg").write_text(
            render(slug, number, label, title, accent), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
