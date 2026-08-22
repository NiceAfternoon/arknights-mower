"""资源包 version.json 的纯逻辑（无重依赖，可直接单测）。

- pick_latest_activity / pick_latest_gacha：从活动/卡池表取"最新一个"。
- 包内容哈希：决定 res_version 的哈希部分，反映实际产物内容是否变化。

auto_get_res_new.py 生成完后据此写 version.json；
MowerResource 管线发布时从本模块导入 RES_PACKAGE_* 打包（单一来源，避免两处漂移）。
"""

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 资源包文件集（相对仓库根）：生成脚本的产出，内容哈希覆盖的就是这些。
RES_PACKAGE_DIRS = (
    "ui/public/depot",
    "ui/public/avatar",
    "ui/public/building_skill",
)
RES_PACKAGE_MODELS = (
    "arknights_mower/models/NORMAL.pkl",
    "arknights_mower/models/CONSUME.pkl",
    "arknights_mower/models/recruit.pkl",
    "arknights_mower/models/recruit_result.pkl",
    "arknights_mower/models/operator_room.model",
    "arknights_mower/models/operator_select.model",
    "arknights_mower/models/operator_train.model",
)
RES_PACKAGE_DATA = (
    "arknights_mower/data/agent.json",
    "arknights_mower/data/agent_profession.json",
    "arknights_mower/data/key_mapping.json",
    "arknights_mower/data/stage_data_full.json",
    "arknights_mower/data/stage_order.json",
    "arknights_mower/data/recruit.json",
    "arknights_mower/data/recruit_result.json",
    "arknights_mower/data/skill_data.json",
    "arknights_mower/data/workshop_formula.json",
)


def package_file_paths(root) -> list:
    """展开资源包实际存在的文件（相对 root 的路径），按路径排序。"""
    root = Path(root)
    rels = []
    for rel in RES_PACKAGE_DIRS:
        d = root / rel
        if d.is_dir():
            rels.extend(p.relative_to(root) for p in d.rglob("*") if p.is_file())
    for rel in RES_PACKAGE_MODELS + RES_PACKAGE_DATA:
        p = root / rel
        if p.is_file():
            rels.append(p.relative_to(root))
    return sorted(rels)


def content_hash(root, rels) -> str:
    """对相对路径文件集算聚合 sha256（含路径，结果与顺序无关）。"""
    root = Path(root)
    digest = hashlib.sha256()
    for rel in sorted(rels, key=lambda p: p.as_posix()):
        digest.update(rel.as_posix().encode("utf-8"))
        digest.update(b"\0")
        with open(root / rel, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _pick_latest(entries, filter_field, skip_keys, time_key, name_key) -> dict:
    """过滤掉 filter_field 含任一 skip_key 的条目，取 time_key 最大者投影。"""
    kept = [
        e
        for e in entries
        if not any(k in (e.get(filter_field) or "") for k in skip_keys)
    ]
    if not kept:
        return {}
    latest = max(kept, key=lambda e: e.get(time_key, 0))
    return {
        "name": latest.get(name_key),
        "time": latest.get(time_key),
        "endTime": latest.get("endTime"),
    }


def pick_latest_activity(activity_table: dict) -> dict:
    """活动表 basicInfo 里开启时间最新的一个（剔签到/预约/收藏夹类）。"""
    return _pick_latest(
        activity_table.get("basicInfo", {}).values(),
        "type",
        ("CHECKIN", "ONLY", "COLLECTION"),
        "startTime",
        "name",
    )


def pick_latest_gacha(gacha_table: dict) -> dict:
    """卡池表 gachaPoolClient 里开启时间最新的一个（剔标准池）。"""
    return _pick_latest(
        gacha_table.get("gachaPoolClient", []),
        "gachaPoolName",
        ("适合多种场合的强力干员",),
        "openTime",
        "gachaPoolName",
    )


def display_version(version_info: dict) -> str:
    """客户端展示用可读版本号：较晚开启的 activity/gacha 的 name + #MMDD（北京时区）。"""
    later = max(
        (version_info.get("activity") or {}, version_info.get("gacha") or {}),
        key=lambda e: e.get("time", 0),
    )
    name = later.get("name")
    if not name or not later.get("time"):
        return ""
    mmdd = datetime.fromtimestamp(
        later["time"], tz=timezone(timedelta(hours=8))
    ).strftime("%m%d")
    return f"{name}#{mmdd}"
