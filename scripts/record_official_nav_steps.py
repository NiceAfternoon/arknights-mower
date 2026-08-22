"""官方导航步骤录制脚本（维护者工具，不随程序分发）。

用法：:

    python scripts/record_official_nav_steps.py PA-1 PA-2 EP-EX-3
    # 或指定导出路径
    python scripts/record_official_nav_steps.py PA-1 -o my_steps.json

连模拟器后，对每个目标关卡调现有 AI 自学导航（``NavigationSolver.run``）走一遍，
成功且记录到步骤的关卡导出成标准 ``nav_steps.json``（stages + patterns，条目结构与
``nav_trie_steps.json`` 一致），并在末尾提示上传到 hot_update 仓库。

注意：每关跑完 ``NavigationSolver.run`` 内部的 ``persist_nav_steps`` 也会把这一步刷新到
本机 ``nav_trie_steps.json``（对维护者本机无害——官方导出是另一份文件，两者互不覆盖）。
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from arknights_mower.utils.log import logger
from arknights_mower.utils.nav_steps import (
    build_official_steps,
    load_nav_file,
    merge_official_steps,
)


def collect_records(
    stages: list[str], navigate
) -> tuple[list[dict], list[dict], list[dict]]:
    """逐关导航，收集成功记录 / 失败清单 / 无步骤跳过清单。

    ``navigate(stage)`` 返回记录 dict（含 stage / stage_type / steps）表示该关跑完；返回
    None 或抛异常视为该关失败。成功但无步骤（命中快捷入口、本就在目标）归入 skipped——
    不算失败：官方没录到步骤可由现有 AI 自学兜底。返回 (成功记录, 失败清单, 跳过清单)。
    """
    ok: list[dict] = []
    failed: list[dict] = []
    skipped: list[dict] = []
    now = datetime.now().isoformat(timespec="seconds")
    for stage in stages:
        logger.info(f"录制导航步骤：{stage}")
        try:
            rec = navigate(stage)
        except Exception as e:
            logger.exception(f"导航失败：{stage}")
            failed.append({"stage": stage, "reason": str(e)})
            continue
        if rec and rec.get("steps"):
            rec["updated_at"] = rec.get("updated_at") or now
            ok.append(rec)
        elif rec:
            skipped.append(
                {
                    "stage": stage,
                    "reason": "导航成功但未记录到步骤（可能命中快捷入口/已在目标），由 AI 自学兜底",
                }
            )
        else:
            failed.append({"stage": stage, "reason": "navigation failed"})
    return ok, failed, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="官方导航步骤录制脚本：连模拟器走 AI 自学导航并导出 nav_steps.json。"
    )
    parser.add_argument("stages", nargs="+", help="目标关卡代码列表，例如 PA-1 EP-EX-3")
    parser.add_argument(
        "-o",
        "--output",
        default="nav_steps.json",
        help="导出的官方步骤文件路径（默认 ./nav_steps.json）",
    )
    parser.add_argument(
        "--no-ocr",
        action="store_true",
        help="跳过 OCR 初始化（无 OCR 资源时降级，导航可能变慢）",
    )
    args = parser.parse_args(argv)

    from arknights_mower.utils import rapidocr

    if not args.no_ocr:
        try:
            rapidocr.initialize_ocr()
        except Exception as e:
            logger.warning(f"OCR 初始化失败（已降级继续）：{e}")

    from arknights_mower.solvers.navigation import NavigationSolver

    try:
        solver = NavigationSolver()
    except Exception as e:
        logger.error(f"连接模拟器失败：{e}")
        print("请先启动模拟器并确保 adb 已注册目标设备。", file=sys.stderr)
        return 1

    def navigate(stage: str) -> dict | None:
        if solver.run(stage):
            return {
                "stage": solver.name,
                "stage_type": solver.stageType,
                "steps": solver.nav_steps,
            }
        return None

    ok, failed, skipped = collect_records(args.stages, navigate)

    fresh = build_official_steps(ok)
    out_path = Path(args.output)
    existing = load_nav_file(out_path) if out_path.exists() else {}
    result = merge_official_steps(existing, fresh)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    from arknights_mower.utils.hot_update import HOT_UPDATE_REPO

    logger.info(
        f"录制完成：成功 {len(ok)} 关，跳过(无步骤/AI 兜底) {len(skipped)} 关，失败 "
        f"{len(failed)} 关，已写入 {out_path}"
    )
    for s in skipped:
        logger.info(f"  {s['stage']}: {s['reason']}")
    for f in failed:
        logger.warning(f"  {f['stage']}: {f['reason']}")
    print(f"\n已导出官方导航步骤：{out_path}")
    print(
        f"请把该文件作为 hot_update 包内的 nav_steps.json，上传到 {HOT_UPDATE_REPO}"
        "仓库并打包发布。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
